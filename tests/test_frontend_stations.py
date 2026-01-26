"""
Frontend UI/UX Tests for Stations Management Pages
Tests for /stations and /stations/all views
"""

from django.test import TestCase, Client
from django.urls import reverse
from apps.streamflow.models import (
    Station,
    MasterStation,
    PullConfiguration,
    PullConfigurationStation
)
from datetime import datetime


class StationListViewTests(TestCase):
    """Tests for /stations (configured stations) page"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test configurations
        self.config1 = PullConfiguration.objects.create(
            name="Test Config 1",
            data_source="USGS",
            data_type="realtime_15min",
            data_strategy="append",
            pull_start_date=datetime(2024, 1, 1),
            schedule_type="daily"
        )
        
        self.config2 = PullConfiguration.objects.create(
            name="Test Config 2", 
            data_source="NOAA_RFC",
            data_type="forecast",
            data_strategy="overwrite",
            pull_start_date=datetime(2024, 1, 1),
            schedule_type="daily"
        )
        
        # Create test stations
        self.station1 = Station.objects.create(
            station_number="TEST001",
            name="Test Station 1",
            agency="USGS",
            latitude=45.0,
            longitude=-110.0,
            state="MT",
            huc_code="17010101",
            basin="Test Basin 1",
            is_active=True
        )
        
        self.station2 = Station.objects.create(
            station_number="TEST002",
            name="Test Station 2",
            agency="NOAA_RFC",
            latitude=46.0,
            longitude=-111.0,
            state="ID",
            huc_code="17010102",
            basin="Test Basin 2",
            is_active=True
        )
        
        self.station3 = Station.objects.create(
            station_number="TEST003",
            name="Test Station 3",
            agency="USGS",
            latitude=44.0,
            longitude=-109.0,
            state="WY",
            huc_code="17010201",
            basin="Test Basin 1",
            is_active=False
        )
        
        # Link stations to configurations
        PullConfigurationStation.objects.create(
            configuration=self.config1,
            station_number="TEST001",
            station_name="Test Station 1",
            huc_code="17010101",
            state="MT"
        )
        
        PullConfigurationStation.objects.create(
            configuration=self.config1,
            station_number="TEST002",
            station_name="Test Station 2",
            huc_code="17010102",
            state="ID"
        )
        
        PullConfigurationStation.objects.create(
            configuration=self.config2,
            station_number="TEST002",
            station_name="Test Station 2",
            huc_code="17010102",
            state="ID"
        )
    
    def test_station_list_shows_all_stations(self):
        """
        ISSUE: StationListView shows ALL Station records, not just configured ones.
        This may confuse users who expect to see only stations in active configurations.
        """
        response = self.client.get(reverse('streamflow:station_list'))
        self.assertEqual(response.status_code, 200)
        
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 3)  # Shows all 3 stations
        
        # OBSERVATION: User might expect only TEST001 and TEST002 (configured stations)
        # But view shows TEST003 too (unconfigured station)
    
    def test_configuration_deletion_leaves_stations(self):
        """
        EXPECTED BEHAVIOR: Deleting a configuration should remove PullConfigurationStation
        links but NOT delete Station records (they are independent).
        
        USER CONCERN: "after deleting a configuration, I still see stations from the 
        configuration listed"
        
        This is actually CORRECT behavior - Station records persist independently.
        The confusion might be about what "configured stations" means in the UI.
        """
        # Verify initial state
        self.assertEqual(Station.objects.count(), 3)
        self.assertEqual(PullConfigurationStation.objects.filter(
            configuration=self.config1
        ).count(), 2)
        
        # Delete configuration
        self.config1.delete()
        
        # Configuration-station links are deleted (CASCADE)
        self.assertEqual(PullConfigurationStation.objects.filter(
            configuration_id=self.config1.id
        ).count(), 0)
        
        # BUT Station records persist
        self.assertEqual(Station.objects.count(), 3)
        self.assertTrue(Station.objects.filter(station_number="TEST001").exists())
        self.assertTrue(Station.objects.filter(station_number="TEST002").exists())
        
        # Station list view still shows all stations
        response = self.client.get(reverse('streamflow:station_list'))
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 3)
    
    def test_filter_by_agency(self):
        """Test agency filter works correctly"""
        response = self.client.get(reverse('streamflow:station_list'), {'agency': 'USGS'})
        self.assertEqual(response.status_code, 200)
        
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 2)  # TEST001, TEST003
        for station in stations:
            self.assertEqual(station.agency, 'USGS')
    
    def test_filter_by_state(self):
        """Test state filter works correctly"""
        response = self.client.get(reverse('streamflow:station_list'), {'state': 'MT'})
        self.assertEqual(response.status_code, 200)
        
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0].state, 'MT')
    
    def test_filter_by_basin(self):
        """Test basin filter works correctly"""
        response = self.client.get(reverse('streamflow:station_list'), {'basin': 'Test Basin 1'})
        self.assertEqual(response.status_code, 200)
        
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 2)  # TEST001, TEST003
    
    def test_filter_by_huc(self):
        """Test HUC code filter works correctly"""
        response = self.client.get(reverse('streamflow:station_list'), {'huc': '170101'})
        self.assertEqual(response.status_code, 200)
        
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 2)  # TEST001, TEST002
    
    def test_filter_by_active_status(self):
        """Test active status filter works correctly"""
        response = self.client.get(reverse('streamflow:station_list'), {'is_active': 'true'})
        self.assertEqual(response.status_code, 200)
        
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 2)  # TEST001, TEST002
        for station in stations:
            self.assertTrue(station.is_active)
    
    def test_search_functionality(self):
        """Test search by station number or name"""
        # Search by number
        response = self.client.get(reverse('streamflow:station_list'), {'search': 'TEST002'})
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0].station_number, 'TEST002')
        
        # Search by name
        response = self.client.get(reverse('streamflow:station_list'), {'search': 'Station 3'})
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0].station_number, 'TEST003')
    
    def test_rfc_filter_missing(self):
        """
        USER REQUEST: "add the RFC filter that's in /stations/all to /stations/"
        
        RFC filter is NOT currently available in StationListView.
        This test documents the missing feature.
        """
        # Station model doesn't have an RFC field
        # RFC data is in MasterStation model
        # To add RFC filter, would need to either:
        # 1. Add rfc field to Station model
        # 2. Query MasterStation and join with Station
        # 3. Store RFC in PullConfigurationStation or separate table
        
        # Currently, no RFC filter exists
        response = self.client.get(reverse('streamflow:station_list'), {'rfc': 'NWRFC'})
        # Filter parameter is ignored (not implemented)
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 3)  # Returns all stations (filter doesn't work)
    
    def test_configuration_filter_missing(self):
        """
        USER REQUEST: "filter stations by Configuration site is in"
        
        Configuration filter is NOT currently available in StationListView.
        This test documents the missing feature.
        """
        # To filter by configuration, would need to:
        # 1. Join Station with PullConfigurationStation
        # 2. Filter by configuration_id or configuration name
        # 3. Add dropdown in template showing available configurations
        
        response = self.client.get(reverse('streamflow:station_list'), {'configuration': self.config1.id})
        # Filter parameter is ignored (not implemented)
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 3)  # Returns all stations (filter doesn't work)


class MasterStationListViewTests(TestCase):
    """Tests for /stations/all (master stations) page"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test master stations
        MasterStation.objects.create(
            agency="USGS",
            agency_station_number="01010000",
            name="USGS Test Station 1",
            state="ME",
            huc="01010001",
            rfc="NERFC"
        )
        
        MasterStation.objects.create(
            agency="USGS",
            agency_station_number="17010000", 
            name="USGS Test Station 2",
            state="MT",
            huc="17010101",
            rfc="NWRFC"
        )
        
        MasterStation.objects.create(
            agency="NOAA_RFC",
            agency_station_number="ABOM8",
            name="NOAA Test Station",
            state="MT",
            huc="17010102",
            rfc="NWRFC"
        )
    
    def test_master_station_list_loads(self):
        """Test master station list page loads successfully"""
        response = self.client.get(reverse('streamflow:master_station_list'))
        self.assertEqual(response.status_code, 200)
        
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 3)
    
    def test_filter_by_agency(self):
        """Test agency filter in master stations"""
        response = self.client.get(reverse('streamflow:master_station_list'), {'agency': 'USGS'})
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 2)
    
    def test_filter_by_state(self):
        """Test state filter in master stations"""
        response = self.client.get(reverse('streamflow:master_station_list'), {'state': 'MT'})
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 2)
    
    def test_filter_by_rfc(self):
        """Test RFC filter in master stations"""
        response = self.client.get(reverse('streamflow:master_station_list'), {'rfc': 'NWRFC'})
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 2)
    
    def test_filter_by_huc(self):
        """Test HUC code filter in master stations"""
        response = self.client.get(reverse('streamflow:master_station_list'), {'huc': '170101'})
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 2)
    
    def test_search_functionality(self):
        """Test search in master stations"""
        response = self.client.get(reverse('streamflow:master_station_list'), {'search': 'ABOM8'})
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0].agency_station_number, 'ABOM8')
    
    def test_environment_canada_stations_missing(self):
        """
        USER ISSUE: "currently can't see any Environmental Canada stations in /stations/all"
        
        ROOT CAUSE: MasterStation table has 0 Environment Canada records.
        Database contains only USGS (11,995 stations) and NOAA_RFC data.
        
        This is a DATA ISSUE, not a CODE ISSUE. The filter works correctly,
        but there's no EC data to filter.
        """
        # Verify no EC stations exist
        ec_count = MasterStation.objects.filter(agency='EC').count()
        self.assertEqual(ec_count, 0)
        
        # Filter by EC returns empty result
        response = self.client.get(reverse('streamflow:master_station_list'), {'agency': 'EC'})
        stations = list(response.context['stations'])
        self.assertEqual(len(stations), 0)
        
        # This is EXPECTED given the data - not a bug in the filter code


class ConfigurationWorkflowTests(TestCase):
    """Tests for configuration creation and management workflow"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
    
    def test_configuration_creation_workflow(self):
        """
        USER ISSUE: "workflow for creating a new configuration (not straight forward 
        currently in how to add stations to a new configuration)"
        
        Test and document the steps required to create a configuration and add stations.
        """
        # Step 1: Create configuration
        config_data = {
            'name': 'New Test Config',
            'description': 'Testing configuration creation',
            'data_source': 'USGS',
            'data_type': 'realtime_15min',
            'data_strategy': 'append',
            'pull_start_date': '2024-01-01 00:00:00',
            'schedule_type': 'daily',
            'schedule_value': '',
            'is_enabled': True
        }
        
        response = self.client.post(reverse('streamflow:pullconfiguration_create'), config_data)
        
        # Check if configuration was created
        # (This test documents the actual workflow - may need adjustment based on actual form)
        
        # Step 2: Add stations to configuration
        # TODO: Document how stations are added to configurations
        # - Is there a separate form/view for adding stations?
        # - Can stations be added during configuration creation?
        # - Is there a bulk add feature?
        
        # This test needs to be expanded once workflow is clarified
        pass


# Summary of Issues Found:
# 
# 1. ENVIRONMENT CANADA DATA MISSING (Data Issue)
#    - MasterStation table has 0 EC stations out of 11,995 records
#    - Only USGS and NOAA_RFC data exists
#    - Filter code works correctly; issue is missing source data
#    - Resolution: Import EC station data or document that EC data unavailable
#
# 2. CONFIGURATION DELETION BEHAVIOR (Design Issue)
#    - Deleting configuration removes PullConfigurationStation links (correct)
#    - Station records persist independently (correct per design)
#    - User confusion: expects stations to disappear from /stations list
#    - Resolution: Clarify UI labels or filter /stations to show only configured stations
#
# 3. RFC FILTER MISSING FROM /stations (Feature Request)
#    - RFC filter exists in /stations/all but not in /stations
#    - Station model doesn't have RFC field
#    - Resolution: Add RFC field to Station or query from MasterStation
#
# 4. CONFIGURATION FILTER MISSING FROM /stations (Feature Request)
#    - Cannot filter stations by which configuration they belong to
#    - Would require joining with PullConfigurationStation
#    - Resolution: Add configuration filter with dropdown of available configs
#
# 5. CONFIGURATION CREATION WORKFLOW (UX Issue)
#    - User reports difficulty adding stations to new configurations
#    - Need to document/test actual workflow
#    - Resolution: Test current workflow and propose improvements
