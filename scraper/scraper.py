import httpx
import json
import random
import logging
import time
import re
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

logger = logging.getLogger(__name__)


class WebsiteScraper:
    """
    Stateless scraping engine — safe for concurrent Celery workers.

    Dispatches to _scrape_html() or _scrape_json() based on extraction_type.
    """

    # Rotated on each request to reduce bot-detection risk
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    ]

    def scrape(self, url: str, rules: dict, extraction_type: str = "html") -> dict:
        """
        Main entry point.

        Args:
            url: target URL
            rules: validated extraction rules dict
            extraction_type: 'html' (CSS selectors) or 'json' (dotted-path)

        Returns:
            Dict of {field_name: value} ready to store in ScrapedResult.data
        """
        headers = {"User-Agent": random.choice(self.USER_AGENTS)}
        if extraction_type == "json":
            return self._scrape_json(url=url, rules=rules, headers=headers)
        return self._scrape_html(url=url, rules=rules, headers=headers)

    # =========================================================================
    # JSON scraping
    # =========================================================================

    def _scrape_json(self, url: str, rules: dict, headers: dict[str, str]) -> dict:
        """
        Fetch a JSON REST API and extract fields via dotted-path rules.

        Rule format:
            {"price": {"path": "data.product.price", "type": "single"}}

        Raises:
            httpx.RequestError: network error (triggers Celery retry)
            ValueError: response is not valid JSON
        """
        with httpx.Client(
            timeout=15.0, follow_redirects=True, headers=headers
        ) as client:
            try:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
            except httpx.RequestError as e:
                logger.error(f"Network error fetching JSON from {url}: {e}")
                raise
            except json.JSONDecodeError as e:
                logger.error(f"Response from {url} is not valid JSON: {e}")
                raise ValueError(f"Non-JSON response from {url}") from e

        result_data: dict[str, Any] = {}
        for field_name, rule_config in rules.items():
            if not isinstance(rule_config, dict):
                continue
            path = rule_config.get("path")
            extract_type = rule_config.get("type", "single")

            if not path:
                result_data[field_name] = None
                continue

            value = self._resolve_json_path(payload, path)

            if extract_type == "list" and not isinstance(value, list):
                value = [value] if value is not None else []

            result_data[field_name] = value

        return result_data

    def _resolve_json_path(self, data: Any, path: str) -> Any:
        """
        Traverse a nested dict/list using dot notation.

        'items.0.name' → data['items'][0]['name']

        Returns None if any segment is missing or invalid.
        """
        current = data
        for part in path.split("."):
            if current is None:
                return None
            if isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    # =========================================================================
    # HTML scraping
    # =========================================================================

    def _scrape_html(self, url: str, rules: dict, headers: dict[str, str]) -> dict:
        """
        Fetch and parse HTML pages with optional multi-page pagination.

        Pagination config ('pagination' key in rules):
          selector            — CSS selector for the "next page" link
          max_pages           — page cap (default: 1)
          delay_between_pages — politeness delay in seconds between requests

        List/nested results accumulate across pages; single values are taken
        from the first page only.
        """
        result_data: dict[str, Any] = {}
        current_url: Optional[str] = url
        pages_scraped = 0

        pagination_config = rules.get("pagination", {})
        next_selector: Optional[str] = pagination_config.get("selector")
        max_pages: int = pagination_config.get("max_pages", 1)
        delay: float = pagination_config.get("delay_between_pages", 0)

        with httpx.Client(
            timeout=15.0, follow_redirects=True, headers=headers
        ) as client:
            while current_url and pages_scraped < max_pages:
                if pages_scraped > 0 and delay > 0:
                    logger.info(f"Politeness delay: waiting {delay}s...")
                    time.sleep(delay)

                try:
                    logger.info(f"Fetching page {pages_scraped + 1}: {current_url}")
                    response = client.get(current_url)
                    response.raise_for_status()
                except httpx.RequestError as e:
                    logger.error(f"Network error on page {pages_scraped + 1}: {e}")
                    break  # Return whatever was collected so far

                soup = BeautifulSoup(response.text, "html.parser")

                for field_name, rule_config in rules.items():
                    if field_name == "pagination":
                        continue  # 'pagination' is config, not a data field

                    extracted = self._extract_field(soup, rule_config)

                    # Lists accumulate across pages; scalars are set once
                    if isinstance(extracted, list):
                        result_data.setdefault(field_name, [])
                        result_data[field_name].extend(extracted)
                    elif field_name not in result_data:
                        result_data[field_name] = extracted

                pages_scraped += 1

                if next_selector and pages_scraped < max_pages:
                    next_el = soup.select_one(next_selector)
                    if next_el and next_el.has_attr("href"):
                        # urljoin handles both absolute and relative links
                        current_url = urljoin(current_url, next_el["href"])
                    else:
                        current_url = None
                else:
                    current_url = None

        return result_data

    def _extract_field(self, soup: Tag, rule_config: dict) -> Any:
        """
        Extract a single field from a BeautifulSoup node.

        Types:
          'single' — first match → scalar value
          'list'   — all matches → list of values
          'nested' — containers, each recursively yielding a sub-dict

        'attribute' key (default 'text'):
          'text'  → element.get_text(strip=True)
          other   → element[attribute]  e.g. 'href', 'src'
        """
        if not isinstance(rule_config, dict):
            return None

        css_selector: Optional[str] = rule_config.get("selector")
        extract_type: str = rule_config.get("type", "single")
        attribute: str = rule_config.get("attribute", "text")
        format_type: Optional[str] = rule_config.get("format")

        if not css_selector:
            return None

        value: Any = None
        if extract_type == "single":
            element = soup.select_one(css_selector)
            if element:
                try:
                    value = (
                        element[attribute]
                        if attribute != "text"
                        else element.get_text(strip=True)
                    )
                except KeyError:
                    value = None  # Element exists but lacks the requested attribute

        elif extract_type == "list":
            elements = soup.select(css_selector)
            if attribute != "text":
                value = [el[attribute] for el in elements if el.has_attr(attribute)]
            else:
                value = [el.get_text(strip=True) for el in elements]

        elif extract_type == "nested":
            containers = soup.select(css_selector)
            nested_fields: dict = rule_config.get("fields", {})
            results: list[dict] = []
            for container in containers:
                item: dict[str, Any] = {}
                for f_name, f_config in nested_fields.items():
                    if isinstance(f_config, dict) and "type" not in f_config:
                        f_config["type"] = "single"
                    item[f_name] = self._extract_field(container, f_config)
                results.append(item)
            return results

        if extract_type != "nested":
            if isinstance(value, list):
                return [self._post_process(v, format_type) for v in value]
            return self._post_process(value, format_type)

        return value

    def _post_process(self, value: Any, format_type: Optional[str]) -> Any:
        """
        Clean and convert raw scraped text values.

        Supported formats:
          'decimal'   — price string → float:  "$1,234.56" → 1234.56
          'int'       — string → int:           "  42  "   → 42
          'bool'      — yes/no/true/false/1/0  → bool
          'strip'     — collapse whitespace:    "foo  bar"  → "foo bar"
          'uppercase' — uppercase the string
          'lowercase' — lowercase the string

        Returns the original value on conversion failure.
        """
        if value is None or not format_type:
            return value

        if format_type == "decimal":
            if not isinstance(value, str):
                return value
            clean_val = re.sub(r"[^\d.,-]", "", value)
            clean_val = clean_val.replace(",", ".")
            try:
                return float(Decimal(clean_val))
            except (InvalidOperation, ValueError):
                return value

        if format_type == "int":
            try:
                return int(re.sub(r"[^\d-]", "", str(value)))
            except (ValueError, TypeError):
                return value

        if format_type == "bool":
            if isinstance(value, bool):
                return value
            normalized = str(value).strip().lower()
            if normalized in ("true", "yes", "1", "on"):
                return True
            if normalized in ("false", "no", "0", "off"):
                return False
            return value  # Unrecognised — keep original

        if format_type == "strip":
            if isinstance(value, str):
                return re.sub(r"\s+", " ", value).strip()
            return value

        if format_type == "uppercase":
            return str(value).upper() if isinstance(value, str) else value

        if format_type == "lowercase":
            return str(value).lower() if isinstance(value, str) else value

        logger.warning(f"Unknown format_type '{format_type}' — value returned as-is.")
        return value
