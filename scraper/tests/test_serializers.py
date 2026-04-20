"""
Unit tests for the ScrapingSourceSerializer extraction rules validation.
"""
import pytest
from rest_framework import serializers
from scraper.serializers import ScrapingSourceSerializer

def test_validate_rules_valid_flat():
    serializer = ScrapingSourceSerializer()
    rules = {
        "title": {"selector": "h1"},
        "price": {"selector": ".price", "type": "single", "attribute": "text"}
    }
    # Should not raise any error
    assert serializer.validate_rules(rules) == rules

def test_validate_rules_valid_nested():
    serializer = ScrapingSourceSerializer()
    rules = {
        "books": {
            "selector": ".product",
            "type": "nested",
            "fields": {
                "name": {"selector": "h2"}
            }
        }
    }
    assert serializer.validate_rules(rules) == rules

def test_validate_rules_valid_pagination():
    serializer = ScrapingSourceSerializer()
    rules = {
        "pagination": {"selector": ".next", "max_pages": 5},
        "items": {"selector": "li"}
    }
    assert serializer.validate_rules(rules) == rules

def test_validate_rules_missing_selector():
    serializer = ScrapingSourceSerializer()
    rules = {
        "title": {"type": "single"} # missing selector
    }
    with pytest.raises(serializers.ValidationError) as excinfo:
        serializer.validate_rules(rules)
    assert "selector" in str(excinfo.value)

def test_validate_rules_invalid_type():
    serializer = ScrapingSourceSerializer()
    rules = {
        "title": {"selector": "h1", "type": "wrong_type"}
    }
    with pytest.raises(serializers.ValidationError) as excinfo:
        serializer.validate_rules(rules)
    assert "wrong_type" in str(excinfo.value)

def test_validate_rules_nested_missing_fields():
    serializer = ScrapingSourceSerializer()
    rules = {
        "books": {
            "selector": ".product",
            "type": "nested"
            # missing fields
        }
    }
    with pytest.raises(serializers.ValidationError) as excinfo:
        serializer.validate_rules(rules)
    assert "missing 'fields'" in str(excinfo.value)

def test_validate_rules_empty():
    serializer = ScrapingSourceSerializer()
    with pytest.raises(serializers.ValidationError):
        serializer.validate_rules({})
