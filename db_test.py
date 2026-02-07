from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SELECT version();")
    version = cursor.fetchone()[0]
    print(f"  ✓ Database connected: {version.split(',')[0]}")

            # Check for PostGIS
    cursor.execute("SELECT PostGIS_Version();")
    postgis_version = cursor.fetchone()[0]
    print(f"  ✓ PostGIS extension: {postgis_version}")


