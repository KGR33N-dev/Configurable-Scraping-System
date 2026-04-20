from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ScrapingSourceViewSet, ScrapedResultViewSet

router = DefaultRouter()
router.register(r'sources', ScrapingSourceViewSet, basename='scrapingsource')
router.register(r'results', ScrapedResultViewSet, basename='scrapedresult')

urlpatterns = [
    path('', include(router.urls)),
]
