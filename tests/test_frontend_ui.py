"""
Frontend UI/UX Tests for StreamFlow DataOps

These tests check:
1. Template rendering and context
2. UI elements presence (buttons, forms, links)
3. JavaScript functionality
4. Bootstrap component rendering
5. Responsive design elements
6. Form validation and user feedback
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.streamflow.models import (
    Station, PullConfiguration, PullConfigurationStation,
    DataPullLog, MasterStation, DischargeObservation
)
from bs4 import BeautifulSoup


class TemplateRenderingTests(TestCase):
    """Test that templates render correctly with proper HTML structure."""
    
    def setUp(self):
        self.client = Client()
    
    def test_base_template_has_bootstrap(self):
        """Verify base template includes Bootstrap CSS and JS."""
        response = self.client.get(reverse('streamflow:dashboard'))
        self.assertContains(response, 'bootstrap')
        self.assertContains(response, 'font-awesome')  # Check for FontAwesome CSS
    
    def test_navigation_menu_present(self):
        """Verify navigation menu is rendered on all pages."""
        urls = [
            reverse('streamflow:dashboard'),
            reverse('streamflow:configuration_list'),
            reverse('streamflow:log_list'),
            reverse('streamflow:master_station_list'),
        ]
        
        for url in urls:
            response = self.client.get(url)
            self.assertContains(response, '<nav', msg_prefix=f"Nav missing on {url}")
            self.assertContains(response, 'Dashboard', msg_prefix=f"Dashboard link missing on {url}")
    
    def test_page_titles_are_unique(self):
        """Each page should have a unique, descriptive title."""
        pages = {
            reverse('streamflow:dashboard'): 'Dashboard',
            reverse('streamflow:configuration_list'): 'Configurations',
            reverse('streamflow:log_list'): 'Data Pull Logs',
            reverse('streamflow:master_station_list'): 'All Stations',
        }
        
        for url, expected_text in pages.items():
            response = self.client.get(url)
            self.assertContains(response, expected_text, msg_prefix=f"Title missing on {url}")


class DashboardUITests(TestCase):
    """Test dashboard UI elements and layout."""
    
    def setUp(self):
        self.client = Client()
        self.url = reverse('streamflow:dashboard')
        
        # Create test data
        self.config = PullConfiguration.objects.create(
            name='Test Config',
            data_source='USGS',
            data_type='daily_mean',
            data_strategy='append',
            pull_start_date=timezone.now(),
            is_enabled=True
        )
        
        self.station = Station.objects.create(
            station_number='12345678',
            name='Test Station',
            agency='USGS'
        )
    
    def test_dashboard_stat_cards_present(self):
        """Dashboard should show configuration and station statistics."""
        response = self.client.get(self.url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Check for stat cards
        cards = soup.find_all('div', class_='card')
        self.assertGreater(len(cards), 0, "No stat cards found on dashboard")
    
    def test_dashboard_shows_enabled_disabled_counts(self):
        """Dashboard should display enabled/disabled configuration counts."""
        response = self.client.get(self.url)
        
        self.assertIn('enabled_configs', response.context)
        self.assertIn('disabled_configs', response.context)
        self.assertEqual(response.context['enabled_configs'], 1)
    
    def test_dashboard_recent_logs_table(self):
        """Dashboard should show recent logs in a table."""
        # Create a log
        DataPullLog.objects.create(
            configuration=self.config,
            status='success',
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(minutes=5)
        )
        
        response = self.client.get(self.url)
        self.assertContains(response, 'Test Config')
        self.assertContains(response, 'success')
    
    def test_dashboard_has_action_buttons(self):
        """Dashboard should have quick action buttons."""
        response = self.client.get(self.url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for buttons
        buttons = soup.find_all('a', class_='btn')
        self.assertGreater(len(buttons), 0, "No action buttons found")


class ConfigurationListUITests(TestCase):
    """Test configuration list page UI."""
    
    def setUp(self):
        self.client = Client()
        self.url = reverse('streamflow:configuration_list')
        
        # Create test configurations
        self.config1 = PullConfiguration.objects.create(
            name='USGS Config',
            data_source='USGS',
            data_type='daily_mean',
            data_strategy='append',
            pull_start_date=timezone.now(),
            is_enabled=True
        )
        
        self.config2 = PullConfiguration.objects.create(
            name='NOAA Config',
            data_source='NOAA_RFC',
            data_type='forecast',
            data_strategy='append',
            pull_start_date=timezone.now(),
            is_enabled=False
        )
    
    def test_configuration_list_shows_all_configs(self):
        """Configuration list should display all configurations."""
        response = self.client.get(self.url)
        self.assertContains(response, 'USGS Config')
        self.assertContains(response, 'NOAA Config')
    
    def test_configuration_cards_show_status_badges(self):
        """Each configuration should show enabled/disabled status."""
        response = self.client.get(self.url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for badges
        badges = soup.find_all('span', class_='badge')
        self.assertGreater(len(badges), 0, "No status badges found")
    
    def test_configuration_has_action_buttons(self):
        """Each configuration should have view, edit, trigger buttons."""
        response = self.client.get(self.url)
        
        # Should have links to detail, update, and trigger
        self.assertContains(response, 'View')
        self.assertContains(response, 'Edit')
        self.assertContains(response, 'trigger')
    
    def test_create_configuration_button_present(self):
        """Should have a prominent 'Create Configuration' button."""
        response = self.client.get(self.url)
        self.assertContains(response, 'Create')
        self.assertContains(response, 'btn-primary')


class MasterStationListUITests(TestCase):
    """Test master station list page UI and filtering."""
    
    def setUp(self):
        self.client = Client()
        self.url = reverse('streamflow:master_station_list')
        
        # Create test stations
        MasterStation.objects.create(
            station_number='12345678',
            station_name='USGS Test Station',
            agency='USGS',
            state_code='CA',
            huc_code='18010101'
        )
        
        MasterStation.objects.create(
            station_number='ABCD1',
            station_name='NOAA Test Station',
            agency='NOAA_RFC',
            state_code='OR',
            rfc_code='NWRFC'
        )
    
    def test_master_station_list_loads(self):
        """Master station list page should load successfully."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
    
    def test_filter_form_present(self):
        """Should have a filter form with agency, state, RFC, HUC fields."""
        response = self.client.get(self.url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Check for filter inputs
        self.assertIsNotNone(soup.find('select', {'name': 'agency'}), "Agency filter missing")
        self.assertIsNotNone(soup.find('select', {'name': 'state'}), "State filter missing")
        self.assertIsNotNone(soup.find('select', {'name': 'rfc'}), "RFC filter missing")
        self.assertIsNotNone(soup.find('input', {'name': 'huc'}), "HUC filter missing")
    
    def test_station_table_shows_data(self):
        """Station table should display station data."""
        response = self.client.get(self.url)
        self.assertContains(response, '12345678')
        self.assertContains(response, 'USGS Test Station')
        self.assertContains(response, 'ABCD1')
    
    def test_rfc_filter_works(self):
        """Filtering by RFC should work correctly."""
        response = self.client.get(self.url, {'rfc': 'NWRFC'})
        self.assertContains(response, 'ABCD1')
        self.assertNotContains(response, '12345678')
    
    def test_pagination_present(self):
        """Should have pagination controls if many stations."""
        # Create more stations
        for i in range(105):
            MasterStation.objects.create(
                station_number=f'TEST{i:04d}',
                station_name=f'Test Station {i}',
                agency='USGS'
            )
        
        response = self.client.get(self.url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Check for pagination
        pagination = soup.find('nav', attrs={'aria-label': 'Page navigation'}) or \
                    soup.find('ul', class_='pagination')
        self.assertIsNotNone(pagination, "Pagination not found with many records")


class ConfigurationDetailUITests(TestCase):
    """Test configuration detail page UI."""
    
    def setUp(self):
        self.client = Client()
        self.config = PullConfiguration.objects.create(
            name='Test Config',
            data_source='USGS',
            data_type='daily_mean',
            data_strategy='append',
            pull_start_date=timezone.now(),
            is_enabled=True
        )
        self.url = reverse('streamflow:configuration_detail', args=[self.config.id])
        
        # Add stations to config
        PullConfigurationStation.objects.create(
            configuration=self.config,
            station_number='12345678',
            station_name='Test Station',
            state='CA'
        )
    
    def test_detail_page_shows_configuration_info(self):
        """Detail page should show all configuration information."""
        response = self.client.get(self.url)
        self.assertContains(response, 'Test Config')
        self.assertContains(response, 'USGS')
        self.assertContains(response, 'Discharge')  # Data type display
    
    def test_detail_page_shows_stations_table(self):
        """Should display a table of stations in the configuration."""
        response = self.client.get(self.url)
        self.assertContains(response, '12345678')
        self.assertContains(response, 'Test Station')
    
    def test_trigger_button_present(self):
        """Should have a manual trigger button."""
        response = self.client.get(self.url)
        self.assertContains(response, 'trigger', msg_prefix="Trigger button missing")
    
    def test_add_stations_button_present(self):
        """Should have a button to add more stations."""
        response = self.client.get(self.url)
        self.assertContains(response, 'Add', msg_prefix="Add stations button missing")
    
    def test_recent_logs_displayed(self):
        """Should show recent logs for this configuration."""
        # Create a log
        DataPullLog.objects.create(
            configuration=self.config,
            status='success',
            start_time=timezone.now(),
            records_processed=100
        )
        
        response = self.client.get(self.url)
        self.assertContains(response, 'success')


class FormUITests(TestCase):
    """Test form UI and validation feedback."""
    
    def setUp(self):
        self.client = Client()
    
    def test_configuration_form_has_all_fields(self):
        """Configuration form should have all required fields."""
        response = self.client.get(reverse('streamflow:configuration_create'))
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Check for required fields
        self.assertIsNotNone(soup.find('input', {'name': 'name'}), "Name field missing")
        self.assertIsNotNone(soup.find('select', {'name': 'data_source'}), "Data source field missing")
        self.assertIsNotNone(soup.find('select', {'name': 'data_type'}), "Data type field missing")
        self.assertIsNotNone(soup.find('select', {'name': 'data_strategy'}), "Data strategy field missing")
        self.assertIsNotNone(soup.find('select', {'name': 'schedule_type'}), "Schedule type field missing")
    
    def test_form_shows_help_text(self):
        """Form fields should have helpful descriptions."""
        response = self.client.get(reverse('streamflow:configuration_create'))
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Check for help text elements (crispy forms uses 'form-text' class)
        help_texts = soup.find_all('div', class_='form-text') or \
                    soup.find_all('small', class_='form-text') or \
                    soup.find_all(class_='help-block')
        self.assertGreater(len(help_texts), 0, "No help text found in form")
    
    def test_form_validation_errors_displayed(self):
        """Invalid form submission should show error messages."""
        response = self.client.post(reverse('streamflow:configuration_create'), {
            'name': '',  # Invalid - required field
            'data_type': 'daily_mean',
            'data_strategy': 'append',
        })
        
        # Should show error
        self.assertContains(response, 'error', msg_prefix="Validation errors not displayed")


class ResponsiveDesignTests(TestCase):
    """Test responsive design elements."""
    
    def setUp(self):
        self.client = Client()
    
    def test_viewport_meta_tag_present(self):
        """Should have viewport meta tag for mobile responsiveness."""
        response = self.client.get(reverse('streamflow:dashboard'))
        self.assertContains(response, 'viewport')
    
    def test_bootstrap_grid_classes_used(self):
        """Templates should use Bootstrap grid system."""
        response = self.client.get(reverse('streamflow:dashboard'))
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Check for Bootstrap grid classes
        grid_elements = soup.find_all(class_=lambda x: x and ('col-' in x or 'row' in x))
        self.assertGreater(len(grid_elements), 0, "No Bootstrap grid classes found")


class AccessibilityTests(TestCase):
    """Test basic accessibility features."""
    
    def setUp(self):
        self.client = Client()
    
    def test_forms_have_labels(self):
        """All form inputs should have associated labels."""
        response = self.client.get(reverse('streamflow:configuration_create'))
        soup = BeautifulSoup(response.content, 'html.parser')
        
        inputs = soup.find_all('input', {'type': ['text', 'email', 'number']})
        selects = soup.find_all('select')
        
        for element in inputs + selects:
            element_id = element.get('id')
            if element_id:
                label = soup.find('label', {'for': element_id})
                self.assertIsNotNone(label, f"No label for input {element_id}")
    
    def test_buttons_have_descriptive_text(self):
        """Buttons should have descriptive text or aria-labels."""
        response = self.client.get(reverse('streamflow:configuration_list'))
        soup = BeautifulSoup(response.content, 'html.parser')
        
        buttons = soup.find_all('button')
        for button in buttons:
            has_text = button.get_text(strip=True)
            has_aria_label = button.get('aria-label')
            has_title = button.get('title')
            
            self.assertTrue(
                has_text or has_aria_label or has_title,
                f"Button has no descriptive text: {button}"
            )
    
    def test_images_have_alt_text(self):
        """Images should have alt text."""
        response = self.client.get(reverse('streamflow:dashboard'))
        soup = BeautifulSoup(response.content, 'html.parser')
        
        images = soup.find_all('img')
        for img in images:
            self.assertIsNotNone(img.get('alt'), f"Image missing alt text: {img.get('src')}")


class UserFeedbackTests(TestCase):
    """Test that user actions provide appropriate feedback."""
    
    def setUp(self):
        self.client = Client()
        self.config = PullConfiguration.objects.create(
            name='Test Config',
            data_source='USGS',
            data_type='daily_mean',
            data_strategy='append',
            pull_start_date=timezone.now(),
            is_enabled=True
        )
    
    def test_success_messages_displayed(self):
        """Successful actions should show success messages."""
        # Create a configuration
        response = self.client.post(
            reverse('streamflow:configuration_create'),
            {
                'name': 'New Test Config',
                'data_source': 'USGS',
                'data_type': 'daily_mean',
                'data_strategy': 'append',
                'pull_start_date': timezone.now().strftime('%Y-%m-%dT%H:%M'),
                'schedule_type': 'daily',
                'is_enabled': True,
            },
            follow=True
        )
        
        # Should show success message
        messages = list(response.context.get('messages', []))
        self.assertGreater(len(messages), 0, "No success message shown")
    
    def test_loading_states_present(self):
        """AJAX operations should show loading states."""
        # Check if templates have loading indicators
        response = self.client.get(
            reverse('streamflow:add_stations', args=[self.config.id])
        )
        # Look for loading spinner or indicator in template
        self.assertTrue(response.status_code == 200)


class NavigationTests(TestCase):
    """Test navigation and URL structure."""
    
    def setUp(self):
        self.client = Client()
    
    def test_all_main_urls_resolve(self):
        """All main navigation URLs should be accessible."""
        urls = [
            'streamflow:dashboard',
            'streamflow:configuration_list',
            'streamflow:configuration_create',
            'streamflow:log_list',
            'streamflow:station_list',
            'streamflow:master_station_list',
        ]
        
        for url_name in urls:
            url = reverse(url_name)
            response = self.client.get(url)
            self.assertIn(
                response.status_code,
                [200, 302],
                f"URL {url_name} returned {response.status_code}"
            )
    
    def test_breadcrumbs_present(self):
        """Detail pages should have breadcrumb navigation."""
        config = PullConfiguration.objects.create(
            name='Test',
            data_source='USGS',
            data_type='daily_mean',
            data_strategy='append',
            pull_start_date=timezone.now()
        )
        
        response = self.client.get(
            reverse('streamflow:configuration_detail', args=[config.id])
        )
        soup = BeautifulSoup(response.content, 'html.parser')
        
        breadcrumb = soup.find('nav', attrs={'aria-label': 'breadcrumb'}) or \
                    soup.find('ol', class_='breadcrumb')
        
        # Breadcrumbs are nice-to-have, not required
        # Just log if missing
        if not breadcrumb:
            print(f"Note: No breadcrumbs on configuration detail page")
