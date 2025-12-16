"""URL configuration for streamflow app."""

from django.urls import path
from . import views

app_name = 'streamflow'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Pull Configurations
    path('configurations/', views.PullConfigurationListView.as_view(), name='configuration_list'),
    path('configurations/new/', views.PullConfigurationCreateView.as_view(), name='configuration_create'),
    path('configurations/<int:pk>/', views.PullConfigurationDetailView.as_view(), name='configuration_detail'),
    path('configurations/<int:pk>/edit/', views.PullConfigurationUpdateView.as_view(), name='configuration_update'),
    path('configurations/<int:pk>/delete/', views.PullConfigurationDeleteView.as_view(), name='configuration_delete'),
    path('configurations/<int:pk>/trigger/', views.trigger_pull, name='trigger_pull'),
    path('configurations/<int:pk>/toggle/', views.toggle_configuration, name='toggle_configuration'),
    
    # Stations
    path('stations/search/', views.station_search, name='station_search'),
    path('configurations/<int:pk>/stations/add/', views.add_station_to_config, name='add_station'),
    path('configurations/<int:pk>/stations/<int:station_id>/remove/', views.remove_station_from_config, name='remove_station'),
    
    # Logs
    path('logs/', views.DataPullLogListView.as_view(), name='log_list'),
]
