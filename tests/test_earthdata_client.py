"""Unit tests for EarthDataClient."""

import os
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import numpy as np

from src.acquisition.earthdata_client import (
    EarthDataClient,
    EarthDataError,
    EarthDataAuthenticationError
)


@pytest.fixture
def mock_env_credentials(monkeypatch):
    """Mock environment credentials."""
    monkeypatch.setenv('EARTHDATA_USERNAME', 'test_user')
    monkeypatch.setenv('EARTHDATA_PASSWORD', 'test_pass')


@pytest.fixture
def mock_earthaccess():
    """Mock earthaccess library."""
    with patch('src.acquisition.earthdata_client.earthaccess') as mock:
        mock_auth = Mock()
        mock_auth.authenticated = True
        mock.login.return_value = mock_auth
        yield mock


@pytest.fixture
def client(mock_env_credentials, mock_earthaccess):
    """Create test client."""
    return EarthDataClient()


class TestAuthentication:
    """Test authentication methods."""
    
    def test_init_with_env_credentials(self, mock_env_credentials, mock_earthaccess):
        """Test initialization with environment variables."""
        client = EarthDataClient()
        
        assert client.username == 'test_user'
        assert client.password == 'test_pass'
        assert client.authenticated is True
        mock_earthaccess.login.assert_called_once()
    
    def test_init_with_explicit_credentials(self, mock_earthaccess):
        """Test initialization with explicit credentials."""
        client = EarthDataClient(username='explicit_user', password='explicit_pass')
        
        assert client.username == 'explicit_user'
        assert client.password == 'explicit_pass'
        assert client.authenticated is True
    
    def test_init_without_credentials(self, mock_earthaccess):
        """Test initialization fails without credentials."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EarthDataAuthenticationError):
                EarthDataClient()
    
    def test_auth_failure(self, mock_env_credentials):
        """Test authentication failure handling."""
        with patch('src.acquisition.earthdata_client.earthaccess') as mock_ea:
            mock_ea.login.side_effect = Exception("Auth failed")
            
            with pytest.raises(EarthDataAuthenticationError):
                EarthDataClient()


class TestGranuleSearch:
    """Test granule search functionality."""
    
    def test_search_granules_success(self, client, mock_earthaccess):
        """Test successful granule search."""
        # Mock search results
        mock_granule = Mock()
        mock_granule.data_links.return_value = ['https://example.com/data.h5']
        mock_earthaccess.search_data.return_value = [mock_granule]
        
        results = client.search_granules(
            collection_id='SPL4SMGP_008',
            bbox=[-124.7, 41.5, -108.0, 49.0],
            start_date=datetime(2024, 5, 31),
            end_date=datetime(2024, 6, 1),
            limit=10
        )
        
        assert len(results) == 1
        assert results[0] == mock_granule
        
        # Verify search_data was called with correct parameters
        call_args = mock_earthaccess.search_data.call_args
        assert call_args.kwargs['short_name'] == 'SPL4SMGP_008'
        assert call_args.kwargs['count'] == 10
    
    def test_search_granules_empty_results(self, client, mock_earthaccess):
        """Test search with no results."""
        mock_earthaccess.search_data.return_value = []
        
        results = client.search_granules(
            collection_id='SPL4SMGP_008',
            bbox=[-124.7, 41.5, -108.0, 49.0],
            start_date=datetime(2024, 5, 31),
            end_date=datetime(2024, 6, 1)
        )
        
        assert results == []
    
    def test_search_granules_not_authenticated(self):
        """Test search fails when not authenticated."""
        with patch('src.acquisition.earthdata_client.earthaccess') as mock_ea:
            mock_auth = Mock()
            mock_auth.authenticated = False
            mock_ea.login.return_value = mock_auth
            
            with patch.dict(os.environ, {'EARTHDATA_USERNAME': 'test', 'EARTHDATA_PASSWORD': 'test'}):
                client = EarthDataClient()
                
                with pytest.raises(EarthDataAuthenticationError):
                    client.search_granules('TEST', [-180, -90, 180, 90], datetime.now(), datetime.now())


class TestDownloadGranule:
    """Test granule download functionality."""
    
    def test_download_success(self, client, mock_earthaccess, tmp_path):
        """Test successful download."""
        # Mock download
        test_file = tmp_path / 'test_data.h5'
        test_file.write_text('mock data')
        mock_earthaccess.download.return_value = [str(test_file)]
        
        mock_granule = Mock()
        result = client.download_granule(mock_granule, tmp_path / 'output')
        
        assert result.exists()
        assert result.name == 'test_data.h5'
        mock_earthaccess.download.assert_called_once()
    
    def test_download_retry_on_failure(self, client, mock_earthaccess, tmp_path):
        """Test retry logic on download failure."""
        # First two attempts fail, third succeeds
        test_file = tmp_path / 'test_data.h5'
        test_file.write_text('mock data')
        
        mock_earthaccess.download.side_effect = [
            Exception("Network error"),
            Exception("Timeout"),
            [str(test_file)]
        ]
        
        mock_granule = Mock()
        
        with patch('time.sleep'):  # Skip actual sleep
            result = client.download_granule(mock_granule, tmp_path / 'output', max_retries=3)
        
        assert result.exists()
        assert mock_earthaccess.download.call_count == 3
    
    def test_download_max_retries_exceeded(self, client, mock_earthaccess, tmp_path):
        """Test failure after max retries."""
        mock_earthaccess.download.side_effect = Exception("Network error")
        mock_granule = Mock()
        
        with patch('time.sleep'):
            with pytest.raises(EarthDataError, match="after 3 attempts"):
                client.download_granule(mock_granule, tmp_path / 'output', max_retries=3)
        
        assert mock_earthaccess.download.call_count == 3


class TestDataAvailability:
    """Test data availability checking."""
    
    def test_check_smap_availability(self, client, mock_earthaccess):
        """Test SMAP data availability check."""
        mock_granule = Mock()
        mock_earthaccess.search_data.return_value = [mock_granule]
        
        available = client.check_data_availability(
            dataset='SMAP_SPL4',
            start_date=datetime(2024, 5, 31),
            end_date=datetime(2024, 6, 1),
            bbox=[-124.7, 41.5, -108.0, 49.0]
        )
        
        assert available is True
        assert 'granule_count' in available
        assert available['granule_count'] == 1
    
    def test_check_gpm_availability(self, client, mock_earthaccess):
        """Test GPM data availability check."""
        mock_earthaccess.search_data.return_value = []
        
        available = client.check_data_availability(
            dataset='GPM_IMERG',
            start_date=datetime(2024, 5, 31),
            end_date=datetime(2024, 6, 1),
            bbox=[-124.7, 41.5, -108.0, 49.0]
        )
        
        assert available is False
    
    def test_check_availability_invalid_dataset(self, client):
        """Test availability check with invalid dataset."""
        with pytest.raises(ValueError, match="Unknown dataset"):
            client.check_data_availability(
                dataset='INVALID',
                start_date=datetime.now(),
                end_date=datetime.now(),
                bbox=[-180, -90, 180, 90]
            )


class TestCollectionMapping:
    """Test collection ID and DAAC mappings."""
    
    def test_collection_ids_exist(self, client):
        """Test that all expected collection IDs are defined."""
        assert 'SMAP_SPL4' in client.collections
        assert 'GPM_IMERG' in client.collections
        assert 'MODIS_LST_TERRA' in client.collections
        assert 'MODIS_LST_AQUA' in client.collections
    
    def test_daac_mappings_exist(self, client):
        """Test that DAAC mappings are defined."""
        assert 'SMAP_SPL4' in client.daacs
        assert 'GPM_IMERG' in client.daacs
        assert 'MODIS_LST_TERRA' in client.daacs
    
    def test_collection_id_values(self, client):
        """Test correct collection ID values."""
        assert client.collections['SMAP_SPL4'] == 'SPL4SMGP_008'
        assert client.collections['GPM_IMERG'] == 'GPM_3IMERGDF_07'
        assert client.collections['MODIS_LST_TERRA'] == 'MOD11A1_061'
        assert client.collections['MODIS_LST_AQUA'] == 'MYD11A1_061'


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_search_api_error(self, client, mock_earthaccess):
        """Test handling of API errors during search."""
        mock_earthaccess.search_data.side_effect = Exception("CMR API error")
        
        with pytest.raises(EarthDataError, match="Search failed"):
            client.search_granules(
                'SPL4SMGP_008',
                [-180, -90, 180, 90],
                datetime.now(),
                datetime.now()
            )
    
    def test_download_not_authenticated(self, mock_earthaccess):
        """Test download fails when not authenticated."""
        with patch('src.acquisition.earthdata_client.earthaccess') as mock_ea:
            mock_auth = Mock()
            mock_auth.authenticated = False
            mock_ea.login.return_value = mock_auth
            
            with patch.dict(os.environ, {'EARTHDATA_USERNAME': 'test', 'EARTHDATA_PASSWORD': 'test'}):
                client = EarthDataClient()
                
                with pytest.raises(EarthDataAuthenticationError):
                    client.download_granule(Mock(), Path('/tmp'))


@pytest.mark.parametrize("dataset,expected_collection", [
    ('SMAP_SPL4', 'SPL4SMGP_008'),
    ('GPM_IMERG', 'GPM_3IMERGDF_07'),
    ('MODIS_LST_TERRA', 'MOD11A1_061'),
    ('MODIS_LST_AQUA', 'MYD11A1_061'),
])
def test_dataset_to_collection_mapping(client, dataset, expected_collection):
    """Test dataset name to collection ID mapping."""
    assert client.collections[dataset] == expected_collection
