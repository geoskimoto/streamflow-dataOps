#!/bin/bash
# Load master stations for Western US states
# This script loads USGS streamflow stations for all Western US states

echo "Loading USGS stations for Western US..."
echo "This may take several minutes..."

# Define Western US states
STATES=(
    "MT"  # Montana
    "ID"  # Idaho
    "WY"  # Wyoming
    "CO"  # Colorado
    "NM"  # New Mexico
    "AZ"  # Arizona
    "UT"  # Utah
    "NV"  # Nevada
    "CA"  # California
    "OR"  # Oregon
    "WA"  # Washington
    "AK"  # Alaska
    "HI"  # Hawaii
)

# Load stations for each state
for state in "${STATES[@]}"; do
    echo ""
    echo "===================================="
    echo "Loading stations for $state..."
    echo "===================================="
    python manage.py load_master_stations --state "$state"
    
    if [ $? -eq 0 ]; then
        echo "✓ Successfully loaded stations for $state"
    else
        echo "✗ Error loading stations for $state"
    fi
done

echo ""
echo "===================================="
echo "Loading complete!"
echo "===================================="
echo ""
echo "Summary:"
python manage.py shell -c "
from apps.streamflow.models import MasterStation
from django.db.models import Count

total = MasterStation.objects.count()
print(f'Total stations loaded: {total}')
print()
print('Stations by state:')
by_state = MasterStation.objects.values('state_code').annotate(count=Count('id')).order_by('state_code')
for item in by_state:
    print(f\"  {item['state_code']}: {item['count']} stations\")
"
