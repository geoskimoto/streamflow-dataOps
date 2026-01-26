#!/bin/bash

# Frontend Testing Setup Script for StreamFlow DataOps
# This script installs additional tools for comprehensive frontend testing

echo "==================================================================="
echo "StreamFlow DataOps - Frontend Testing Setup"
echo "==================================================================="
echo ""

# Install Python testing dependencies
echo "📦 Installing Python testing packages..."
pip install beautifulsoup4 lxml selenium playwright pytest-django django-debug-toolbar

echo ""
echo "✅ Python packages installed"
echo ""

# Install Playwright browsers (optional - for E2E tests)
read -p "Install Playwright browsers for E2E testing? (y/n): " install_playwright
if [ "$install_playwright" = "y" ]; then
    echo "🌐 Installing Playwright browsers..."
    playwright install chromium
    echo "✅ Playwright browsers installed"
fi

echo ""
echo "==================================================================="
echo "Frontend Testing Tools Installed!"
echo "==================================================================="
echo ""
echo "Available Testing Approaches:"
echo ""
echo "1. Django Template Tests (already installed)"
echo "   - Run: python manage.py test tests.test_frontend_ui"
echo "   - Fast unit tests for templates and views"
echo ""
echo "2. Selenium Tests (now available)"
echo "   - Browser automation testing"
echo "   - Requires Chrome/Firefox browser"
echo ""
echo "3. Playwright Tests (if installed)"
echo "   - Modern browser testing framework"
echo "   - Run: pytest tests/test_e2e_playwright.py"
echo ""
echo "4. Manual Testing Checklist"
echo "   - See tests/FRONTEND_TESTING_CHECKLIST.md"
echo ""
echo "==================================================================="
echo ""
echo "Next Steps:"
echo "1. Run basic tests: python manage.py test tests.test_frontend_ui"
echo "2. Start dev server: python manage.py runserver"
echo "3. Run E2E tests (if needed): pytest tests/test_e2e_*.py"
echo ""
