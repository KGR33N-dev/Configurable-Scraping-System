"""
Unit tests for the scraping engine (WebsiteScraper).
Verifies HTML parsing edge cases without HTTP requests.
"""
import pytest
from bs4 import BeautifulSoup
from scraper.scraper import WebsiteScraper

def test_extract_field_missing_element():
    scraper = WebsiteScraper()
    soup = BeautifulSoup("<html><body><h1>Title</h1></body></html>", "html.parser")
    
    # Element .price does not exist
    rule = {"selector": ".price", "type": "single"}
    result = scraper._extract_field(soup, rule)
    
    assert result is None

def test_extract_field_missing_attribute():
    scraper = WebsiteScraper()
    soup = BeautifulSoup("<html><body><img src='test.jpg'></body></html>", "html.parser")
    
    # Attribute 'alt' is missing on the img tag
    rule = {"selector": "img", "attribute": "alt"}
    result = scraper._extract_field(soup, rule)
    
    assert result is None

def test_extract_field_nested_partial_missing():
    scraper = WebsiteScraper()
    html = """
    <div class="item">
        <span class="name">Item 1</span>
        <!-- price missing -->
    </div>
    <div class="item">
        <span class="name">Item 2</span>
        <span class="price">10</span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    rule = {
        "selector": ".item",
        "type": "nested",
        "fields": {
            "name": {"selector": ".name"},
            "price": {"selector": ".price"}
        }
    }
    result = scraper._extract_field(soup, rule)
    
    assert len(result) == 2
    assert result[0]["name"] == "Item 1"
    assert result[0]["price"] is None
    assert result[1]["price"] == "10"
