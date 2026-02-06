"""Management command to setup spatial extents."""

from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.gis.geos import Polygon

from apps.streamflow.models import SpatialExtent


class Command(BaseCommand):
    """Setup spatial extents for raster data pulls."""
    
    help = 'Setup spatial extents (HUC17, Western US, etc.)'
    
    def handle(self, *args, **options):
        """Execute command."""
        self.stdout.write("Setting up spatial extents...")
        
        extents_created = 0
        
        # HUC 17 (Columbia River Basin)
        huc17_bbox = settings.HUC17_BBOX
        huc17_polygon = Polygon.from_bbox(huc17_bbox)
        
        huc17, created = SpatialExtent.objects.get_or_create(
            name='HUC_17',
            defaults={
                'description': 'Columbia River Basin (HUC 17)',
                'min_lon': huc17_bbox[0],
                'min_lat': huc17_bbox[1],
                'max_lon': huc17_bbox[2],
                'max_lat': huc17_bbox[3],
                'geometry': huc17_polygon
            }
        )
        if created:
            extents_created += 1
            self.stdout.write(self.style.SUCCESS(f"  ✓ Created extent: HUC_17"))
            self.stdout.write(f"    Bounds: {huc17_bbox}")
        else:
            self.stdout.write(f"  - Extent already exists: HUC_17")
        
        # Western US
        western_us_bbox = settings.WESTERN_US_BBOX
        western_us_polygon = Polygon.from_bbox(western_us_bbox)
        
        western_us, created = SpatialExtent.objects.get_or_create(
            name='Western_US',
            defaults={
                'description': 'Western United States (CA, OR, WA, ID, MT, WY, CO, UT, NV, AZ, NM)',
                'min_lon': western_us_bbox[0],
                'min_lat': western_us_bbox[1],
                'max_lon': western_us_bbox[2],
                'max_lat': western_us_bbox[3],
                'geometry': western_us_polygon
            }
        )
        if created:
            extents_created += 1
            self.stdout.write(self.style.SUCCESS(f"  ✓ Created extent: Western_US"))
            self.stdout.write(f"    Bounds: {western_us_bbox}")
        else:
            self.stdout.write(f"  - Extent already exists: Western_US")
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS(
            f"Setup complete: {extents_created} extents created"
        ))
