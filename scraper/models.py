from typing import Optional
from django.db import models
from django.core.validators import MinValueValidator


class ScrapingSource(models.Model):
    """Configuration for a single scraping target."""

    name: str = models.CharField(max_length=255)

    # db_index speeds up ?url= filtering
    url: str = models.URLField(max_length=2000, db_index=True)

    # Extraction rules validated by ScrapingSourceSerializer
    rules: dict = models.JSONField(default=dict)

    extraction_type: str = models.CharField(
        max_length=20,
        choices=[('html', 'HTML'), ('json', 'JSON')],
        default='html',
    )

    frequency_minutes: int = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1)],
        help_text="How often (in minutes) this source should be scraped.",
    )

    # Inactive sources are skipped by the heartbeat task
    is_active: bool = models.BooleanField(default=True)

    last_error: Optional[str] = models.TextField(null=True, blank=True)

    # Used by heartbeat: next_scrape = last_scraped_at + frequency_minutes
    last_scraped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return f"{self.name} ({self.url})"


class ScrapedResult(models.Model):
    """
    Immutable record of data collected from a source at a point in time.

    Treated as an append-only audit log — never modified after creation.
    """

    # CASCADE: deleting a source removes all its results
    source = models.ForeignKey(
        ScrapingSource,
        on_delete=models.CASCADE,
        related_name='results',
    )

    data: dict = models.JSONField()

    # True  — data differs from the previous scrape (or first run)
    # False — data identical to previous scrape
    # None  — unknown (records predating this field)
    has_changed: Optional[bool] = models.BooleanField(
        null=True,
        blank=True,
        db_index=True,  # Speeds up ?changed_only=true filter
        help_text="True if scraped data differs from the previous result for this source.",
    )

    # Set once on creation, never updated
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Result for '{self.source.name}' at {self.created_at:%Y-%m-%d %H:%M}"
