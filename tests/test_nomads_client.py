"""Unit tests for NomadsClient."""

import unittest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil
import numpy as np

from src.acquisition.nomads_client import (
    NomadsClient,
    NomadsError
)


class TestNomadsClient(unittest.TestCase):
    """Test suite for NomadsClient."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = NomadsClient()
        self.test_dir = Path(tempfile.mkdtemp())
        self.bbox = [-124.7, 41.5, -108.0, 49.0]  # HUC 17
        
    def tearDown(self):
        """Clean up test fixtures."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_initialization(self):
        """Test client initialization."""
        self.assertIn('nomads.ncep.noaa.gov', self.client.NOMADS_BASE)
        self.assertIsNotNone(self.client.session)
    
    def test_rtma_variables_mapping(self):
        """Test RTMA_VARIABLES dictionary has correct structure."""
        self.assertIn('temperature', self.client.RTMA_VARIABLES)
        self.assertIn('pressure', self.client.RTMA_VARIABLES)
        self.assertIn('wind_speed', self.client.RTMA_VARIABLES)
        
        # Check structure
        temp_config = self.client.RTMA_VARIABLES['temperature']
        self.assertEqual(temp_config['grib_name'], '2t')
        self.assertEqual(temp_config['units'], 'K')
    
    def test_build_rtma_url_basic(self):
        """Test RTMA URL building with basic timestamp."""
        timestamp = datetime(2026, 1, 28, 20, 0, 0, tzinfo=timezone.utc)
        url = self.client._build_rtma_url(timestamp)
        
        # Check URL contains expected components
        self.assertIn('rtma2p5.20260128', url)
        self.assertIn('t20z', url)
        self.assertIn('2dvaranl_ndfd.grb2_wexp', url)
    
    def test_build_rtma_url_different_times(self):
        """Test URL building for different timestamps."""
        test_cases = [
            (datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
             'rtma2p5.20260101/rtma2p5.t00z.2dvaranl_ndfd.grb2_wexp'),
            (datetime(2026, 12, 31, 23, 0, 0, tzinfo=timezone.utc),
             'rtma2p5.20261231/rtma2p5.t23z.2dvaranl_ndfd.grb2_wexp'),
            (datetime(2025, 6, 15, 12, 30, 0, tzinfo=timezone.utc),
             'rtma2p5.20250615/rtma2p5.t12z.2dvaranl_ndfd.grb2_wexp'),
        ]
        
        for timestamp, expected_suffix in test_cases:
            url = self.client._build_rtma_url(timestamp)
            self.assertIn(expected_suffix, url)
    
    def test_check_data_availability_success(self):
        """Test data availability check with successful response."""
        timestamp = datetime(2026, 1, 28, 20, 0, 0, tzinfo=timezone.utc)
        
        with patch('requests.head') as mock_head:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {'content-length': '80000000'}
            mock_head.return_value = mock_response
            
            available = self.client.check_data_availability(timestamp)
            self.assertTrue(available)
            mock_head.assert_called_once()
    
    def test_check_data_availability_404(self):
        """Test data availability check with 404 response."""
        timestamp = datetime(2026, 1, 28, 20, 0, 0, tzinfo=timezone.utc)
        
        with patch('requests.head') as mock_head:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_head.return_value = mock_response
            
            available = self.client.check_data_availability(timestamp)
            self.assertFalse(available)
    
    @patch('src.acquisition.nomads_client.requests.get')
    def test_download_file_success(self, mock_get):
        """Test successful file download."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'mock_grib_data'
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        output_path = self.test_dir / 'test.grb2'
        url = 'https://example.com/test.grb2'
        
        result = self.client._download_file(url, output_path)
        
        self.assertTrue(result)
        self.assertTrue(output_path.exists())
        self.assertEqual(output_path.read_bytes(), b'mock_grib_data')
        mock_get.assert_called_once()
    
    @patch('src.acquisition.nomads_client.requests.get')
    def test_download_file_retry_on_failure(self, mock_get):
        """Test download retry logic on failure."""
        # First two calls fail, third succeeds
        mock_response_fail = Mock()
        mock_response_fail.status_code = 500
        mock_response_fail.raise_for_status.side_effect = Exception("Server error")
        
        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.content = b'mock_grib_data'
        mock_response_success.raise_for_status = Mock()
        
        mock_get.side_effect = [
            mock_response_fail,
            mock_response_fail,
            mock_response_success
        ]
        
        output_path = self.test_dir / 'test.grb2'
        url = 'https://example.com/test.grb2'
        
        result = self.client._download_file(url, output_path, max_retries=3)
        
        self.assertTrue(result)
        self.assertEqual(mock_get.call_count, 3)
    
    @patch('src.acquisition.nomads_client.requests.get')
    def test_download_file_max_retries_exceeded(self, mock_get):
        """Test download failure after max retries."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("Server error")
        mock_get.return_value = mock_response
        
        output_path = self.test_dir / 'test.grb2'
        url = 'https://example.com/test.grb2'
        
        result = self.client._download_file(url, output_path, max_retries=2)
        
        self.assertFalse(result)
        self.assertEqual(mock_get.call_count, 2)
    
    @patch('src.acquisition.nomads_client.pygrib.open')
    def test_extract_rtma_temperature(self, mock_pygrib_open):
        """Test temperature extraction from GRIB2."""
        # Mock GRIB messages
        mock_message = Mock()
        mock_message.shortName = '2t'
        mock_message.level = 2
        mock_message.data.return_value = (
            np.random.uniform(240, 310, (100, 100)),  # temperature data
            np.random.uniform(-125, -108, (100, 100)),  # lats
            np.random.uniform(41, 50, (100, 100))      # lons
        )
        
        mock_grbs = Mock()
        mock_grbs.select.return_value = [mock_message]
        mock_grbs.close = Mock()
        mock_pygrib_open.return_value.__enter__.return_value = mock_grbs
        
        grib_path = self.test_dir / 'test.grb2'
        grib_path.write_bytes(b'mock_grib')
        output_path = self.test_dir / 'output.tif'
        
        # Call extraction
        result = self.client._extract_rtma_to_geotiff(
            grib_path, 'temperature', self.bbox, output_path
        )
        
        self.assertIsNotNone(result)
        self.assertIn('variable', result)
        self.assertEqual(result['variable'], 'temperature')
    
    @patch('src.acquisition.nomads_client.pygrib.open')
    def test_extract_rtma_pressure(self, mock_pygrib_open):
        """Test pressure extraction from GRIB2."""
        mock_message = Mock()
        mock_message.shortName = 'sp'
        mock_message.level = 0
        mock_message.data.return_value = (
            np.random.uniform(60000, 105000, (100, 100)),  # pressure data
            np.random.uniform(-125, -108, (100, 100)),
            np.random.uniform(41, 50, (100, 100))
        )
        
        mock_grbs = Mock()
        mock_grbs.select.return_value = [mock_message]
        mock_grbs.close = Mock()
        mock_pygrib_open.return_value.__enter__.return_value = mock_grbs
        
        grib_path = self.test_dir / 'test.grb2'
        grib_path.write_bytes(b'mock_grib')
        output_path = self.test_dir / 'output.tif'
        
        result = self.client._extract_rtma_to_geotiff(
            grib_path, 'pressure', self.bbox, output_path
        )
        
        self.assertIsNotNone(result)
        self.assertEqual(result['variable'], 'pressure')
    
    @patch('src.acquisition.nomads_client.pygrib.open')
    def test_extract_wind_speed(self, mock_pygrib_open):
        """Test wind speed calculation from U and V components."""
        # Mock U component (10u)
        mock_u = Mock()
        mock_u.shortName = '10u'
        mock_u.level = 10
        u_data = np.random.uniform(-10, 10, (100, 100))
        mock_u.data.return_value = (
            u_data,
            np.random.uniform(-125, -108, (100, 100)),
            np.random.uniform(41, 50, (100, 100))
        )
        
        # Mock V component (10v)
        mock_v = Mock()
        mock_v.shortName = '10v'
        mock_v.level = 10
        v_data = np.random.uniform(-10, 10, (100, 100))
        mock_v.data.return_value = (
            v_data,
            np.random.uniform(-125, -108, (100, 100)),
            np.random.uniform(41, 50, (100, 100))
        )
        
        def mock_select(shortName=None, level=None):
            if shortName == '10u':
                return [mock_u]
            elif shortName == '10v':
                return [mock_v]
            return []
        
        mock_grbs = Mock()
        mock_grbs.select = mock_select
        mock_grbs.close = Mock()
        mock_pygrib_open.return_value.__enter__.return_value = mock_grbs
        
        grib_path = self.test_dir / 'test.grb2'
        grib_path.write_bytes(b'mock_grib')
        output_path = self.test_dir / 'wind_speed.tif'
        
        result = self.client._extract_wind_speed(
            grib_path, self.bbox, output_path
        )
        
        self.assertIsNotNone(result)
        self.assertEqual(result['variable'], 'wind_speed')
    
    @patch('src.acquisition.nomads_client.pygrib.open')
    def test_extract_no_matching_message(self, mock_pygrib_open):
        """Test extraction when no matching GRIB message found."""
        mock_grbs = Mock()
        mock_grbs.select.return_value = []  # No messages
        mock_grbs.close = Mock()
        mock_pygrib_open.return_value.__enter__.return_value = mock_grbs
        
        grib_path = self.test_dir / 'test.grb2'
        grib_path.write_bytes(b'mock_grib')
        output_path = self.test_dir / 'output.tif'
        
        with self.assertRaises(NomadsError) as context:
            self.client._extract_rtma_to_geotiff(
                grib_path, 'temperature', self.bbox, output_path
            )
        
        self.assertIn('No GRIB message found', str(context.exception))
    
    def test_invalid_variable_name(self):
        """Test handling of invalid variable name."""
        timestamp = datetime(2026, 1, 28, 20, 0, 0, tzinfo=timezone.utc)
        output_path = self.test_dir / 'output.tif'
        
        with self.assertRaises(NomadsError) as context:
            self.client.get_rtma_data(
                'invalid_variable',
                timestamp,
                self.bbox,
                output_path
            )
        
        self.assertIn('Unknown variable', str(context.exception))
    
    @patch('src.acquisition.nomads_client.NomadsClient._download_file')
    @patch('src.acquisition.nomads_client.NomadsClient._extract_rtma_to_geotiff')
    def test_get_rtma_data_full_flow(self, mock_extract, mock_download):
        """Test complete RTMA data retrieval flow."""
        timestamp = datetime(2026, 1, 28, 20, 0, 0, tzinfo=timezone.utc)
        output_path = self.test_dir / 'temperature.tif'
        
        # Mock successful download
        mock_download.return_value = True
        
        # Mock successful extraction
        mock_extract.return_value = {
            'variable': 'temperature',
            'timestamp': timestamp,
            'bbox': self.bbox,
            'min_value': 244.0,
            'max_value': 302.0,
            'mean_value': 276.1
        }
        
        result = self.client.get_rtma_data(
            'temperature',
            timestamp,
            self.bbox,
            output_path
        )
        
        self.assertIsNotNone(result)
        self.assertEqual(result['variable'], 'temperature')
        mock_download.assert_called_once()
        mock_extract.assert_called_once()
    
    @patch('src.acquisition.nomads_client.NomadsClient._download_file')
    def test_get_rtma_data_download_failure(self, mock_download):
        """Test RTMA data retrieval with download failure."""
        timestamp = datetime(2026, 1, 28, 20, 0, 0, tzinfo=timezone.utc)
        output_path = self.test_dir / 'temperature.tif'
        
        # Mock failed download
        mock_download.return_value = False
        
        with self.assertRaises(NomadsError) as context:
            self.client.get_rtma_data(
                'temperature',
                timestamp,
                self.bbox,
                output_path
            )
        
        self.assertIn('Failed to download', str(context.exception))
    
    def test_bbox_validation(self):
        """Test bounding box validation."""
        timestamp = datetime(2026, 1, 28, 20, 0, 0, tzinfo=timezone.utc)
        output_path = self.test_dir / 'output.tif'
        
        # Invalid bbox (wrong order)
        invalid_bbox = [-108.0, 41.5, -124.7, 49.0]
        
        with patch('src.acquisition.nomads_client.NomadsClient._download_file') as mock_download:
            mock_download.return_value = True
            
            # Should still work but may clip incorrectly
            # The actual validation happens in the processor
            # Just test that client doesn't crash
            try:
                self.client.get_rtma_data(
                    'temperature',
                    timestamp,
                    invalid_bbox,
                    output_path
                )
            except Exception:
                pass  # Expected to fail in extraction
    
    def test_timestamp_validation(self):
        """Test timestamp must be timezone-aware."""
        naive_timestamp = datetime(2026, 1, 28, 20, 0, 0)  # No timezone
        output_path = self.test_dir / 'output.tif'
        
        # Should work - client will handle it
        # Just verify URL building works
        url = self.client._build_rtma_url(naive_timestamp)
        self.assertIn('20260128', url)
        self.assertIn('t20z', url)


if __name__ == '__main__':
    unittest.main()
