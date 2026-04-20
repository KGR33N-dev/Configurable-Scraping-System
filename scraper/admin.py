import json
import re
from typing import Any, Optional

from django.contrib import admin
from django.utils.html import mark_safe, escape

from .models import ScrapingSource, ScrapedResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_data(data: Any) -> str:
    """
    Render a JSONB field as readable HTML.

    Strategy:
      1. List of dicts  → HTML table (headers from first item's keys)
      2. Any other JSON → syntax-highlighted <pre> block (VS Code Dark+ colors)
      3. Empty / None   → placeholder message
    """
    if not data:
        return '<em style="color:#999">— no data —</em>'

    # Case 1: list of dicts → table
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        headers: list[str] = list(data[0].keys())

        header_cells: str = "".join(
            f'<th style="padding:6px 12px;border-bottom:2px solid #444;'
            f'text-align:left;white-space:nowrap">{escape(str(h))}</th>'
            for h in headers
        )

        rows_html: str = ""
        for i, row in enumerate(data):
            bg: str = "#2a2a2a" if i % 2 == 0 else "#232323"
            cells: str = "".join(
                f'<td style="padding:5px 12px;border-bottom:1px solid #333;'
                f'vertical-align:top;max-width:300px;word-break:break-word">'
                f'{escape(str(row.get(h, "")))}</td>'
                for h in headers
            )
            rows_html += f'<tr style="background:{bg}">{cells}</tr>'

        return (
            '<div style="overflow-x:auto">'
            '<table style="border-collapse:collapse;width:100%;'
            'font-family:monospace;font-size:13px;color:#e0e0e0;'
            'background:#1e1e1e;border-radius:6px;overflow:hidden">'
            f'<thead><tr style="background:#111">{header_cells}</tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            '</table></div>'
        )

    # Case 2: pretty JSON with syntax highlighting
    try:
        pretty: str = json.dumps(data, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        pretty = str(data)

    highlighted_lines: list[str] = []
    for line in pretty.splitlines():
        escaped: str = escape(line)
        # Keys (quoted string before colon)
        escaped = re.sub(
            r'(&quot;)([^&]+)(&quot;)(\s*:)',
            r'<span style="color:#9cdcfe">\1\2\3</span>\4',
            escaped,
        )
        # String values
        escaped = re.sub(
            r'(:\s*)(&quot;)([^&]*)(&quot;)',
            r'\1<span style="color:#ce9178">\2\3\4</span>',
            escaped,
        )
        # Numbers
        escaped = re.sub(
            r'(:\s*)(-?\d+\.?\d*)',
            r'\1<span style="color:#b5cea8">\2</span>',
            escaped,
        )
        # Literals
        escaped = re.sub(
            r'\b(true|false|null)\b',
            r'<span style="color:#569cd6">\1</span>',
            escaped,
        )
        highlighted_lines.append(escaped)

    highlighted: str = "<br>".join(highlighted_lines)

    return (
        '<pre style="background:#1e1e1e;color:#d4d4d4;padding:14px 18px;'
        'border-radius:8px;font-size:13px;line-height:1.6;overflow-x:auto;'
        'max-height:500px;overflow-y:auto;margin:0;white-space:pre-wrap;'
        'word-break:break-word;border:1px solid #333">'
        f'{highlighted}</pre>'
    )


def _render_diff(old_data: Any, new_data: Any) -> str:
    """
    Render a colour-coded diff between two JSONB values.

    For dicts: each key is shown as added (green), removed (red),
    changed (amber with from→to), or unchanged (grey, collapsed).
    For non-dict payloads: a simple before/after comparison.
    """
    STYLE_BASE = 'font-family:monospace;font-size:13px;padding:6px 12px;border-radius:4px;margin:2px 0;display:block;word-break:break-word;'

    def _val(v: Any) -> str:
        try:
            return json.dumps(v, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(v)

    if not isinstance(old_data, dict) or not isinstance(new_data, dict):
        if old_data == new_data:
            return '<em style="color:#999">— data identical —</em>'
        return (
            f'<div style="{STYLE_BASE}background:#4a1010;color:#f88">'
            f'<strong>Before:</strong><br><pre style="margin:4px 0;white-space:pre-wrap">{escape(_val(old_data))}</pre></div>'
            f'<div style="{STYLE_BASE}background:#0f3a1a;color:#8f8">'
            f'<strong>After:</strong><br><pre style="margin:4px 0;white-space:pre-wrap">{escape(_val(new_data))}</pre></div>'
        )

    all_keys = sorted(set(old_data.keys()) | set(new_data.keys()))
    rows: list[str] = []

    added = removed = changed = 0
    for key in all_keys:
        in_old = key in old_data
        in_new = key in new_data
        k = escape(str(key))

        if in_new and not in_old:
            added += 1
            rows.append(
                f'<div style="{STYLE_BASE}background:#0f3a1a;color:#8f8">'
                f'<span style="opacity:.7">+</span> <strong>{k}</strong>: '
                f'<span style="color:#b3ffb3">{escape(_val(new_data[key]))}</span></div>'
            )
        elif in_old and not in_new:
            removed += 1
            rows.append(
                f'<div style="{STYLE_BASE}background:#4a1010;color:#f88">'
                f'<span style="opacity:.7">−</span> <strong>{k}</strong>: '
                f'<span style="color:#ffb3b3">{escape(_val(old_data[key]))}</span></div>'
            )
        elif old_data[key] != new_data[key]:
            changed += 1
            rows.append(
                f'<div style="{STYLE_BASE}background:#3d2e00;color:#ffd">'
                f'<span style="opacity:.7">~</span> <strong>{k}</strong>:<br>'
                f'&nbsp;&nbsp;<span style="color:#f88;font-size:12px">− {escape(_val(old_data[key]))}</span><br>'
                f'&nbsp;&nbsp;<span style="color:#8f8;font-size:12px">+ {escape(_val(new_data[key]))}</span></div>'
            )
        else:
            rows.append(
                f'<div style="{STYLE_BASE}background:#1e1e1e;color:#555">'
                f'&nbsp;&nbsp;<strong>{k}</strong>: {escape(_val(old_data[key]))}</div>'
            )

    summary = (
        f'<div style="margin-bottom:8px;font-family:monospace;font-size:12px">'
        f'<span style="color:#8f8;margin-right:12px">+{added} added</span>'
        f'<span style="color:#f88;margin-right:12px">−{removed} removed</span>'
        f'<span style="color:#ffd">~{changed} changed</span></div>'
    )

    return (
        f'<div style="background:#111;border:1px solid #333;border-radius:8px;'
        f'padding:12px;max-height:600px;overflow-y:auto">'
        f'{summary}'
        + ''.join(rows)
        + '</div>'
    )


# ---------------------------------------------------------------------------
# Inline
# ---------------------------------------------------------------------------

class ScrapedResultInline(admin.TabularInline):
    """Show up to 5 latest results directly on the ScrapingSource change page."""

    model = ScrapedResult
    extra = 0
    max_num = 5
    readonly_fields = ['created_at', 'data_pretty']

    def data_pretty(self, obj: ScrapedResult) -> str:
        # mark_safe is safe here — _render_data() escapes all user data.
        # format_html() would misinterpret { } in CSS/JSON as template placeholders.
        return mark_safe(_render_data(obj.data))
    data_pretty.short_description = 'Data'


# ---------------------------------------------------------------------------
# ScrapingSource
# ---------------------------------------------------------------------------

@admin.register(ScrapingSource)
class ScrapingSourceAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'url', 'frequency_minutes',
        'is_active', 'last_scraped_at', 'last_error', 'result_count',
    ]
    list_filter = ['is_active', 'extraction_type', 'last_scraped_at']
    search_fields = ['name', 'url']
    ordering = ['-last_scraped_at']
    inlines = [ScrapedResultInline]

    readonly_fields = ['last_scraped_at', 'last_error', 'result_count', 'rules_rendered']
    fields = [
        'name', 'url', 'extraction_type', 'frequency_minutes', 'is_active',
        'rules',          # editable textarea
        'rules_rendered', # read-only preview of saved rules
        'last_scraped_at', 'last_error',
    ]

    def result_count(self, obj: ScrapingSource) -> int:
        """Total number of scraped results for this source."""
        return obj.results.count()
    result_count.short_description = 'Result Count'

    def rules_rendered(self, obj: ScrapingSource) -> str:
        """Syntax-highlighted read-only preview of the saved rules JSON."""
        if not obj.rules:
            return mark_safe('<em style="color:#999">— no rules —</em>')
        return mark_safe(_render_data(obj.rules))
    rules_rendered.short_description = 'Rules Preview (read-only)'


# ---------------------------------------------------------------------------
# ScrapedResult
# ---------------------------------------------------------------------------

@admin.register(ScrapedResult)
class ScrapedResultAdmin(admin.ModelAdmin):
    """
    Read-only result viewer.

    All fields are immutable — results are an append-only audit log.
    'data_rendered' replaces the raw 'data' field with a formatted view:
      list of dicts → HTML table
      other JSON    → syntax-highlighted <pre>
    'diff_rendered' is shown below when has_changed=True, comparing
    this result to the immediately preceding one.
    """

    list_display = ['source', 'created_at', 'has_changed_badge', 'data_preview']
    list_filter = ['source', 'has_changed', 'created_at']
    search_fields = ['source__name', 'data__icontains']
    readonly_fields = ['id', 'source', 'created_at', 'has_changed', 'data_rendered', 'diff_rendered']
    fields = ['id', 'source', 'created_at', 'has_changed', 'data_rendered', 'diff_rendered']
    ordering = ['-created_at']

    def has_changed_badge(self, obj: ScrapedResult) -> str:
        """Coloured badge indicating whether data changed on this scrape."""
        if obj.has_changed is True:
            return mark_safe(
                '<span style="background:#2e7d32;color:#fff;padding:2px 8px;'
                'border-radius:4px;font-size:12px;font-weight:600">✔ Changed</span>'
            )
        if obj.has_changed is False:
            return mark_safe(
                '<span style="background:#555;color:#ccc;padding:2px 8px;'
                'border-radius:4px;font-size:12px">– No change</span>'
            )
        return mark_safe(
            '<span style="background:#333;color:#999;padding:2px 8px;'
            'border-radius:4px;font-size:12px">? Unknown</span>'
        )
    has_changed_badge.short_description = 'Changed'
    has_changed_badge.admin_order_field = 'has_changed'

    def data_preview(self, obj: ScrapedResult) -> str:
        """Truncated data string for the list column."""
        data_str: str = str(obj.data)
        return data_str[:80] + '…' if len(data_str) > 80 else data_str
    data_preview.short_description = 'Data Preview'

    def data_rendered(self, obj: ScrapedResult) -> str:
        """Full formatted data view on the detail page (table or highlighted JSON)."""
        return mark_safe(_render_data(obj.data))
    data_rendered.short_description = 'Data'

    def diff_rendered(self, obj: ScrapedResult) -> str:
        """Colour-coded diff vs. the previous scrape — shown only when has_changed=True."""
        if obj.has_changed is not True:
            return mark_safe('<em style="color:#555">— no diff (data unchanged or unknown) —</em>')

        previous: Optional[ScrapedResult] = (
            ScrapedResult.objects
            .filter(source=obj.source, created_at__lt=obj.created_at)
            .order_by('-created_at')
            .only('data')
            .first()
        )

        if previous is None:
            return mark_safe('<em style="color:#555">— first scrape for this source, no previous result to compare —</em>')

        return mark_safe(_render_diff(previous.data, obj.data))
    diff_rendered.short_description = 'Diff vs. Previous'
