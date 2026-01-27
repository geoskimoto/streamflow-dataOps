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
    ForecastRunViewSet,
    DataPullLogViewSet,
)
from apps.api.views.raster_views import (
    RasterDatasetViewSet,
    RasterVariableViewSet,
    SpatialExtentViewSet,
    RasterLayerViewSet,
    RasterPullConfigurationViewSet,
    RasterPullLogViewSet,
)

# Create router and register viewsets
router = DefaultRouter()
router.register(r'stations', StationViewSet, basename='station')
router.register(r'configurations', PullConfigurationViewSet, basename='configuration')
router.register(r'observations/discharge', DischargeObservationViewSet, basename='discharge')
router.register(r'forecasts', ForecastRunViewSet, basename='forecast')
router.register(r'logs', DataPullLogViewSet, basename='log')

# Register raster viewsets
router.register(r'raster-datasets', RasterDatasetViewSet, basename='raster-dataset')
router.register(r'raster-variables', RasterVariableViewSet, basename='raster-variable')
router.register(r'spatial-extents', SpatialExtentViewSet, basename='spatial-extent')
router.register(r'raster-layers', RasterLayerViewSet, basename='raster-layer')
router.register(r'raster-configurations', RasterPullConfigurationViewSet, basename='raster-configuration')
router.register(r'raster-logs', RasterPullLogViewSet, basename='raster-log')

app_name = 'api'

urlpatterns = [
    # API documentation
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api:schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api:schema'), name='redoc'),
    
    # API endpoints
    path('', include(router.urls)),
]
