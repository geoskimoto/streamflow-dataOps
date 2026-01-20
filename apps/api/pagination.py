"""Pagination classes for API."""

from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination with configurable page size."""
    
    page_size = 50
    page_size_query_param = 'limit'
    max_page_size = 1000
