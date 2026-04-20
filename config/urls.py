from django.contrib import admin
from django.urls import path, include

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [
    path("admin/", admin.site.urls),
    # POST {username, password} → returns {token: "..."}
    path("api/auth/token/", obtain_auth_token, name="api-token-auth"),
    path("api/", include("scraper.urls")),
    # Raw OpenAPI 3.0 schema (JSON/YAML)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # Interactive Swagger UI
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
