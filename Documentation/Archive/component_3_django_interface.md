# Component 3: Data Pull Scheduling and Configuration Interface

## Overview
Build a full-stack Django web application for managing data pull configurations, station selection, and job scheduling. Integrate with Celery Beat for dynamic task scheduling and implement the Smart Append Logic workflow through a user-friendly interface.

---

## Technical Stack
- **Web Framework**: Django 4.2+
- **Task Queue**: Celery with Celery Beat
- **Message Broker**: Redis or RabbitMQ
- **Database**: PostgreSQL (production) / SQLite (development)
- **ORM**: SQLAlchemy (integrated with Django)
- **Frontend**: Django Templates + Bootstrap 5 (or Django + HTMX for modern UX)

---

## Implementation Plan

### Phase 1: Django Project Setup

#### 1.1 Project Structure
```
streamflow_dataops/
├── manage.py
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   ├── __init__.py
│   ├── stations/              # Station management app
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── forms.py
│   │   ├── templates/
│   │   │   └── stations/
│   │   └── static/
│   │       └── stations/
│   ├── pulls/                 # Data pull configuration app
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── models.py          # Django models wrapping SQLAlchemy
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── forms.py
│   │   ├── services.py        # Business logic
│   │   ├── celery_manager.py  # Celery Beat integration
│   │   ├── templates/
│   │   │   └── pulls/
│   │   └── static/
│   │       └── pulls/
│   ├── monitoring/            # Job monitoring and logs
│   │   ├── __init__.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── templates/
│   │   └── static/
│   └── api/                   # Optional REST API
│       ├── __init__.py
│       ├── serializers.py
│       ├── views.py
│       └── urls.py
├── templates/
│   ├── base.html
│   ├── navbar.html
│   └── home.html
├── static/
│   ├── css/
│   ├── js/
│   └── images/
├── media/
├── requirements.txt
└── README.md
```

#### 1.2 Install Django Dependencies
Update `requirements.txt`:
```
# Django Core
Django==4.2.7
django-environ==0.11.2
django-crispy-forms==2.1
crispy-bootstrap5==1.0.2

# Celery Integration
celery==5.3.4
django-celery-beat==2.5.0
django-celery-results==2.5.1

# Database
psycopg2-binary==2.9.9
sqlalchemy==2.0.23

# Forms and UI
django-widget-tweaks==1.5.0
django-tables2==2.6.0
django-filter==23.3

# API (optional)
djangorestframework==3.14.0

# Others
python-dateutil==2.8.2
pytz==2023.3
```

#### 1.3 Initialize Django Project
```bash
django-admin startproject config .
python manage.py startapp stations apps/stations
python manage.py startapp pulls apps/pulls
python manage.py startapp monitoring apps/monitoring
```

#### 1.4 Configure Django Settings (`config/settings.py`)
```python
import os
from pathlib import Path
import environ

# Initialize environment variables
env = environ.Env(
    DEBUG=(bool, False)
)

BASE_DIR = Path(__file__).resolve().parent.parent

# Read .env file
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = env('SECRET_KEY', default='your-secret-key-here')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party apps
    'crispy_forms',
    'crispy_bootstrap5',
    'django_celery_beat',
    'django_celery_results',
    'django_tables2',
    'django_filters',
    'rest_framework',
    
    # Local apps
    'apps.stations',
    'apps.pulls',
    'apps.monitoring',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database - Using SQLAlchemy models but Django for admin
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DB_NAME', default='streamflow_db'),
        'USER': env('DB_USER', default='postgres'),
        'PASSWORD': env('DB_PASSWORD', default=''),
        'HOST': env('DB_HOST', default='localhost'),
        'PORT': env('DB_PORT', default='5432'),
    }
}

# Celery Configuration
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_CACHE_BACKEND = 'django-cache'
CELERY_TIMEZONE = 'UTC'
CELERY_ENABLE_UTC = True
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Crispy Forms
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Django REST Framework (optional)
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50
}

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': 'django.log',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
}
```

---

### Phase 2: SQLAlchemy Integration with Django

#### 2.1 Create Django Model Wrappers
Since we're using SQLAlchemy for the ORM, we need to integrate it with Django. We have two options:

**Option A: Use Aldjemy** (Automatic Django-SQLAlchemy bridge)
```bash
pip install aldjemy
```

**Option B: Manual Integration** (More control)
Create proxy models that interface with SQLAlchemy:

`apps/pulls/sqlalchemy_models.py`:
```python
"""
Bridge between Django views and SQLAlchemy models
"""
from src.database.connection import SessionLocal
from src.database.models import (
    PullConfiguration,
    PullConfigurationStation,
    MasterStation,
    DataPullLog,
    PullStationProgress
)
from src.database.repositories import (
    PullConfigurationRepository,
    MasterStationRepository,
    DataPullLogRepository,
    PullProgressRepository
)

class SQLAlchemyManager:
    """Context manager for SQLAlchemy sessions in Django views"""
    
    def __enter__(self):
        self.session = SessionLocal()
        return self.session
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.session.rollback()
        self.session.close()

def get_sa_session():
    """Get SQLAlchemy session for use in Django views"""
    return SessionLocal()
```

#### 2.2 Create Django Models for Celery Beat
Even though we use SQLAlchemy for data, we need Django models for Celery Beat:

`apps/pulls/models.py`:
```python
from django.db import models
from django_celery_beat.models import PeriodicTask, CrontabSchedule
import json

class PullConfigurationProxy(models.Model):
    """
    Django model that mirrors SQLAlchemy PullConfiguration
    Used primarily for admin interface and Celery Beat integration
    """
    # This is a proxy/bridge model - actual data is in SQLAlchemy tables
    
    class Meta:
        managed = False  # Don't let Django manage this table
        db_table = 'pull_configurations'
    
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    data_type = models.CharField(max_length=20)
    is_enabled = models.BooleanField(default=True)
    schedule_type = models.CharField(max_length=20)
    schedule_value = models.CharField(max_length=50, blank=True, null=True)
    last_run_at = models.DateTimeField(blank=True, null=True)
    next_run_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### Phase 3: Station Selection Interface

#### 3.1 Station Search and Filter View (`apps/stations/views.py`)
```python
from django.shortcuts import render
from django.views.generic import ListView, DetailView
from django.contrib import messages
from django.db.models import Q
import django_filters
from apps.pulls.sqlalchemy_models import get_sa_session, MasterStation
from src.database.repositories import MasterStationRepository

class MasterStationFilter(django_filters.FilterSet):
    """Filter for station search"""
    state_code = django_filters.CharFilter(
        field_name='state_code',
        lookup_expr='iexact',
        label='State Code'
    )
    huc_prefix = django_filters.CharFilter(
        method='filter_by_huc_prefix',
        label='HUC Code (2-digit)'
    )
    search = django_filters.CharFilter(
        method='filter_by_search',
        label='Search Station Name or ID'
    )
    
    def filter_by_huc_prefix(self, queryset, name, value):
        # Custom filter method
        if value:
            # This will be handled in the view with SQLAlchemy
            return queryset
        return queryset
    
    def filter_by_search(self, queryset, name, value):
        # Custom filter method
        if value:
            # This will be handled in the view with SQLAlchemy
            return queryset
        return queryset

class StationSearchView(ListView):
    """
    Station search and selection view
    Provides filtering by State, HUC, and search term
    """
    template_name = 'stations/station_search.html'
    context_object_name = 'stations'
    paginate_by = 50
    
    def get_queryset(self):
        """Get filtered station list from SQLAlchemy"""
        with get_sa_session() as session:
            repo = MasterStationRepository(session)
            
            # Get filter parameters
            state_code = self.request.GET.get('state_code', None)
            huc_prefix = self.request.GET.get('huc_prefix', None)
            search_term = self.request.GET.get('search', None)
            
            # Query using repository
            stations = repo.search_stations(
                state_code=state_code,
                huc_code_prefix=huc_prefix,
                search_term=search_term,
                limit=500
            )
            
            return stations
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = self.get_filter_form()
        return context
    
    def get_filter_form(self):
        """Get filter form for template"""
        return {
            'state_code': self.request.GET.get('state_code', ''),
            'huc_prefix': self.request.GET.get('huc_prefix', ''),
            'search': self.request.GET.get('search', '')
        }

class StationDetailView(DetailView):
    """Detailed view of a single station"""
    template_name = 'stations/station_detail.html'
    context_object_name = 'station'
    
    def get_object(self):
        station_number = self.kwargs.get('station_number')
        with get_sa_session() as session:
            repo = MasterStationRepository(session)
            return repo.get_by_station_number(station_number)
```

#### 3.2 Station Search Template (`apps/stations/templates/stations/station_search.html`)
```html
{% extends "base.html" %}
{% load crispy_forms_tags %}

{% block title %}Station Search{% endblock %}

{% block content %}
<div class="container mt-4">
    <h2>Master Station Search</h2>
    
    <!-- Search and Filter Form -->
    <div class="card mb-4">
        <div class="card-body">
            <form method="get" action="{% url 'stations:search' %}">
                <div class="row">
                    <div class="col-md-3">
                        <label for="state_code">State Code</label>
                        <input type="text" 
                               class="form-control" 
                               id="state_code" 
                               name="state_code" 
                               placeholder="e.g., MD"
                               value="{{ filter_form.state_code }}">
                    </div>
                    <div class="col-md-3">
                        <label for="huc_prefix">HUC Code (2-digit)</label>
                        <input type="text" 
                               class="form-control" 
                               id="huc_prefix" 
                               name="huc_prefix" 
                               placeholder="e.g., 02"
                               value="{{ filter_form.huc_prefix }}">
                    </div>
                    <div class="col-md-4">
                        <label for="search">Search Station Name or ID</label>
                        <input type="text" 
                               class="form-control" 
                               id="search" 
                               name="search" 
                               placeholder="Search..."
                               value="{{ filter_form.search }}">
                    </div>
                    <div class="col-md-2 d-flex align-items-end">
                        <button type="submit" class="btn btn-primary w-100">Search</button>
                    </div>
                </div>
            </form>
        </div>
    </div>
    
    <!-- Results Table -->
    <div class="card">
        <div class="card-header">
            <h5>Search Results ({{ page_obj.paginator.count }} stations)</h5>
        </div>
        <div class="card-body">
            <div class="table-responsive">
                <table class="table table-striped table-hover">
                    <thead>
                        <tr>
                            <th>Station Number</th>
                            <th>Station Name</th>
                            <th>State</th>
                            <th>HUC Code</th>
                            <th>Drainage Area (sq mi)</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for station in stations %}
                        <tr>
                            <td>{{ station.station_number }}</td>
                            <td>{{ station.station_name }}</td>
                            <td>{{ station.state_code }}</td>
                            <td>{{ station.huc_code }}</td>
                            <td>{{ station.drainage_area_sqmi|floatformat:2 }}</td>
                            <td>
                                <a href="{% url 'stations:detail' station.station_number %}" 
                                   class="btn btn-sm btn-info">View</a>
                                <button class="btn btn-sm btn-success select-station" 
                                        data-station-number="{{ station.station_number }}"
                                        data-station-name="{{ station.station_name }}">
                                    Select
                                </button>
                            </td>
                        </tr>
                        {% empty %}
                        <tr>
                            <td colspan="6" class="text-center">No stations found</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            <!-- Pagination -->
            {% if is_paginated %}
            <nav aria-label="Page navigation">
                <ul class="pagination justify-content-center">
                    {% if page_obj.has_previous %}
                    <li class="page-item">
                        <a class="page-link" href="?page=1{{ request.GET.urlencode }}">First</a>
                    </li>
                    <li class="page-item">
                        <a class="page-link" href="?page={{ page_obj.previous_page_number }}{{ request.GET.urlencode }}">Previous</a>
                    </li>
                    {% endif %}
                    
                    <li class="page-item active">
                        <span class="page-link">
                            Page {{ page_obj.number }} of {{ page_obj.paginator.num_pages }}
                        </span>
                    </li>
                    
                    {% if page_obj.has_next %}
                    <li class="page-item">
                        <a class="page-link" href="?page={{ page_obj.next_page_number }}{{ request.GET.urlencode }}">Next</a>
                    </li>
                    <li class="page-item">
                        <a class="page-link" href="?page={{ page_obj.paginator.num_pages }}{{ request.GET.urlencode }}">Last</a>
                    </li>
                    {% endif %}
                </ul>
            </nav>
            {% endif %}
        </div>
    </div>
</div>

<script>
// Handle station selection
document.querySelectorAll('.select-station').forEach(button => {
    button.addEventListener('click', function() {
        const stationNumber = this.dataset.stationNumber;
        const stationName = this.dataset.stationName;
        
        // Store in sessionStorage for use in configuration form
        let selectedStations = JSON.parse(sessionStorage.getItem('selectedStations') || '[]');
        selectedStations.push({
            station_number: stationNumber,
            station_name: stationName
        });
        sessionStorage.setItem('selectedStations', JSON.stringify(selectedStations));
        
        // Show feedback
        this.textContent = 'Added!';
        this.classList.remove('btn-success');
        this.classList.add('btn-secondary');
        this.disabled = true;
    });
});
</script>
{% endblock %}
```

---


### Phase 4: Pull Configuration Management

#### 4.1 Configuration Form (`apps/pulls/forms.py`)
```python
from django import forms
from django.core.exceptions import ValidationError
from datetime import datetime
import json

class PullConfigurationForm(forms.Form):
    """Form for creating/editing pull configurations"""
    
    # Basic Information
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Daily USGS Discharge - Maryland'
        })
    )
    
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Optional description of this configuration'
        })
    )
    
    # Data Type Selection
    DATA_TYPE_CHOICES = [
        ('daily_mean', 'Daily Mean Discharge'),
        ('realtime_15min', 'Real-time (15-minute) Discharge'),
    ]
    
    data_type = forms.ChoiceField(
        choices=DATA_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    # Data Strategy
    STRATEGY_CHOICES = [
        ('append', 'Append (Smart Append Logic)'),
        ('overwrite', 'Overwrite Existing Data'),
    ]
    
    data_strategy = forms.ChoiceField(
        choices=STRATEGY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Append is recommended for continuous updates'
    )
    
    # Pull Start Date
    pull_start_date = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        }),
        help_text='Initial start date for first data pull (e.g., 1900-01-01 for historical data)'
    )
    
    # Schedule Configuration
    SCHEDULE_TYPE_CHOICES = [
        ('hourly', 'Every Hour'),
        ('every_6_hours', 'Every 6 Hours'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('custom_cron', 'Custom (Cron Expression)'),
    ]
    
    schedule_type = forms.ChoiceField(
        choices=SCHEDULE_TYPE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'schedule_type'
        })
    )
    
    schedule_value = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., 0 */6 * * * for every 6 hours',
            'id': 'schedule_value'
        }),
        help_text='Only needed for custom cron expressions'
    )
    
    # Enable/Disable
    is_enabled = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    # Selected Stations (JSON field)
    selected_stations = forms.CharField(
        widget=forms.HiddenInput(),
        help_text='JSON array of selected station objects'
    )
    
    def clean_selected_stations(self):
        """Validate and parse selected stations JSON"""
        data = self.cleaned_data['selected_stations']
        try:
            stations = json.loads(data)
            if not isinstance(stations, list) or len(stations) == 0:
                raise ValidationError('At least one station must be selected')
            return stations
        except json.JSONDecodeError:
            raise ValidationError('Invalid station data format')
    
    def clean_schedule_value(self):
        """Validate cron expression if custom schedule selected"""
        schedule_type = self.data.get('schedule_type')
        schedule_value = self.cleaned_data.get('schedule_value')
        
        if schedule_type == 'custom_cron' and not schedule_value:
            raise ValidationError('Cron expression required for custom schedule')
        
        return schedule_value
    
    def get_cron_expression(self):
        """Convert schedule type to cron expression"""
        schedule_type = self.cleaned_data.get('schedule_type')
        schedule_value = self.cleaned_data.get('schedule_value')
        
        cron_map = {
            'hourly': '0 * * * *',
            'every_6_hours': '0 */6 * * *',
            'daily': '0 0 * * *',
            'weekly': '0 0 * * 0',
        }
        
        if schedule_type == 'custom_cron':
            return schedule_value
        else:
            return cron_map.get(schedule_type, '0 0 * * *')


class StationSelectionForm(forms.Form):
    """Form for bulk station selection from search results"""
    
    station_numbers = forms.CharField(
        widget=forms.HiddenInput()
    )
    
    def clean_station_numbers(self):
        data = self.cleaned_data['station_numbers']
        try:
            station_list = json.loads(data)
            return station_list
        except json.JSONDecodeError:
            raise ValidationError('Invalid station data')
```

#### 4.2 Configuration Views (`apps/pulls/views.py`)
```python
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib import messages
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import json
from datetime import datetime

from apps.pulls.forms import PullConfigurationForm
from apps.pulls.sqlalchemy_models import get_sa_session
from apps.pulls.services import PullConfigurationService
from apps.pulls.celery_manager import CeleryBeatManager
from src.database.repositories import PullConfigurationRepository
from src.database.models import PullConfiguration

class PullConfigurationListView(ListView):
    """List all pull configurations"""
    template_name = 'pulls/configuration_list.html'
    context_object_name = 'configurations'
    paginate_by = 20
    
    def get_queryset(self):
        with get_sa_session() as session:
            repo = PullConfigurationRepository(session)
            return repo.get_all()

class PullConfigurationDetailView(DetailView):
    """Detailed view of a pull configuration"""
    template_name = 'pulls/configuration_detail.html'
    context_object_name = 'configuration'
    
    def get_object(self):
        config_id = self.kwargs.get('pk')
        with get_sa_session() as session:
            repo = PullConfigurationRepository(session)
            return repo.get_by_id(config_id)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get associated stations
        config_id = self.kwargs.get('pk')
        with get_sa_session() as session:
            repo = PullConfigurationRepository(session)
            context['stations'] = repo.get_configuration_stations(config_id)
            context['recent_logs'] = repo.get_recent_logs(config_id, limit=10)
        
        return context

class PullConfigurationCreateView(CreateView):
    """Create a new pull configuration"""
    template_name = 'pulls/configuration_form.html'
    form_class = PullConfigurationForm
    success_url = reverse_lazy('pulls:list')
    
    def form_valid(self, form):
        try:
            with get_sa_session() as session:
                service = PullConfigurationService(session)
                
                # Create configuration
                config_data = {
                    'name': form.cleaned_data['name'],
                    'description': form.cleaned_data.get('description', ''),
                    'data_type': form.cleaned_data['data_type'],
                    'data_strategy': form.cleaned_data['data_strategy'],
                    'pull_start_date': form.cleaned_data['pull_start_date'],
                    'schedule_type': form.cleaned_data['schedule_type'],
                    'schedule_value': form.get_cron_expression(),
                    'is_enabled': form.cleaned_data.get('is_enabled', True),
                }
                
                # Get selected stations
                selected_stations = form.cleaned_data['selected_stations']
                
                # Create configuration with stations
                config = service.create_configuration(config_data, selected_stations)
                
                # Create Celery Beat periodic task
                if config.is_enabled:
                    celery_manager = CeleryBeatManager()
                    celery_manager.create_or_update_task(config)
                
                messages.success(
                    self.request,
                    f'Configuration "{config.name}" created successfully!'
                )
                
                return redirect(self.success_url)
                
        except Exception as e:
            messages.error(self.request, f'Error creating configuration: {str(e)}')
            return self.form_invalid(form)

class PullConfigurationUpdateView(UpdateView):
    """Update an existing pull configuration"""
    template_name = 'pulls/configuration_form.html'
    form_class = PullConfigurationForm
    
    def get_object(self):
        config_id = self.kwargs.get('pk')
        with get_sa_session() as session:
            repo = PullConfigurationRepository(session)
            return repo.get_by_id(config_id)
    
    def get_initial(self):
        """Populate form with existing configuration data"""
        config = self.get_object()
        
        # Get associated stations
        with get_sa_session() as session:
            repo = PullConfigurationRepository(session)
            stations = repo.get_configuration_stations(config.id)
        
        return {
            'name': config.name,
            'description': config.description,
            'data_type': config.data_type,
            'data_strategy': config.data_strategy,
            'pull_start_date': config.pull_start_date,
            'schedule_type': config.schedule_type,
            'schedule_value': config.schedule_value,
            'is_enabled': config.is_enabled,
            'selected_stations': json.dumps([
                {
                    'station_number': s.station_number,
                    'station_name': s.station_name
                } for s in stations
            ])
        }
    
    def form_valid(self, form):
        try:
            config_id = self.kwargs.get('pk')
            with get_sa_session() as session:
                service = PullConfigurationService(session)
                
                # Update configuration
                config_data = {
                    'name': form.cleaned_data['name'],
                    'description': form.cleaned_data.get('description', ''),
                    'data_type': form.cleaned_data['data_type'],
                    'data_strategy': form.cleaned_data['data_strategy'],
                    'pull_start_date': form.cleaned_data['pull_start_date'],
                    'schedule_type': form.cleaned_data['schedule_type'],
                    'schedule_value': form.get_cron_expression(),
                    'is_enabled': form.cleaned_data.get('is_enabled', True),
                }
                
                selected_stations = form.cleaned_data['selected_stations']
                
                config = service.update_configuration(config_id, config_data, selected_stations)
                
                # Update Celery Beat task
                celery_manager = CeleryBeatManager()
                if config.is_enabled:
                    celery_manager.create_or_update_task(config)
                else:
                    celery_manager.disable_task(config_id)
                
                messages.success(self.request, 'Configuration updated successfully!')
                return redirect('pulls:detail', pk=config_id)
                
        except Exception as e:
            messages.error(self.request, f'Error updating configuration: {str(e)}')
            return self.form_invalid(form)

class PullConfigurationDeleteView(DeleteView):
    """Delete a pull configuration"""
    template_name = 'pulls/configuration_confirm_delete.html'
    success_url = reverse_lazy('pulls:list')
    
    def get_object(self):
        config_id = self.kwargs.get('pk')
        with get_sa_session() as session:
            repo = PullConfigurationRepository(session)
            return repo.get_by_id(config_id)
    
    def delete(self, request, *args, **kwargs):
        config = self.get_object()
        config_id = config.id
        
        try:
            # Delete Celery Beat task first
            celery_manager = CeleryBeatManager()
            celery_manager.delete_task(config_id)
            
            # Delete configuration
            with get_sa_session() as session:
                service = PullConfigurationService(session)
                service.delete_configuration(config_id)
            
            messages.success(request, f'Configuration "{config.name}" deleted successfully!')
            return redirect(self.success_url)
            
        except Exception as e:
            messages.error(request, f'Error deleting configuration: {str(e)}')
            return redirect('pulls:detail', pk=config_id)

@require_http_methods(["POST"])
def toggle_configuration(request, pk):
    """Enable/disable a configuration via AJAX"""
    try:
        with get_sa_session() as session:
            repo = PullConfigurationRepository(session)
            config = repo.get_by_id(pk)
            
            # Toggle enabled state
            config.is_enabled = not config.is_enabled
            session.commit()
            
            # Update Celery Beat task
            celery_manager = CeleryBeatManager()
            if config.is_enabled:
                celery_manager.create_or_update_task(config)
            else:
                celery_manager.disable_task(pk)
            
            return JsonResponse({
                'success': True,
                'is_enabled': config.is_enabled
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@require_http_methods(["POST"])
def trigger_manual_run(request, pk):
    """Manually trigger a configuration run"""
    try:
        from src.acquisition.tasks import execute_pull_configuration
        
        # Queue the task immediately
        task = execute_pull_configuration.delay(pk)
        
        messages.success(request, f'Pull job queued successfully! Task ID: {task.id}')
        return redirect('pulls:detail', pk=pk)
        
    except Exception as e:
        messages.error(request, f'Error triggering job: {str(e)}')
        return redirect('pulls:detail', pk=pk)
```

---

### Phase 5: Business Logic Service Layer

#### 5.1 Configuration Service (`apps/pulls/services.py`)
```python
"""
Business logic for pull configuration management
"""
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict, Optional
import logging

from src.database.models import (
    PullConfiguration,
    PullConfigurationStation,
    PullStationProgress
)
from src.database.repositories import PullConfigurationRepository

logger = logging.getLogger(__name__)

class PullConfigurationService:
    """Service layer for pull configuration operations"""
    
    def __init__(self, session: Session):
        self.session = session
        self.repo = PullConfigurationRepository(session)
    
    def create_configuration(self, 
                           config_data: Dict, 
                           selected_stations: List[Dict]) -> PullConfiguration:
        """
        Create a new pull configuration with associated stations
        
        Args:
            config_data: Dictionary with configuration fields
            selected_stations: List of station dictionaries
        
        Returns:
            Created PullConfiguration instance
        """
        try:
            # Create configuration
            config = PullConfiguration(**config_data)
            self.session.add(config)
            self.session.flush()  # Get config.id without committing
            
            # Add stations
            for station_data in selected_stations:
                station = PullConfigurationStation(
                    config_id=config.id,
                    station_number=station_data['station_number'],
                    station_name=station_data.get('station_name'),
                    huc_code=station_data.get('huc_code'),
                    state=station_data.get('state')
                )
                self.session.add(station)
            
            # Initialize progress tracking for each station
            for station_data in selected_stations:
                progress = PullStationProgress(
                    config_id=config.id,
                    station_number=station_data['station_number'],
                    last_successful_pull_date=None  # Will be set after first pull
                )
                self.session.add(progress)
            
            self.session.commit()
            self.session.refresh(config)
            
            logger.info(f"Created configuration {config.id} with {len(selected_stations)} stations")
            return config
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error creating configuration: {e}")
            raise
    
    def update_configuration(self,
                           config_id: int,
                           config_data: Dict,
                           selected_stations: List[Dict]) -> PullConfiguration:
        """
        Update an existing pull configuration
        
        Args:
            config_id: Configuration ID
            config_data: Dictionary with updated configuration fields
            selected_stations: List of station dictionaries
        
        Returns:
            Updated PullConfiguration instance
        """
        try:
            config = self.repo.get_by_id(config_id)
            if not config:
                raise ValueError(f"Configuration {config_id} not found")
            
            # Update configuration fields
            for key, value in config_data.items():
                setattr(config, key, value)
            
            config.updated_at = datetime.utcnow()
            
            # Delete existing stations
            self.session.query(PullConfigurationStation)\
                .filter(PullConfigurationStation.config_id == config_id)\
                .delete()
            
            # Add updated stations
            for station_data in selected_stations:
                station = PullConfigurationStation(
                    config_id=config.id,
                    station_number=station_data['station_number'],
                    station_name=station_data.get('station_name'),
                    huc_code=station_data.get('huc_code'),
                    state=station_data.get('state')
                )
                self.session.add(station)
            
            # Add any new stations to progress tracking
            existing_progress = self.session.query(PullStationProgress)\
                .filter(PullStationProgress.config_id == config_id)\
                .all()
            
            existing_stations = {p.station_number for p in existing_progress}
            
            for station_data in selected_stations:
                if station_data['station_number'] not in existing_stations:
                    progress = PullStationProgress(
                        config_id=config.id,
                        station_number=station_data['station_number']
                    )
                    self.session.add(progress)
            
            self.session.commit()
            self.session.refresh(config)
            
            logger.info(f"Updated configuration {config_id}")
            return config
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error updating configuration: {e}")
            raise
    
    def delete_configuration(self, config_id: int):
        """
        Delete a pull configuration and all associated data
        
        Args:
            config_id: Configuration ID
        """
        try:
            # Delete associated records (cascade should handle this, but explicit is better)
            self.session.query(PullConfigurationStation)\
                .filter(PullConfigurationStation.config_id == config_id)\
                .delete()
            
            self.session.query(PullStationProgress)\
                .filter(PullStationProgress.config_id == config_id)\
                .delete()
            
            # Note: We might want to keep DataPullLog for audit purposes
            # self.session.query(DataPullLog).filter(...).delete()
            
            # Delete configuration
            config = self.repo.get_by_id(config_id)
            if config:
                self.session.delete(config)
            
            self.session.commit()
            logger.info(f"Deleted configuration {config_id}")
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error deleting configuration: {e}")
            raise
    
    def get_configuration_statistics(self, config_id: int) -> Dict:
        """
        Get statistics for a configuration
        
        Returns:
            Dictionary with statistics (total runs, success rate, etc.)
        """
        from src.database.repositories import DataPullLogRepository
        
        log_repo = DataPullLogRepository(self.session)
        logs = log_repo.get_logs_for_config(config_id)
        
        total_runs = len(logs)
        successful_runs = len([l for l in logs if l.status == 'success'])
        failed_runs = len([l for l in logs if l.status == 'failed'])
        total_records = sum(l.records_processed or 0 for l in logs)
        
        return {
            'total_runs': total_runs,
            'successful_runs': successful_runs,
            'failed_runs': failed_runs,
            'success_rate': (successful_runs / total_runs * 100) if total_runs > 0 else 0,
            'total_records_processed': total_records,
            'last_run': logs[0] if logs else None
        }
```

---

### Phase 6: Celery Beat Integration

#### 6.1 Celery Beat Manager (`apps/pulls/celery_manager.py`)
```python
"""
Manages Celery Beat periodic tasks for pull configurations
"""
from django_celery_beat.models import PeriodicTask, CrontabSchedule
from django.utils import timezone
import json
import logging

logger = logging.getLogger(__name__)

class CeleryBeatManager:
    """Manages dynamic Celery Beat task creation and updates"""
    
    @staticmethod
    def parse_cron_expression(cron_expr: str) -> dict:
        """
        Parse cron expression into components
        
        Args:
            cron_expr: Cron expression (e.g., '0 */6 * * *')
        
        Returns:
            Dictionary with cron components
        """
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}")
        
        return {
            'minute': parts[0],
            'hour': parts[1],
            'day_of_month': parts[2],
            'month_of_year': parts[3],
            'day_of_week': parts[4]
        }
    
    def get_or_create_crontab(self, cron_expr: str) -> CrontabSchedule:
        """
        Get or create a CrontabSchedule instance
        
        Args:
            cron_expr: Cron expression
        
        Returns:
            CrontabSchedule instance
        """
        cron_parts = self.parse_cron_expression(cron_expr)
        
        schedule, created = CrontabSchedule.objects.get_or_create(
            minute=cron_parts['minute'],
            hour=cron_parts['hour'],
            day_of_month=cron_parts['day_of_month'],
            month_of_year=cron_parts['month_of_year'],
            day_of_week=cron_parts['day_of_week']
        )
        
        return schedule
    
    def create_or_update_task(self, config):
        """
        Create or update a Celery Beat periodic task for a configuration
        
        Args:
            config: PullConfiguration instance
        """
        try:
            # Get or create crontab schedule
            schedule = self.get_or_create_crontab(config.schedule_value)
            
            # Task name
            task_name = f"pull_config_{config.id}"
            
            # Check if task exists
            task, created = PeriodicTask.objects.get_or_create(
                name=task_name,
                defaults={
                    'task': 'src.acquisition.tasks.execute_pull_configuration',
                    'crontab': schedule,
                    'args': json.dumps([config.id]),
                    'enabled': config.is_enabled,
                }
            )
            
            # Update if it already exists
            if not created:
                task.crontab = schedule
                task.enabled = config.is_enabled
                task.args = json.dumps([config.id])
                task.save()
            
            logger.info(f"{'Created' if created else 'Updated'} Celery Beat task for config {config.id}")
            
            return task
            
        except Exception as e:
            logger.error(f"Error creating/updating Celery Beat task: {e}")
            raise
    
    def disable_task(self, config_id: int):
        """
        Disable a Celery Beat task
        
        Args:
            config_id: Configuration ID
        """
        try:
            task_name = f"pull_config_{config_id}"
            task = PeriodicTask.objects.filter(name=task_name).first()
            
            if task:
                task.enabled = False
                task.save()
                logger.info(f"Disabled Celery Beat task for config {config_id}")
            
        except Exception as e:
            logger.error(f"Error disabling Celery Beat task: {e}")
            raise
    
    def delete_task(self, config_id: int):
        """
        Delete a Celery Beat task
        
        Args:
            config_id: Configuration ID
        """
        try:
            task_name = f"pull_config_{config_id}"
            deleted = PeriodicTask.objects.filter(name=task_name).delete()
            
            if deleted[0] > 0:
                logger.info(f"Deleted Celery Beat task for config {config_id}")
            
        except Exception as e:
            logger.error(f"Error deleting Celery Beat task: {e}")
            raise
```

---


### Phase 7: Templates and Frontend

#### 7.1 Base Template (`templates/base.html`)
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Streamflow DataOps{% endblock %}</title>
    
    <!-- Bootstrap 5 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    
    {% block extra_css %}{% endblock %}
</head>
<body>
    {% include 'navbar.html' %}
    
    <main class="container-fluid mt-4">
        <!-- Django Messages -->
        {% if messages %}
        <div class="row">
            <div class="col-12">
                {% for message in messages %}
                <div class="alert alert-{{ message.tags }} alert-dismissible fade show" role="alert">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}
        
        {% block content %}{% endblock %}
    </main>
    
    <!-- Bootstrap 5 JS Bundle -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    
    {% block extra_js %}{% endblock %}
</body>
</html>
```

#### 7.2 Configuration List Template (`apps/pulls/templates/pulls/configuration_list.html`)
```html
{% extends "base.html" %}

{% block title %}Pull Configurations{% endblock %}

{% block content %}
<div class="row">
    <div class="col-12">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2>Pull Configurations</h2>
            <a href="{% url 'pulls:create' %}" class="btn btn-primary">
                <i class="bi bi-plus-circle"></i> Create New Configuration
            </a>
        </div>
        
        <div class="card">
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Data Type</th>
                                <th>Schedule</th>
                                <th>Stations</th>
                                <th>Status</th>
                                <th>Last Run</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for config in configurations %}
                            <tr>
                                <td>
                                    <a href="{% url 'pulls:detail' config.id %}">
                                        {{ config.name }}
                                    </a>
                                </td>
                                <td>
                                    <span class="badge bg-info">{{ config.data_type }}</span>
                                </td>
                                <td>
                                    <small>{{ config.schedule_value }}</small>
                                </td>
                                <td>
                                    {{ config.configuration_stations|length }}
                                </td>
                                <td>
                                    {% if config.is_enabled %}
                                    <span class="badge bg-success">Enabled</span>
                                    {% else %}
                                    <span class="badge bg-secondary">Disabled</span>
                                    {% endif %}
                                </td>
                                <td>
                                    {% if config.last_run_at %}
                                    {{ config.last_run_at|date:"Y-m-d H:i" }}
                                    {% else %}
                                    <em>Never</em>
                                    {% endif %}
                                </td>
                                <td>
                                    <div class="btn-group btn-group-sm" role="group">
                                        <a href="{% url 'pulls:detail' config.id %}" 
                                           class="btn btn-outline-primary" 
                                           title="View">
                                            <i class="bi bi-eye"></i>
                                        </a>
                                        <a href="{% url 'pulls:update' config.id %}" 
                                           class="btn btn-outline-secondary" 
                                           title="Edit">
                                            <i class="bi bi-pencil"></i>
                                        </a>
                                        <form method="post" 
                                              action="{% url 'pulls:trigger_manual_run' config.id %}" 
                                              style="display: inline;">
                                            {% csrf_token %}
                                            <button type="submit" 
                                                    class="btn btn-outline-success" 
                                                    title="Run Now">
                                                <i class="bi bi-play-fill"></i>
                                            </button>
                                        </form>
                                    </div>
                                </td>
                            </tr>
                            {% empty %}
                            <tr>
                                <td colspan="7" class="text-center">
                                    No configurations found. 
                                    <a href="{% url 'pulls:create' %}">Create one now</a>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                
                <!-- Pagination -->
                {% if is_paginated %}
                <nav>
                    <ul class="pagination justify-content-center">
                        {% if page_obj.has_previous %}
                        <li class="page-item">
                            <a class="page-link" href="?page={{ page_obj.previous_page_number }}">Previous</a>
                        </li>
                        {% endif %}
                        
                        <li class="page-item active">
                            <span class="page-link">Page {{ page_obj.number }} of {{ page_obj.paginator.num_pages }}</span>
                        </li>
                        
                        {% if page_obj.has_next %}
                        <li class="page-item">
                            <a class="page-link" href="?page={{ page_obj.next_page_number }}">Next</a>
                        </li>
                        {% endif %}
                    </ul>
                </nav>
                {% endif %}
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

#### 7.3 Configuration Form Template (`apps/pulls/templates/pulls/configuration_form.html`)
```html
{% extends "base.html" %}
{% load crispy_forms_tags %}

{% block title %}{{ form.instance.id|yesno:"Edit,Create" }} Configuration{% endblock %}

{% block content %}
<div class="row">
    <div class="col-lg-8 offset-lg-2">
        <h2>{{ form.instance.id|yesno:"Edit,Create" }} Pull Configuration</h2>
        
        <div class="card mt-4">
            <div class="card-body">
                <form method="post">
                    {% csrf_token %}
                    
                    <!-- Basic Information -->
                    <h5 class="border-bottom pb-2">Basic Information</h5>
                    <div class="row mb-3">
                        <div class="col-md-8">
                            {{ form.name|as_crispy_field }}
                        </div>
                        <div class="col-md-4">
                            <div class="form-check mt-4">
                                {{ form.is_enabled }}
                                <label class="form-check-label" for="{{ form.is_enabled.id_for_label }}">
                                    Enable Configuration
                                </label>
                            </div>
                        </div>
                    </div>
                    
                    {{ form.description|as_crispy_field }}
                    
                    <!-- Data Configuration -->
                    <h5 class="border-bottom pb-2 mt-4">Data Configuration</h5>
                    <div class="row">
                        <div class="col-md-6">
                            {{ form.data_type|as_crispy_field }}
                        </div>
                        <div class="col-md-6">
                            {{ form.data_strategy|as_crispy_field }}
                        </div>
                    </div>
                    
                    <div class="row">
                        <div class="col-md-6">
                            {{ form.pull_start_date|as_crispy_field }}
                        </div>
                    </div>
                    
                    <!-- Schedule Configuration -->
                    <h5 class="border-bottom pb-2 mt-4">Schedule Configuration</h5>
                    <div class="row">
                        <div class="col-md-6">
                            {{ form.schedule_type|as_crispy_field }}
                        </div>
                        <div class="col-md-6" id="custom-cron-field" style="display: none;">
                            {{ form.schedule_value|as_crispy_field }}
                        </div>
                    </div>
                    
                    <!-- Station Selection -->
                    <h5 class="border-bottom pb-2 mt-4">Station Selection</h5>
                    <div class="mb-3">
                        <a href="{% url 'stations:search' %}" 
                           class="btn btn-info" 
                           target="_blank">
                            <i class="bi bi-search"></i> Search and Select Stations
                        </a>
                        <small class="form-text text-muted d-block mt-2">
                            Click to open station search in a new tab. Selected stations will be automatically added.
                        </small>
                    </div>
                    
                    {{ form.selected_stations }}
                    
                    <div id="selected-stations-display" class="mt-3">
                        <h6>Selected Stations:</h6>
                        <div id="station-list" class="list-group">
                            <!-- Will be populated by JavaScript -->
                        </div>
                    </div>
                    
                    <!-- Form Actions -->
                    <div class="mt-4">
                        <button type="submit" class="btn btn-primary">
                            <i class="bi bi-save"></i> Save Configuration
                        </button>
                        <a href="{% url 'pulls:list' %}" class="btn btn-secondary">
                            <i class="bi bi-x-circle"></i> Cancel
                        </a>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script>
// Show/hide custom cron field based on schedule type
document.getElementById('id_schedule_type').addEventListener('change', function() {
    const customField = document.getElementById('custom-cron-field');
    if (this.value === 'custom_cron') {
        customField.style.display = 'block';
    } else {
        customField.style.display = 'none';
    }
});

// Trigger on page load
document.getElementById('id_schedule_type').dispatchEvent(new Event('change'));

// Load selected stations from sessionStorage
function loadSelectedStations() {
    const selectedStations = JSON.parse(sessionStorage.getItem('selectedStations') || '[]');
    const stationList = document.getElementById('station-list');
    const hiddenField = document.getElementById('id_selected_stations');
    
    stationList.innerHTML = '';
    
    if (selectedStations.length === 0) {
        stationList.innerHTML = '<div class="list-group-item">No stations selected</div>';
    } else {
        selectedStations.forEach((station, index) => {
            const item = document.createElement('div');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            item.innerHTML = `
                <span>
                    <strong>${station.station_number}</strong> - ${station.station_name}
                </span>
                <button type="button" class="btn btn-sm btn-danger" onclick="removeStation(${index})">
                    <i class="bi bi-trash"></i>
                </button>
            `;
            stationList.appendChild(item);
        });
    }
    
    // Update hidden field
    hiddenField.value = JSON.stringify(selectedStations);
}

function removeStation(index) {
    const selectedStations = JSON.parse(sessionStorage.getItem('selectedStations') || '[]');
    selectedStations.splice(index, 1);
    sessionStorage.setItem('selectedStations', JSON.stringify(selectedStations));
    loadSelectedStations();
}

// Load stations on page load
window.addEventListener('load', loadSelectedStations);

// Poll for updates from station search page
setInterval(loadSelectedStations, 1000);

// Clear sessionStorage on form submit
document.querySelector('form').addEventListener('submit', function() {
    sessionStorage.removeItem('selectedStations');
});
</script>
{% endblock %}
```

---

### Phase 8: Monitoring and Logging Interface

#### 8.1 Monitoring Views (`apps/monitoring/views.py`)
```python
from django.shortcuts import render
from django.views.generic import ListView, DetailView
from apps.pulls.sqlalchemy_models import get_sa_session
from src.database.repositories import DataPullLogRepository
from src.database.models import DataPullLog

class DataPullLogListView(ListView):
    """View all data pull logs"""
    template_name = 'monitoring/log_list.html'
    context_object_name = 'logs'
    paginate_by = 50
    
    def get_queryset(self):
        with get_sa_session() as session:
            repo = DataPullLogRepository(session)
            
            # Optional filtering
            status = self.request.GET.get('status')
            config_id = self.request.GET.get('config_id')
            
            return repo.get_logs(
                status=status,
                config_id=config_id,
                limit=500
            )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_status'] = self.request.GET.get('status', '')
        context['filter_config_id'] = self.request.GET.get('config_id', '')
        return context

class DashboardView(ListView):
    """Main dashboard with system overview"""
    template_name = 'monitoring/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        with get_sa_session() as session:
            from src.database.repositories import (
                PullConfigurationRepository,
                DataPullLogRepository
            )
            
            config_repo = PullConfigurationRepository(session)
            log_repo = DataPullLogRepository(session)
            
            # Get statistics
            all_configs = config_repo.get_all()
            recent_logs = log_repo.get_recent_logs(limit=10)
            
            context.update({
                'total_configurations': len(all_configs),
                'enabled_configurations': len([c for c in all_configs if c.is_enabled]),
                'recent_logs': recent_logs,
                'failed_runs_today': log_repo.count_failed_today(),
            })
        
        return context
```

#### 8.2 Dashboard Template (`apps/monitoring/templates/monitoring/dashboard.html`)
```html
{% extends "base.html" %}

{% block title %}Dashboard{% endblock %}

{% block content %}
<div class="row">
    <div class="col-12">
        <h2>System Dashboard</h2>
    </div>
</div>

<!-- Statistics Cards -->
<div class="row mt-4">
    <div class="col-md-3">
        <div class="card text-white bg-primary">
            <div class="card-body">
                <h5 class="card-title">Total Configurations</h5>
                <p class="card-text display-4">{{ total_configurations }}</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card text-white bg-success">
            <div class="card-body">
                <h5 class="card-title">Enabled</h5>
                <p class="card-text display-4">{{ enabled_configurations }}</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card text-white bg-danger">
            <div class="card-body">
                <h5 class="card-title">Failed Runs Today</h5>
                <p class="card-text display-4">{{ failed_runs_today }}</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card text-white bg-info">
            <div class="card-body">
                <h5 class="card-title">Recent Logs</h5>
                <p class="card-text display-4">{{ recent_logs|length }}</p>
            </div>
        </div>
    </div>
</div>

<!-- Recent Activity -->
<div class="row mt-4">
    <div class="col-12">
        <div class="card">
            <div class="card-header">
                <h5>Recent Activity</h5>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Configuration</th>
                                <th>Status</th>
                                <th>Records Processed</th>
                                <th>Duration</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for log in recent_logs %}
                            <tr>
                                <td>{{ log.start_time|date:"Y-m-d H:i:s" }}</td>
                                <td>
                                    <a href="{% url 'pulls:detail' log.config_id %}">
                                        Config #{{ log.config_id }}
                                    </a>
                                </td>
                                <td>
                                    {% if log.status == 'success' %}
                                    <span class="badge bg-success">Success</span>
                                    {% elif log.status == 'failed' %}
                                    <span class="badge bg-danger">Failed</span>
                                    {% else %}
                                    <span class="badge bg-warning">{{ log.status }}</span>
                                    {% endif %}
                                </td>
                                <td>{{ log.records_processed|default:"N/A" }}</td>
                                <td>
                                    {% if log.end_time %}
                                    {{ log.end_time|timeuntil:log.start_time }}
                                    {% else %}
                                    Running...
                                    {% endif %}
                                </td>
                            </tr>
                            {% empty %}
                            <tr>
                                <td colspan="5" class="text-center">No recent activity</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

---

### Phase 9: URL Configuration

#### 9.1 Main URLs (`config/urls.py`)
```python
from django.contrib import admin
from django.urls import path, include
from apps.monitoring.views import DashboardView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', DashboardView.as_view(), name='home'),
    path('stations/', include('apps.stations.urls')),
    path('pulls/', include('apps.pulls.urls')),
    path('monitoring/', include('apps.monitoring.urls')),
]
```

#### 9.2 Pulls URLs (`apps/pulls/urls.py`)
```python
from django.urls import path
from apps.pulls import views

app_name = 'pulls'

urlpatterns = [
    path('', views.PullConfigurationListView.as_view(), name='list'),
    path('create/', views.PullConfigurationCreateView.as_view(), name='create'),
    path('<int:pk>/', views.PullConfigurationDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', views.PullConfigurationUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', views.PullConfigurationDeleteView.as_view(), name='delete'),
    path('<int:pk>/toggle/', views.toggle_configuration, name='toggle'),
    path('<int:pk>/run/', views.trigger_manual_run, name='trigger_manual_run'),
]
```

#### 9.3 Stations URLs (`apps/stations/urls.py`)
```python
from django.urls import path
from apps.stations import views

app_name = 'stations'

urlpatterns = [
    path('search/', views.StationSearchView.as_view(), name='search'),
    path('<str:station_number>/', views.StationDetailView.as_view(), name='detail'),
]
```

---

### Phase 10: Deployment and Testing

#### 10.1 Environment Setup
Create `.env` file:
```
DEBUG=True
SECRET_KEY=your-secret-key-change-in-production
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DB_NAME=streamflow_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
```

#### 10.2 Initialize Django
```bash
# Install dependencies
pip install -r requirements.txt

# Run Django migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic --noinput
```

#### 10.3 Run Development Server
```bash
# Terminal 1: Start Redis
redis-server

# Terminal 2: Start Celery Worker
celery -A src.celery_app.celery worker --loglevel=info

# Terminal 3: Start Celery Beat
celery -A src.celery_app.celery beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler

# Terminal 4: Start Django
python manage.py runserver
```

#### 10.4 Production Deployment
For production, use:
- **Gunicorn** or **uWSGI** for Django
- **Supervisor** or **systemd** for Celery workers
- **Nginx** as reverse proxy
- **PostgreSQL** for database

Example systemd service for Celery:
```ini
[Unit]
Description=Streamflow DataOps Celery Worker
After=network.target

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/path/to/streamflow_dataops
ExecStart=/path/to/venv/bin/celery -A src.celery_app.celery worker --loglevel=info

[Install]
WantedBy=multi-user.target
```

---

## Implementation Checklist

- [ ] Phase 1: Django project setup and structure
- [ ] Phase 2: SQLAlchemy integration with Django
- [ ] Phase 3: Station selection interface
- [ ] Phase 4: Pull configuration management (forms and views)
- [ ] Phase 5: Business logic service layer
- [ ] Phase 6: Celery Beat integration
- [ ] Phase 7: Templates and frontend UI
- [ ] Phase 8: Monitoring and logging interface
- [ ] Phase 9: URL configuration
- [ ] Phase 10: Deployment and testing
- [ ] Additional: User authentication and permissions
- [ ] Additional: API endpoints for external access
- [ ] Additional: Advanced monitoring dashboards
- [ ] Additional: Email/SMS notifications for failures
- [ ] Additional: Data quality reports

---

## Key Features Implemented

1. **Station Selection Workflow**: Search, filter, and select stations by State, HUC, and name
2. **Pull Configuration Management**: CRUD operations for data pull configurations
3. **Smart Append Logic**: Automatically implemented via PullStationProgress tracking
4. **Dynamic Scheduling**: Celery Beat tasks created/updated automatically
5. **Manual Triggering**: Ability to manually run configurations on-demand
6. **Monitoring Dashboard**: Real-time view of system status and recent activity
7. **Error Handling**: Comprehensive error tracking and reporting

---

## Testing Strategy

### Unit Tests
```python
# tests/test_configuration_service.py
def test_create_configuration_with_stations(test_db):
    service = PullConfigurationService(test_db)
    
    config_data = {
        'name': 'Test Config',
        'data_type': 'daily_mean',
        'data_strategy': 'append',
        'pull_start_date': datetime(2020, 1, 1),
        'schedule_type': 'daily',
        'schedule_value': '0 0 * * *',
        'is_enabled': True
    }
    
    stations = [
        {'station_number': '01010000', 'station_name': 'Test Station'}
    ]
    
    config = service.create_configuration(config_data, stations)
    assert config.id is not None
```

### Integration Tests
Test the full workflow from station selection to Celery task creation.

---

## Next Steps

After completing Component 3:
1. **Integrate with Component 2**: Ensure Celery tasks are properly called
2. **Build Component 4**: REST API for external access
3. **Add user authentication**: Implement Django's auth system
4. **Create data visualization dashboards**: Charts for discharge trends
5. **Implement notifications**: Email alerts for failed jobs
6. **Performance optimization**: Database query optimization, caching

---

## Security Considerations

1. **CSRF Protection**: Enabled by default in Django
2. **SQL Injection**: Prevented by SQLAlchemy ORM
3. **Authentication**: Implement Django's built-in auth for production
4. **Rate Limiting**: Consider django-ratelimit for API endpoints
5. **HTTPS**: Always use HTTPS in production
6. **Environment Variables**: Never commit .env files to version control

---

## Maintenance and Monitoring

1. **Logging**: Centralized logging with rotation
2. **Error Tracking**: Consider Sentry for production error monitoring
3. **Performance Monitoring**: Use Django Debug Toolbar in development
4. **Database Backups**: Regular automated backups
5. **Celery Monitoring**: Use Flower or Celery events
6. **Health Checks**: Implement /health endpoint for monitoring

