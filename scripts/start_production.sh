#!/bin/bash
# Production startup script for Streamflow DataOps
# Uses systemd services (gunicorn, celery-worker, celery-beat)

set -e

echo "=================================================="
echo "Streamflow DataOps - Production Startup"
echo "=================================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PROJECT_DIR="/root/proj/streamflow-dataOps/streamflow-dataOps"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"

# Check if Redis is running
echo -e "\n${YELLOW}[1/7] Checking Redis...${NC}"
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Redis is running${NC}"
else
    echo -e "${RED}✗ Redis is not running!${NC}"
    echo "Start Redis with: sudo systemctl start redis-server"
    exit 1
fi

# Check if PostgreSQL is running
echo -e "\n${YELLOW}[2/7] Checking PostgreSQL...${NC}"
if pg_isready > /dev/null 2>&1; then
    echo -e "${GREEN}✓ PostgreSQL is running${NC}"
else
    echo -e "${RED}✗ PostgreSQL is not running!${NC}"
    echo "Start with: sudo systemctl start postgresql"
    exit 1
fi

# Initialize raster datasets if needed
echo -e "\n${YELLOW}[3/7] Checking raster datasets...${NC}"
DATASET_COUNT=$($VENV_PYTHON "$PROJECT_DIR/manage.py" shell -c "from apps.streamflow.models import RasterDataset; print(RasterDataset.objects.count())")

if [ "$DATASET_COUNT" = "0" ]; then
    echo -e "${YELLOW}No datasets found. Running initialization...${NC}"
    $VENV_PYTHON "$PROJECT_DIR/manage.py" init_raster_datasets
else
    echo -e "${GREEN}✓ Found $DATASET_COUNT dataset(s)${NC}"
fi

# Run database migrations
echo -e "\n${YELLOW}[4/7] Running database migrations...${NC}"
$VENV_PYTHON "$PROJECT_DIR/manage.py" migrate --noinput
echo -e "${GREEN}✓ Migrations complete${NC}"

# Collect static files
echo -e "\n${YELLOW}[5/7] Collecting static files...${NC}"
$VENV_PYTHON "$PROJECT_DIR/manage.py" collectstatic --noinput --clear > /dev/null 2>&1
echo -e "${GREEN}✓ Static files collected${NC}"

# Create log directories
echo -e "\n${YELLOW}[6/7] Ensuring log directories exist...${NC}"
mkdir -p /var/log/gunicorn /var/log/celery
echo -e "${GREEN}✓ Log directories ready${NC}"

# Start and enable systemd services
echo -e "\n${YELLOW}[7/7] Starting systemd services...${NC}"

systemctl daemon-reload

# Stop existing services (ignore errors if not running)
systemctl stop gunicorn celery-worker celery-beat 2>/dev/null || true

# Start services
systemctl start gunicorn
echo -e "${GREEN}✓ gunicorn started${NC}"

systemctl start celery-worker
echo -e "${GREEN}✓ celery-worker started${NC}"

systemctl start celery-beat
echo -e "${GREEN}✓ celery-beat started${NC}"

# Enable for boot
systemctl enable gunicorn celery-worker celery-beat
echo -e "${GREEN}✓ All services enabled for boot${NC}"

# Reload nginx to pick up any config changes
systemctl reload nginx
echo -e "${GREEN}✓ nginx reloaded${NC}"

# Show service status
echo ""
echo "=================================================="
echo "Service Status:"
echo "=================================================="
echo ""
systemctl --no-pager status gunicorn celery-worker celery-beat | head -30

# Show access URLs
echo ""
echo "=================================================="
echo "Services Available At:"
echo "=================================================="
echo ""
echo "Web App:          https://streamflowops.3rdplaces.io/"
echo "Django Admin:     https://streamflowops.3rdplaces.io/admin/"
echo "REST API:         https://streamflowops.3rdplaces.io/api/v1/"
echo "API Docs:         https://streamflowops.3rdplaces.io/api/v1/docs/"
echo ""
echo "=================================================="
echo "Management Commands:"
echo "=================================================="
echo ""
echo "Status:           sudo systemctl status gunicorn celery-worker celery-beat"
echo "Restart all:      sudo systemctl restart gunicorn celery-worker celery-beat"
echo "View logs:        sudo journalctl -u gunicorn -f"
echo "                  sudo journalctl -u celery-worker -f"
echo "                  sudo journalctl -u celery-beat -f"
echo ""
echo -e "${GREEN}✓ Startup complete!${NC}"
