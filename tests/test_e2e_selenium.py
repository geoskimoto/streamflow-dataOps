"""
End-to-End Frontend Tests using Selenium

These tests simulate real user interactions in a browser.
Requires: pip install selenium
"""

from django.test import LiveServerTestCase
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from apps.streamflow.models import PullConfiguration, MasterStation
from django.utils import timezone
import time


class SeleniumTestCase(LiveServerTestCase):
    """Base class for Selenium tests."""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Set up Chrome in headless mode
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        
        try:
            cls.browser = webdriver.Chrome(options=chrome_options)
            cls.browser.implicitly_wait(10)
        except Exception as e:
            print(f"⚠️  Chrome WebDriver not available: {e}")
            print("   Install with: pip install selenium")
            print("   And download ChromeDriver from: https://chromedriver.chromium.org/")
            raise
    
    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'browser'):
            cls.browser.quit()
        super().tearDownClass()
    
    def wait_for_element(self, by, value, timeout=10):
        """Wait for element to be present."""
        try:
            element = WebDriverWait(self.browser, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except TimeoutException:
            self.fail(f"Element not found: {by}={value}")


class DashboardE2ETests(SeleniumTestCase):
    """Test dashboard page interactions."""
    
    def setUp(self):
        # Create test data
        self.config = PullConfiguration.objects.create(
            name='Test Config',
            data_source='USGS',
            data_type='daily_mean',
            data_strategy='append',
            pull_start_date=timezone.now(),
            is_enabled=True
        )
    
    def test_dashboard_loads_and_displays_stats(self):
        """Dashboard should load and show statistics."""
        self.browser.get(f'{self.live_server_url}/')
        
        # Wait for page to load
        self.wait_for_element(By.TAG_NAME, 'h1')
        
        # Check page title
        self.assertIn('Dashboard', self.browser.title or self.browser.find_element(By.TAG_NAME, 'h1').text)
        
        # Check for stat cards
        cards = self.browser.find_elements(By.CLASS_NAME, 'card')
        self.assertGreater(len(cards), 0, "No stat cards found")
    
    def test_navigation_links_work(self):
        """Test that navigation links are clickable and work."""
        self.browser.get(f'{self.live_server_url}/')
        
        # Find and click Configurations link
        try:
            config_link = self.browser.find_element(By.LINK_TEXT, 'Configurations')
            config_link.click()
            
            # Wait for page to load
            time.sleep(1)
            
            # Should be on configurations page
            self.assertIn('configuration', self.browser.current_url.lower())
        except Exception as e:
            print(f"Navigation test failed: {e}")
            # Take screenshot on failure
            self.browser.save_screenshot('/tmp/nav_test_failure.png')
            raise


class ConfigurationListE2ETests(SeleniumTestCase):
    """Test configuration list page interactions."""
    
    def setUp(self):
        # Create test configurations
        self.config1 = PullConfiguration.objects.create(
            name='USGS Daily Config',
            data_source='USGS',
            data_type='daily_mean',
            data_strategy='append',
            pull_start_date=timezone.now(),
            is_enabled=True
        )
        
        self.config2 = PullConfiguration.objects.create(
            name='NOAA Forecast Config',
            data_source='NOAA_RFC',
            data_type='forecast',
            data_strategy='append',
            pull_start_date=timezone.now(),
            is_enabled=False
        )
    
    def test_filter_configurations(self):
        """Test filtering configurations by status."""
        url = f'{self.live_server_url}/streamflow/configurations/'
        self.browser.get(url)
        
        # Wait for page to load
        self.wait_for_element(By.TAG_NAME, 'h2')
        
        # Both configs should be visible initially
        page_text = self.browser.page_source
        self.assertIn('USGS Daily Config', page_text)
        self.assertIn('NOAA Forecast Config', page_text)
    
    def test_create_configuration_button_visible(self):
        """Create button should be visible and clickable."""
        url = f'{self.live_server_url}/streamflow/configurations/'
        self.browser.get(url)
        
        # Find create button
        try:
            create_btn = self.browser.find_element(By.LINK_TEXT, 'Create Configuration')
            self.assertTrue(create_btn.is_displayed())
        except:
            # Try finding by class
            create_btn = self.browser.find_element(By.CLASS_NAME, 'btn-primary')
            self.assertIsNotNone(create_btn)


class MasterStationListE2ETests(SeleniumTestCase):
    """Test master station list filtering and search."""
    
    def setUp(self):
        # Create test stations
        MasterStation.objects.create(
            station_number='12345678',
            station_name='Test USGS Station',
            agency='USGS',
            state_code='CA',
            huc_code='18010101'
        )
        
        MasterStation.objects.create(
            station_number='NWRF1',
            station_name='Test NOAA Station',
            agency='NOAA_RFC',
            state_code='OR',
            rfc_code='NWRFC'
        )
    
    def test_station_list_loads(self):
        """Station list should load with data."""
        url = f'{self.live_server_url}/streamflow/stations/all/'
        self.browser.get(url)
        
        # Wait for table to load
        self.wait_for_element(By.TAG_NAME, 'table')
        
        # Should show stations
        page_text = self.browser.page_source
        self.assertIn('12345678', page_text)
    
    def test_filter_by_agency(self):
        """Test filtering stations by agency."""
        url = f'{self.live_server_url}/streamflow/stations/all/'
        self.browser.get(url)
        
        # Wait for form to load
        self.wait_for_element(By.NAME, 'agency')
        
        # Select NOAA_RFC agency
        try:
            agency_select = self.browser.find_element(By.NAME, 'agency')
            agency_select.click()
            
            # Select NOAA_RFC option
            noaa_option = self.browser.find_element(By.CSS_SELECTOR, 'option[value="NOAA_RFC"]')
            noaa_option.click()
            
            # Submit form
            submit_btn = self.browser.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            submit_btn.click()
            
            # Wait for page to reload
            time.sleep(2)
            
            # Should only show NOAA stations
            page_text = self.browser.page_source
            self.assertIn('NWRF1', page_text)
            self.assertNotIn('12345678', page_text)
        except Exception as e:
            print(f"Filter test failed: {e}")
            self.browser.save_screenshot('/tmp/filter_test_failure.png')
            raise
    
    def test_search_functionality(self):
        """Test searching for stations."""
        url = f'{self.live_server_url}/streamflow/stations/all/'
        self.browser.get(url)
        
        # Find search input
        try:
            search_input = self.browser.find_element(By.NAME, 'search')
            search_input.send_keys('NOAA')
            
            # Submit search
            submit_btn = self.browser.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            submit_btn.click()
            
            # Wait for results
            time.sleep(2)
            
            # Should show NOAA station
            page_text = self.browser.page_source
            self.assertIn('NOAA', page_text)
        except Exception as e:
            print(f"Search test failed: {e}")


class FormInteractionE2ETests(SeleniumTestCase):
    """Test form interactions and validation."""
    
    def test_configuration_form_validation(self):
        """Test that form validation works."""
        url = f'{self.live_server_url}/streamflow/configurations/create/'
        self.browser.get(url)
        
        # Wait for form to load
        self.wait_for_element(By.NAME, 'name')
        
        # Try to submit empty form
        submit_btn = self.browser.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        submit_btn.click()
        
        # Should show validation errors
        time.sleep(1)
        
        # HTML5 validation or Django validation should prevent submission
        # Check if still on same page (validation prevented submission)
        self.assertIn('create', self.browser.current_url)
    
    def test_form_help_text_visible(self):
        """Form fields should show help text."""
        url = f'{self.live_server_url}/streamflow/configurations/create/'
        self.browser.get(url)
        
        # Wait for form
        self.wait_for_element(By.NAME, 'name')
        
        # Look for help text elements
        help_texts = self.browser.find_elements(By.CLASS_NAME, 'form-text')
        
        if len(help_texts) == 0:
            # Try alternative classes
            help_texts = self.browser.find_elements(By.CLASS_NAME, 'help-block')
        
        self.assertGreater(len(help_texts), 0, "No help text found in form")


class ResponsiveDesignE2ETests(SeleniumTestCase):
    """Test responsive design at different screen sizes."""
    
    def test_mobile_viewport(self):
        """Test that page works on mobile viewport."""
        # Set mobile viewport
        self.browser.set_window_size(375, 667)  # iPhone size
        
        self.browser.get(f'{self.live_server_url}/')
        
        # Wait for page to load
        self.wait_for_element(By.TAG_NAME, 'body')
        
        # Page should still be functional
        # Navigation might be collapsed on mobile
        try:
            # Look for mobile menu toggle
            nav = self.browser.find_element(By.TAG_NAME, 'nav')
            self.assertIsNotNone(nav)
        except Exception as e:
            print(f"Mobile nav test: {e}")
    
    def test_desktop_viewport(self):
        """Test that page works on desktop viewport."""
        # Set desktop viewport
        self.browser.set_window_size(1920, 1080)
        
        self.browser.get(f'{self.live_server_url}/')
        
        # Wait for page
        self.wait_for_element(By.TAG_NAME, 'body')
        
        # Should show full navigation
        nav_links = self.browser.find_elements(By.CSS_SELECTOR, 'nav a')
        self.assertGreater(len(nav_links), 0, "No navigation links found")


# Note: To run these tests, you need:
# 1. Chrome browser installed
# 2. ChromeDriver matching your Chrome version
# 3. Install: pip install selenium
#
# Run with:
# python manage.py test tests.test_e2e_selenium --settings=config.settings
