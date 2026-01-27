"""Template filters for raster/gridded data."""

from django import template

register = template.Library()


@register.filter
def kelvin_to_fahrenheit(value):
    """
    Convert temperature from Kelvin to Fahrenheit.
    
    Args:
        value: Temperature in Kelvin (numeric)
        
    Returns:
        Temperature in Fahrenheit (float) or None if conversion fails
        
    Example:
        {{ layer.mean_value|kelvin_to_fahrenheit }}°F
    """
    if value is None:
        return None
    
    try:
        kelvin = float(value)
        # Convert K to F: (K - 273.15) * 9/5 + 32
        fahrenheit = (kelvin - 273.15) * 9/5 + 32
        return round(fahrenheit, 1)
    except (ValueError, TypeError):
        return None


@register.filter
def kelvin_to_celsius(value):
    """
    Convert temperature from Kelvin to Celsius.
    
    Args:
        value: Temperature in Kelvin (numeric)
        
    Returns:
        Temperature in Celsius (float) or None if conversion fails
        
    Example:
        {{ layer.mean_value|kelvin_to_celsius }}°C
    """
    if value is None:
        return None
    
    try:
        kelvin = float(value)
        # Convert K to C: K - 273.15
        celsius = kelvin - 273.15
        return round(celsius, 1)
    except (ValueError, TypeError):
        return None


@register.filter
def format_file_size(bytes_value):
    """
    Format bytes to human-readable file size.
    
    Args:
        bytes_value: Size in bytes (numeric)
        
    Returns:
        Formatted string like "1.5 MB" or None if conversion fails
        
    Example:
        {{ layer.file_size|format_file_size }}
    """
    if bytes_value is None:
        return None
    
    try:
        bytes_value = float(bytes_value)
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        
        return f"{bytes_value:.1f} PB"
    except (ValueError, TypeError):
        return None
