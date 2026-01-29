#!/bin/bash
# Production startup script for Streamflow DataOps raster acquisition system

set -e

echo "=================================================="
echo "Streamflow DataOps - Production Startup"
echo "=================================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if Redis is running
echo -e "\n${YELLOW}[1/6] Checking Redis...${NC}"
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Redis is running${NC}"
else
    echo -e "${RED}✗ Redis is not running!${NC}"
    echo "Start Redis with: redis-server"
    echo "Or on Ubuntu: sudo systemctl start redis-server"
    exit 1
fi

# Check if PostgreSQL is running
echo -e "\n${YELLOW}[2/6] Checking PostgreSQL...${NC}"
if pg_isready > /dev/null 2>&1; then
    echo -e "${GREEN}✓ PostgreSQL is running${NC}"
else
    echo -e "${RED}✗ PostgreSQL is not running!${NC}"
    echo "On Ubuntu: sudo systemctl start postgresql"
    exit 1
fi

# Initialize raster datasets if needed
echo -e "\n${YELLOW}[3/6] Checking raster datasets...${NC}"
DATASET_COUNT=$(python manage.py shell -c "from apps.streamflow.models import RasterDataset; print(RasterDataset.objects.count())")

if [ "$DATASET_COUNT" = "0" ]; then
    echo -e "${YELLOW}No datasets found. Running initialization...${NC}"
    python manage.py init_raster_datasets
else
    echo -e "${GREEN}✓ Found $DATASET_COUNT dataset(s)${NC}"
fi

# Run database migrations
echo -e "\n${YELLOW}[4/6] Running database migrations...${NC}"
python manage.py migrate --noinput
echo -e "${GREEN}✓ Migrations complete${NC}"

# Collect static files (for Flower)
echo -e "\n${YELLOW}[5/6] Collecting static files...${NC}"
python manage.py collectstatic --noinput --clear > /dev/null 2>&1
echo -e "${GREEN}✓ Static files collected${NC}"

# Start services in screen/tmux sessions
echo -e "\n${YELLOW}[6/6] Starting services...${NC}"

# Check if tmux is available
if command -v tmux &> /dev/null; then
    SESSION="streamflow"
    
    # Kill existing session if it exists
    tmux kill-session -t $SESSION 2>/dev/null || true
    
    # Create new session
    tmux new-session -d -s $SESSION -n django
    
    # Window 1: Django development server
    tmux send-keys -t $SESSION:django "python manage.py runserver 0.0.0.0:8000" C-m
    
    # Window 2: Celery worker
    tmux new-window -t $SESSION -n worker
    tmux send-keys -t $SESSION:worker "celery -A config worker -l info --concurrency=4" C-m
    
    # Window 3: Celery beat scheduler
    tmux new-window -t $SESSION -n beat
    tmux send-keys -t $SESSION:beat "celery -A config beat -l info" C-m
    
    # Window 4: Flower monitoring
    tmux new-window -t $SESSION -n flower
    tmux send-keys -t $SESSION:flower "celery -A config flower --port=5555" C-m
    
    echo -e "${GREEN}✓ All services started in tmux session '$SESSION'${NC}"
    echo ""
    echo "To attach: tmux attach -t $SESSION"
    echo "To switch windows: Ctrl+B then number (0-3)"
    echo "To detach: Ctrl+B then D"
    echo ""
    
elif command -v screen &> /dev/null; then
    # Fallback to screen
    screen -dmS django python manage.py runserver 0.0.0.0:8000
    screen -dmS celery-worker celery -A config worker -l info --concurrency=4
    screen -dmS celery-beat celery -A config beat -l info
    screen -dmS flower celery -A config flower --port=5555
    
    echo -e "${GREEN}✓ All services started in screen sessions${NC}"
    echo ""
    echo "To list sessions: screen -ls"
    echo "To attach: screen -r [session-name]"
    echo ""
else
    echo -e "${RED}Neither tmux nor screen found. Please install one of them.${NC}"
    echo "Ubuntu: sudo apt-get install tmux"
    echo ""
    echo "Or start services manually:"
    echo "  Terminal 1: python manage.py runserver"
    echo "  Terminal 2: celery -A config worker -l info"
    echo "  Terminal 3: celery -A config beat -l info"
    echo "  Terminal 4: celery -A config flower --port=5555"
    exit 1
fi

# Show access URLs
echo "=================================================="
echo "Services Available At:"
echo "=================================================="
echo ""
echo "🌐 Django Admin:     http://localhost:8000/admin/"
echo "🔌 REST API:         http://localhost:8000/api/v1/"
echo "📊 API Documentation: http://localhost:8000/api/v1/schema/swagger-ui/"
echo "🌸 Flower Monitor:   http://localhost:5555/"
echo ""
echo "=================================================="
echo "Health Check Commands:"
echo "=================================================="
echo ""
echo "Check pull status:      python manage.py shell -c \"from src.acquisition.monitoring_tasks import generate_health_report; print(generate_health_report())\""
echo "Monitor logs:           tail -f logs/celery-worker.log"
echo "View active tasks:      celery -A config inspect active"
echo ""
echo -e "${GREEN}✓ Startup complete!${NC}"
