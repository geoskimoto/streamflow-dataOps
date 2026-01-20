"""API URL Configuration."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from apps.api.views import (
    StationViewSet,
    PullConfigurationViewSet,
    DischargeObservationViewSet,
    DataPullLogViewSet,
)

# Create router and register viewsets
router = DefaultRouter()
router.register(r'stations', StationViewSet, basename='station')
router.register(r'configurations', PullConfigurationViewSet, basename='configuration')
router.register(r'observations/discharge', DischargeObservationViewSet, basename='discharge')
router.register(r'logs', DataPullLogViewSet, basename='log')

app_name = 'api'

urlpatterns = [
    # API documentation
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api:schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api:schema'), name='redoc'),
    
    # API endpoints
    path('', include(router.urls)),
]
