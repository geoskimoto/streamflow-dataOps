"""URL configuration for the analytics section."""

from django.urls import path
from apps.analytics import views

app_name = 'analytics'

urlpatterns = [
    path('', views.analytics_dashboard, name='dashboard'),
    path('configurations/', views.StatisticsConfigurationListView.as_view(), name='configuration_list'),
    path('configurations/new/', views.StatisticsConfigurationCreateView.as_view(), name='configuration_create'),
    path('configurations/<int:pk>/', views.StatisticsConfigurationDetailView.as_view(), name='configuration_detail'),
    path('configurations/<int:pk>/edit/', views.StatisticsConfigurationUpdateView.as_view(), name='configuration_update'),
    path('configurations/<int:pk>/delete/', views.StatisticsConfigurationDeleteView.as_view(), name='configuration_delete'),
    path('configurations/<int:pk>/trigger/', views.trigger_statistics_config, name='trigger'),
    path('configurations/<int:pk>/toggle/', views.toggle_statistics_config, name='toggle'),
    path('station-metadata/', views.station_metadata_list, name='station_metadata_list'),
]
