from typing import Any
from rest_framework import serializers
from .models import ScrapingSource, ScrapedResult
from jsonschema import validate, ValidationError as JsonSchemaError


class ScrapedResultSerializer(serializers.ModelSerializer):
    """Full result serializer — used by /api/results/."""

    class Meta:
        model = ScrapedResult
        fields = ["id", "source", "data", "has_changed", "created_at"]
        read_only_fields = ["id", "source", "has_changed", "created_at"]


class ScrapedResultInlineSerializer(serializers.ModelSerializer):
    """
    Lightweight result serializer embedded inside a source detail response.
    Omits 'source' — already implied by context.
    """

    class Meta:
        model = ScrapedResult
        fields = ["id", "data", "has_changed", "created_at"]
        read_only_fields = ["id", "data", "has_changed", "created_at"]


class ScrapingSourceListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for GET /api/sources/ (list view).

    Excludes 'rules' and result history to avoid large payloads.
    result_count comes from annotate() in the view — no N+1 queries.
    """

    result_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ScrapingSource
        fields = [
            "id",
            "name",
            "url",
            "extraction_type",
            "frequency_minutes",
            "is_active",
            "last_error",
            "last_scraped_at",
            "result_count",
        ]
        read_only_fields = ["id", "last_error", "last_scraped_at", "result_count"]


class ScrapingSourceSerializer(serializers.ModelSerializer):
    """
    Full serializer for source detail/create/update endpoints.

    Includes 'rules' and the 10 most recent results.
    recent_results is capped to avoid unbounded response sizes.
    """

    recent_results = serializers.SerializerMethodField()

    class Meta:
        model = ScrapingSource
        fields = [
            "id",
            "name",
            "url",
            "rules",
            "extraction_type",
            "frequency_minutes",
            "is_active",
            "last_error",
            "last_scraped_at",
            "recent_results",
        ]
        read_only_fields = ["id", "last_error", "last_scraped_at", "recent_results"]

    def get_recent_results(self, obj: ScrapingSource) -> list[dict[str, Any]]:
        """Return the 10 latest results. Full history via /api/results/?source=<id>."""
        results = obj.results.order_by("-created_at")[:10]
        return ScrapedResultInlineSerializer(results, many=True).data

    def validate_rules(self, value: dict) -> dict:
        """
        Validate extraction rules against a JSON Schema on every POST/PUT/PATCH.

        Allowed per-rule keys:
          selector   — CSS selector (required)
          type       — 'single' | 'list' | 'nested'
          attribute  — e.g. 'href', 'src' (default: 'text')
          format     — 'decimal' | 'int' | 'bool' | 'strip' | 'uppercase' | 'lowercase'
          fields     — nested field map (required when type='nested')
          path       — dotted JSON path for extraction_type='json'
        """
        if not value:
            raise serializers.ValidationError(
                "Scraping rules must be a valid, non-empty JSON object."
            )

        rule_schema: dict = {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "minLength": 1},
                "type": {"enum": ["single", "list", "nested"]},
                "attribute": {"type": "string", "minLength": 1},
                "format": {
                    "enum": [
                        "decimal",
                        "int",
                        "bool",
                        "strip",
                        "uppercase",
                        "lowercase",
                    ]
                },
                "fields": {"type": "object"},
                "path": {"type": "string", "minLength": 1},
            },
            "required": ["selector"],
            "additionalProperties": False,
        }

        master_schema: dict = {
            "type": "object",
            "properties": {
                # Optional multi-page pagination config
                "pagination": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "minLength": 1},
                        "max_pages": {"type": "integer", "minimum": 1, "maximum": 500},
                        "delay_between_pages": {"type": "number", "minimum": 0},
                    },
                    "required": ["selector"],
                    "additionalProperties": False,
                }
            },
            "patternProperties": {
                "^(?!pagination$).*": rule_schema  # all keys except 'pagination'
            },
            "minProperties": 1,
            "additionalProperties": False,
        }

        try:
            validate(instance=value, schema=master_schema)
            for key, config in value.items():
                if key != "pagination" and config.get("type") == "nested":
                    if not config.get("fields"):
                        raise serializers.ValidationError(
                            f"Field '{key}' is type 'nested' "
                            "but missing 'fields' object."
                        )
        except JsonSchemaError as e:
            # Format path for readability: root -> field -> subfield
            path: str = " -> ".join([str(p) for p in e.path]) if e.path else "root"
            raise serializers.ValidationError(
                f"Invalid JSON structure ({path}): {e.message}"
            )

        return value
