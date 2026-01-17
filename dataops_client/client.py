"""
DataOps API Client

Main client class for interacting with the StreamFlow DataOps REST API.
"""

import requests
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timedelta
import logging
from urllib.parse import urljoin
import time
from functools import wraps

from .models import Station, DischargeObservation, PullConfiguration, PaginatedResponse
from .exceptions import (
    DataOpsAPIError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    TimeoutError,
    ServerError,
)


logger = logging.getLogger(__name__)


def retry_on_failure(max_retries=3, backoff_factor=2):
    """Decorator to retry failed requests with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except (TimeoutError, ServerError) as e:
                    retries += 1
                    if retries >= max_retries:
                        raise
                    wait_time = backoff_factor ** retries
                    logger.warning(f"Request failed, retrying in {wait_time}s... ({retries}/{max_retries})")
                    time.sleep(wait_time)
            return func(*args, **kwargs)
        return wrapper
    return decorator


class DataOpsClient:
    """
    Client for the StreamFlow DataOps REST API.
    
    Example:
        >>> client = DataOpsClient(base_url="http://localhost:8000", api_token="your-token")
        >>> stations = client.get_stations(state="CO", limit=10)
        >>> data = client.get_station_data("09070500", start_date="2026-01-01", end_date="2026-01-17")
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_token: Optional[str] = None,
        timeout: int = 60,
        verify_ssl: bool = True,
        cache_enabled: bool = True,
        cache_ttl: int = 300,  # 5 minutes
    ):
        """
        Initialize DataOps API Client.
        
        Args:
            base_url: Base URL of the DataOps API (e.g., "https://api.dataops.example.com")
            api_token: Optional JWT token or API key for authentication
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            cache_enabled: Enable client-side response caching
            cache_ttl: Cache time-to-live in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        
        self._session = requests.Session()
        self._cache: Dict[str, tuple] = {}  # {url: (data, timestamp)}
        
        # Set default headers
        self._session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        
        if self.api_token:
            self._session.headers.update({
                'Authorization': f'Bearer {self.api_token}'
            })
        
        logger.info(f"DataOps client initialized for {self.base_url}")
    
    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get data from cache if available and not expired."""
        if not self.cache_enabled:
            return None
        
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self.cache_ttl:
                logger.debug(f"Cache hit for {key}")
                return data
            else:
                del self._cache[key]
        
        return None
    
    def _set_cache(self, key: str, data: Any):
        """Store data in cache."""
        if self.cache_enabled:
            self._cache[key] = (data, time.time())
    
    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        logger.info("Cache cleared")
    
    @retry_on_failure(max_retries=3)
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Make HTTP request to API.
        
        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint path (e.g., "/api/v1/stations/")
            params: Query parameters
            data: Request body data
            use_cache: Whether to use cache for GET requests
        
        Returns:
            Response JSON data
        
        Raises:
            DataOpsAPIError: On API errors
        """
        url = urljoin(self.base_url, endpoint)
        
        # Check cache for GET requests
        if method == 'GET' and use_cache:
            cache_key = f"{url}?{str(params)}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data is not None:
                return cached_data
        
        try:
            logger.debug(f"{method} {url} params={params}")
            
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                json=data,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            
            # Handle different status codes
            if response.status_code == 200 or response.status_code == 201:
                response_data = response.json()
                
                # Cache GET responses
                if method == 'GET' and use_cache:
                    self._set_cache(cache_key, response_data)
                
                return response_data
            
            elif response.status_code == 204:
                return {}  # No content
            
            elif response.status_code == 400:
                raise ValidationError(
                    f"Validation error: {response.text}",
                    status_code=400,
                    response=response
                )
            
            elif response.status_code == 401:
                raise AuthenticationError(
                    "Authentication failed. Check your API token.",
                    status_code=401,
                    response=response
                )
            
            elif response.status_code == 404:
                raise NotFoundError(
                    f"Resource not found: {url}",
                    status_code=404,
                    response=response
                )
            
            elif response.status_code == 429:
                raise RateLimitError(
                    "Rate limit exceeded. Please try again later.",
                    status_code=429,
                    response=response
                )
            
            elif 500 <= response.status_code < 600:
                raise ServerError(
                    f"Server error ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                    response=response
                )
            
            else:
                raise DataOpsAPIError(
                    f"Unexpected status code {response.status_code}: {response.text}",
                    status_code=response.status_code,
                    response=response
                )
        
        except requests.exceptions.Timeout:
            raise TimeoutError(f"Request to {url} timed out after {self.timeout}s")
        
        except requests.exceptions.RequestException as e:
            raise DataOpsAPIError(f"Request failed: {str(e)}")
    
    # ===== Station Operations =====
    
    def get_stations(
        self,
        agency: Optional[str] = None,
        state: Optional[str] = None,
        huc_code: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        **kwargs
    ) -> PaginatedResponse:
        """
        Get list of stations with optional filters.
        
        Args:
            agency: Filter by agency (USGS, EC, NOAA)
            state: Filter by state code (e.g., "CO", "CA")
            huc_code: Filter by HUC code
            is_active: Filter by active status
            search: Search in station_number or station_name
            limit: Number of results per page (default: 100)
            offset: Offset for pagination
            **kwargs: Additional query parameters
        
        Returns:
            PaginatedResponse containing list of Station objects
        """
        params = {'limit': limit, 'offset': offset}
        
        if agency:
            params['agency'] = agency
        if state:
            params['state'] = state
        if huc_code:
            params['huc_code'] = huc_code
        if is_active is not None:
            params['is_active'] = is_active
        if search:
            params['search'] = search
        
        params.update(kwargs)
        
        data = self._request('GET', '/api/v1/stations/', params=params)
        return PaginatedResponse.from_dict(data, result_class=Station)
    
    def get_station(self, station_number: str) -> Station:
        """
        Get single station by station number.
        
        Args:
            station_number: Station identifier (e.g., "09070500")
        
        Returns:
            Station object
        """
        data = self._request('GET', f'/api/v1/stations/{station_number}/')
        return Station.from_dict(data)
    
    def get_station_data(
        self,
        station_number: str,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        data_type: Optional[str] = None,
        format: str = 'json',
        use_cache: bool = False,  # Don't cache time series data by default
    ) -> List[DischargeObservation]:
        """
        Get discharge observations for a station.
        
        Args:
            station_number: Station identifier
            start_date: Start date (YYYY-MM-DD or datetime object)
            end_date: End date (YYYY-MM-DD or datetime object)
            data_type: Filter by data type (realtime_15min, daily_mean)
            format: Response format (json or csv)
            use_cache: Whether to cache the response
        
        Returns:
            List of DischargeObservation objects
        """
        params = {
            'start_date': self._format_date(start_date),
            'end_date': self._format_date(end_date),
            'format': format,
        }
        
        if data_type:
            params['data_type'] = data_type
        
        data = self._request(
            'GET',
            f'/api/v1/stations/{station_number}/data/',
            params=params,
            use_cache=use_cache
        )
        
        # Handle paginated or direct list response
        if isinstance(data, dict) and 'results' in data:
            results = data['results']
        else:
            results = data
        
        return [DischargeObservation.from_dict(obs) for obs in results]
    
    def get_station_statistics(
        self,
        station_number: str,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        aggregation: str = 'daily',
    ) -> Dict[str, Any]:
        """
        Get statistical summary for a station.
        
        Args:
            station_number: Station identifier
            start_date: Start date
            end_date: End date
            aggregation: Aggregation level (daily, monthly, yearly)
        
        Returns:
            Dictionary with min, max, mean, percentiles
        """
        params = {
            'start_date': self._format_date(start_date),
            'end_date': self._format_date(end_date),
            'aggregation': aggregation,
        }
        
        return self._request(
            'GET',
            f'/api/v1/stations/{station_number}/statistics/',
            params=params
        )
    
    # ===== Configuration Operations =====
    
    def get_configurations(
        self,
        is_enabled: Optional[bool] = None,
        data_source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> PaginatedResponse:
        """
        Get list of pull configurations.
        
        Args:
            is_enabled: Filter by enabled status
            data_source: Filter by data source (USGS, EC, NOAA)
            limit: Number of results per page
            offset: Offset for pagination
        
        Returns:
            PaginatedResponse containing PullConfiguration objects
        """
        params = {'limit': limit, 'offset': offset}
        
        if is_enabled is not None:
            params['is_enabled'] = is_enabled
        if data_source:
            params['data_source'] = data_source
        
        data = self._request('GET', '/api/v1/configurations/', params=params)
        return PaginatedResponse.from_dict(data, result_class=PullConfiguration)
    
    def get_configuration(self, config_id: int) -> Dict[str, Any]:
        """
        Get single configuration with details.
        
        Args:
            config_id: Configuration ID
        
        Returns:
            Configuration dictionary with stations and execution history
        """
        return self._request('GET', f'/api/v1/configurations/{config_id}/')
    
    def execute_configuration(self, config_id: int) -> Dict[str, Any]:
        """
        Trigger immediate execution of a configuration.
        
        Args:
            config_id: Configuration ID
        
        Returns:
            Dictionary with task_id and status
        """
        return self._request('POST', f'/api/v1/configurations/{config_id}/execute/')
    
    # ===== Execution Log Operations =====
    
    def get_logs(
        self,
        configuration_id: Optional[int] = None,
        status: Optional[str] = None,
        start_date: Optional[Union[str, datetime]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> PaginatedResponse:
        """
        Get execution logs.
        
        Args:
            configuration_id: Filter by configuration ID
            status: Filter by status (running, success, failed)
            start_date: Filter by start date
            limit: Number of results per page
            offset: Offset for pagination
        
        Returns:
            PaginatedResponse with log entries
        """
        params = {'limit': limit, 'offset': offset}
        
        if configuration_id:
            params['configuration_id'] = configuration_id
        if status:
            params['status'] = status
        if start_date:
            params['start_time__gte'] = self._format_date(start_date)
        
        data = self._request('GET', '/api/v1/logs/', params=params)
        return PaginatedResponse.from_dict(data)
    
    # ===== Batch Operations =====
    
    def batch_query_data(
        self,
        station_numbers: List[str],
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        data_type: Optional[str] = None,
    ) -> Dict[str, List[DischargeObservation]]:
        """
        Query data for multiple stations in a single request.
        
        Args:
            station_numbers: List of station identifiers
            start_date: Start date
            end_date: End date
            data_type: Optional data type filter
        
        Returns:
            Dictionary mapping station_number to list of observations
        """
        payload = {
            'stations': station_numbers,
            'start_date': self._format_date(start_date),
            'end_date': self._format_date(end_date),
        }
        
        if data_type:
            payload['data_type'] = data_type
        
        response = self._request('POST', '/api/v1/batch/data-query/', data=payload, use_cache=False)
        
        # Parse response into station-keyed dictionary
        result = {}
        for station_num, observations in response.items():
            result[station_num] = [
                DischargeObservation.from_dict(obs) for obs in observations
            ]
        
        return result
    
    # ===== Utility Methods =====
    
    @staticmethod
    def _format_date(date: Union[str, datetime]) -> str:
        """Format date for API request."""
        if isinstance(date, datetime):
            return date.strftime('%Y-%m-%d')
        return date
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check API health status.
        
        Returns:
            Dictionary with status and version info
        """
        try:
            return self._request('GET', '/api/v1/health/', use_cache=False)
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    
    def __repr__(self):
        return f"DataOpsClient(base_url='{self.base_url}')"
