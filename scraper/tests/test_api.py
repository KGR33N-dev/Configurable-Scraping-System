"""
Integration tests for the REST API.
Verifies the full HTTP -> DB flow, including views, serializers, models, and celery mocks.
"""
import pytest
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from rest_framework import status

from scraper.models import ScrapingSource, ScrapedResult


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def api_client():
    """Unauthenticated API client."""
    return APIClient()


@pytest.fixture
def auth_client(db):
    """Authenticated API client with a valid token."""
    user = User.objects.create_user(username="testuser", password="testpass123")
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


@pytest.fixture
def sample_source(db):
    """Sample ScrapingSource instance."""
    return ScrapingSource.objects.create(
        name="Test Source",
        url="https://example.com",
        rules={"title": {"selector": "h1", "type": "single"}},
        frequency_minutes=60,
        is_active=True,
    )


@pytest.fixture
def sample_result(db, sample_source):
    """Sample ScrapedResult linked to sample_source."""
    return ScrapedResult.objects.create(
        source=sample_source,
        data={"title": "Hello World"},
    )


# =============================================================================
# Source List Tests
# =============================================================================


@pytest.mark.django_db
class TestScrapingSourceList:
    def test_list_sources_unauthenticated(self, api_client, sample_source):
        """GET /api/sources/ is public."""
        response = api_client.get("/api/sources/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

    def test_list_sources_contains_result_count(
        self, api_client, sample_source, sample_result
    ):
        """List returns 'result_count' and excludes 'rules'."""
        response = api_client.get("/api/sources/")
        source_data = response.data["results"][0]
        assert "result_count" in source_data
        assert source_data["result_count"] == 1
        assert "rules" not in source_data

    def test_create_source_requires_auth(self, api_client):
        """POST /api/sources/ without token -> 401."""
        payload = {
            "name": "New Source",
            "url": "https://example.com",
            "rules": {"title": {"selector": "h1"}},
            "frequency_minutes": 30,
        }
        response = api_client.post("/api/sources/", payload, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_source_authenticated(self, auth_client):
        """POST /api/sources/ with token -> 201."""
        payload = {
            "name": "New Source",
            "url": "https://example.com",
            "rules": {"title": {"selector": "h1"}},
            "frequency_minutes": 30,
        }
        response = auth_client.post("/api/sources/", payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert ScrapingSource.objects.count() == 1
        assert response.data["name"] == "New Source"

    def test_create_source_invalid_rules_rejected(self, auth_client):
        """Invalid rules missing 'selector' -> 400."""
        payload = {
            "name": "Bad Source",
            "url": "https://example.com",
            "rules": {"title": {"type": "single"}},  # brak 'selector' — wymagany!
            "frequency_minutes": 30,
        }
        response = auth_client.post("/api/sources/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "rules" in response.data


# =============================================================================
# Source Detail Tests
# =============================================================================


@pytest.mark.django_db
class TestScrapingSourceDetail:
    def test_retrieve_source_includes_recent_results(
        self, api_client, sample_source, sample_result
    ):
        """GET /api/sources/{id}/ includes 'recent_results'."""
        response = api_client.get(f"/api/sources/{sample_source.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert "recent_results" in response.data
        assert len(response.data["recent_results"]) == 1
        assert response.data["recent_results"][0]["data"] == {"title": "Hello World"}

    def test_retrieve_source_recent_results_capped_at_10(
        self, api_client, sample_source
    ):
        """'recent_results' is capped at 10 results max."""
        for i in range(20):
            ScrapedResult.objects.create(source=sample_source, data={"i": i})
        response = api_client.get(f"/api/sources/{sample_source.id}/")
        assert len(response.data["recent_results"]) == 10

    def test_partial_update_requires_auth(self, api_client, sample_source):
        """PATCH without token -> 401."""
        response = api_client.patch(
            f"/api/sources/{sample_source.id}/",
            {"is_active": False},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_partial_update_authenticated(self, auth_client, sample_source):
        """PATCH with token updates the source."""
        response = auth_client.patch(
            f"/api/sources/{sample_source.id}/",
            {"is_active": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        sample_source.refresh_from_db()
        assert sample_source.is_active is False

    def test_delete_source_requires_auth(self, api_client, sample_source):
        """DELETE without token -> 401."""
        response = api_client.delete(f"/api/sources/{sample_source.id}/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_source_authenticated(self, auth_client, sample_source):
        """DELETE with token removes the source."""
        response = auth_client.delete(f"/api/sources/{sample_source.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert ScrapingSource.objects.count() == 0


# =============================================================================
# Manual Scraping Tests
# =============================================================================


@pytest.mark.django_db
class TestRunNow:
    def test_run_now_requires_auth(self, api_client, sample_source):
        """run_now without token -> 401."""
        response = api_client.post(f"/api/sources/{sample_source.id}/run_now/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_run_now_returns_202(self, auth_client, sample_source, mocker):
        """POST run_now enqueues task and returns 202."""
        mock_delay = mocker.patch("scraper.tasks.perform_scraping_task.delay")
        response = auth_client.post(f"/api/sources/{sample_source.id}/run_now/")
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_delay.assert_called_once_with(sample_source.id)

    def test_bulk_run_now_returns_202(self, auth_client, sample_source, mocker):
        """bulk_run_now enqueues tasks for all active sources."""
        mock_delay = mocker.patch("scraper.tasks.perform_scraping_task.delay")
        response = auth_client.post("/api/sources/bulk_run_now/")
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert mock_delay.call_count == 1  # Jedno aktywne źródło = jeden task


# =============================================================================
# Result History Tests
# =============================================================================


@pytest.mark.django_db
class TestScrapedResultHistory:
    def test_list_results_publicly_readable(self, api_client, sample_result):
        """GET /api/results/ is public."""
        response = api_client.get("/api/results/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

    def test_filter_results_by_source(self, api_client, db):
        """?source=<id> returns results for a specific source."""
        source_a = ScrapingSource.objects.create(
            name="A",
            url="https://a.com",
            rules={"t": {"selector": "h1"}},
            frequency_minutes=60,
        )
        source_b = ScrapingSource.objects.create(
            name="B",
            url="https://b.com",
            rules={"t": {"selector": "h1"}},
            frequency_minutes=60,
        )
        ScrapedResult.objects.create(source=source_a, data={"x": 1})
        ScrapedResult.objects.create(source=source_b, data={"x": 2})

        response = api_client.get(f"/api/results/?source={source_a.id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["data"] == {"x": 1}

    def test_filter_results_by_missing_field(self, api_client, sample_source):
        """?missing_field=<field> filters correctly with JSONB nulls."""
        ScrapedResult.objects.create(
            source=sample_source, data={"title": "A", "price": None}
        )
        ScrapedResult.objects.create(
            source=sample_source, data={"title": "B", "price": 9.99}
        )

        response = api_client.get("/api/results/?missing_field=price")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["data"]["title"] == "A"

    def test_results_ordered_newest_first(self, api_client, sample_source):
        """Results are ordered newest first."""
        r1 = ScrapedResult.objects.create(source=sample_source, data={"order": 1})
        r2 = ScrapedResult.objects.create(source=sample_source, data={"order": 2})
        response = api_client.get("/api/results/")
        ids = [r["id"] for r in response.data["results"]]
        assert ids[0] == r2.id  # r2 jest nowszy
        assert ids[1] == r1.id


# =============================================================================
# Token Auth Tests
# =============================================================================


@pytest.mark.django_db
class TestTokenAuthentication:
    def test_obtain_token(self, api_client, db):
        """Valid credentials return a token."""
        User.objects.create_user(username="u", password="p")
        response = api_client.post(
            "/api/auth/token/",
            {"username": "u", "password": "p"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert "token" in response.data

    def test_wrong_credentials_rejected(self, api_client, db):
        """Invalid credentials return 400."""
        User.objects.create_user(username="u", password="p")
        response = api_client.post(
            "/api/auth/token/",
            {"username": "u", "password": "wrong"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
