# Frontend UI/UX Testing Guide

## Overview
This document describes the testing strategy and tools for frontend testing in StreamFlow DataOps.

---

## Testing Approaches

### 1. **Django Template Tests** (Fast, No Browser Required)
- **Location:** `tests/test_frontend_ui.py`
- **Purpose:** Test template rendering, context data, HTML structure
- **Speed:** Very fast (< 1 second per test)
- **Best for:** Quick validation of template logic and content

**Run:**
```bash
python manage.py test tests.test_frontend_ui -v 2
```

**What it tests:**
- ✅ Templates render without errors
- ✅ Correct data appears in context
- ✅ HTML structure and Bootstrap classes present
- ✅ Forms have required fields and labels
- ✅ Navigation links exist
- ✅ Accessibility basics (labels, alt text)

---

### 2. **Selenium E2E Tests** (Browser Automation)
- **Location:** `tests/test_e2e_selenium.py`
- **Purpose:** Simulate real user interactions in browser
- **Speed:** Slower (2-5 seconds per test)
- **Best for:** Testing JavaScript, AJAX, user workflows

**Setup:**
```bash
pip install selenium beautifulsoup4 lxml
# Download ChromeDriver matching your Chrome version
# From: https://chromedriver.chromium.org/
```

**Run:**
```bash
python manage.py test tests.test_e2e_selenium -v 2
```

**What it tests:**
- ✅ Real browser interactions (click, type, submit)
- ✅ JavaScript functionality
- ✅ AJAX requests and responses
- ✅ Form submissions and validation
- ✅ Navigation flows
- ✅ Responsive design at different screen sizes

---

### 3. **Manual Testing Checklist**
Use this checklist when manually testing the frontend:

#### **Dashboard Page**
- [ ] Page loads within 2 seconds
- [ ] All stat cards display correct numbers
- [ ] Recent logs table shows data
- [ ] Action buttons are visible and clickable
- [ ] Links navigate to correct pages
- [ ] No JavaScript console errors

#### **Configuration List Page**
- [ ] All configurations are displayed
- [ ] Status badges show correctly (enabled/disabled)
- [ ] Filter dropdown works
- [ ] Create button navigates to form
- [ ] View/Edit/Trigger buttons work
- [ ] Pagination works (if >50 configs)

#### **Configuration Detail Page**
- [ ] Configuration details displayed correctly
- [ ] Stations table shows all stations
- [ ] Add Stations button works
- [ ] Remove station icons work
- [ ] Manual trigger button submits form
- [ ] Recent logs are displayed
- [ ] Edit button navigates to form

#### **Master Station List Page**
- [ ] Stations load (may take 2-3 seconds for 10,000+)
- [ ] Agency filter dropdown populated
- [ ] State filter dropdown populated
- [ ] **RFC filter dropdown populated** (new)
- [ ] HUC filter input works
- [ ] Search input filters stations
- [ ] Filters can be combined
- [ ] Clear filters button resets all
- [ ] Pagination shows correct page numbers
- [ ] Sorting works (if implemented)

#### **Configuration Create/Edit Form**
- [ ] All fields are present and labeled
- [ ] **Data Source dropdown includes NOAA_RFC** (new)
- [ ] **Data Type dropdown includes forecast** (new)
- [ ] Help text appears below fields
- [ ] Required field validation works
- [ ] Date/time picker works
- [ ] Form submits successfully
- [ ] Success message displays
- [ ] Redirects to correct page

#### **Add Stations to Config Page**
- [ ] Station search loads initially
- [ ] **RFC filter appears** (new)
- [ ] **Agency filter includes NOAA_RFC** (new)
- [ ] State and HUC filters work
- [ ] Search returns results
- [ ] Checkboxes work
- [ ] "Select All" works (if implemented)
- [ ] "Load More" button works
- [ ] Add button submits selected stations
- [ ] Already-added stations marked/disabled

#### **Logs Page**
- [ ] Logs display in table
- [ ] Status column shows icons/badges
- [ ] Duration calculated correctly
- [ ] Configuration filter works
- [ ] Status filter works
- [ ] Date range filter works
- [ ] Pagination works
- [ ] Click log row navigates to detail

#### **Responsive Design**
- [ ] Mobile (375px): Navigation collapses, cards stack
- [ ] Tablet (768px): 2-column layout works
- [ ] Desktop (1920px): Full layout displays
- [ ] Touch targets ≥ 44px on mobile
- [ ] Text readable without zooming

#### **Accessibility**
- [ ] All images have alt text
- [ ] Form inputs have labels
- [ ] Buttons have descriptive text
- [ ] Keyboard navigation works (Tab key)
- [ ] Focus indicators visible
- [ ] Color contrast sufficient (use browser devtools)

#### **Browser Compatibility**
Test in:
- [ ] Chrome/Chromium
- [ ] Firefox
- [ ] Safari (if on Mac)
- [ ] Edge

---

## Common Frontend Issues to Check

### Issue 1: **Broken URL References**
**Symptom:** Links show 404 or NoReverseMatch errors

**Check:**
```bash
# Search for URL patterns in templates
grep -r "{% url" apps/streamflow/templates/
```

**Fix:** Ensure all `{% url %}` tags include proper namespace:
```django
❌ {% url 'configuration_list' %}
✅ {% url 'streamflow:configuration_list' %}
```

### Issue 2: **Missing Static Files**
**Symptom:** No CSS/JS, broken layout

**Check:**
```bash
python manage.py collectstatic --dry-run
```

**Fix:**
```bash
python manage.py collectstatic --noinput
```

### Issue 3: **Template Syntax Errors**
**Symptom:** TemplateSyntaxError in browser

**Check:**
```bash
# Validate templates
python manage.py check --deploy
```

### Issue 4: **JavaScript Errors**
**Symptom:** Features don't work, console shows errors

**Check:** Browser DevTools → Console tab

**Common fixes:**
- Ensure jQuery loads before custom JS
- Check AJAX endpoint URLs are correct
- Verify CSRF token included in POST requests

### Issue 5: **AJAX Station Search Not Working**
**Symptom:** "Load More" button doesn't work

**Check:**
```bash
# Test AJAX endpoint manually
curl "http://localhost:8000/streamflow/ajax/station-search/?q=test&limit=100"
```

**Fix:** Check view returns valid JSON:
```python
return JsonResponse({
    'stations': [...],
    'has_more': True,
    'total': 1000
})
```

### Issue 6: **Form Validation Errors Not Displaying**
**Symptom:** Form submits but no error messages

**Check:**
```html
<!-- In template, ensure form errors are displayed -->
{% if form.errors %}
    <div class="alert alert-danger">
        {{ form.errors }}
    </div>
{% endif %}
```

---

## Running All Tests

### Quick Test (Fast)
```bash
# Run template tests only (< 10 seconds)
python manage.py test tests.test_frontend_ui
```

### Comprehensive Test (Includes Browser)
```bash
# Run all frontend tests (1-2 minutes)
python manage.py test tests.test_frontend_ui tests.test_e2e_selenium
```

### Test with Coverage
```bash
pip install coverage
coverage run --source='apps' manage.py test tests.test_frontend_ui
coverage report
coverage html  # Creates htmlcov/index.html
```

---

## Testing New Features

When adding new NOAA RFC features, test:

1. **RFC Filtering:**
   ```python
   # In tests/test_frontend_ui.py
   def test_rfc_filter_present(self):
       response = self.client.get(reverse('streamflow:master_station_list'))
       self.assertContains(response, 'RFC')
       self.assertContains(response, 'NWRFC')
   ```

2. **Forecast Data Type:**
   ```python
   def test_forecast_data_type_option(self):
       response = self.client.get(reverse('streamflow:configuration_create'))
       self.assertContains(response, 'forecast')
   ```

3. **NOAA Stations Display:**
   ```python
   def test_noaa_stations_show_rfc_code(self):
       MasterStation.objects.create(
           station_number='ABCD1',
           station_name='Test',
           agency='NOAA_RFC',
           rfc_code='NWRFC'
       )
       response = self.client.get(reverse('streamflow:master_station_list'))
       self.assertContains(response, 'NWRFC')
   ```

---

## Debugging Failed Tests

### Get More Details
```bash
# Verbose output
python manage.py test tests.test_frontend_ui -v 3

# Keep test database for inspection
python manage.py test --keepdb tests.test_frontend_ui

# Run specific test
python manage.py test tests.test_frontend_ui.DashboardUITests.test_dashboard_stat_cards_present
```

### Take Screenshots (Selenium)
```python
# In test method
try:
    # ... test code ...
except Exception as e:
    self.browser.save_screenshot('/tmp/test_failure.png')
    raise
```

### Check HTML Output
```python
def test_something(self):
    response = self.client.get(url)
    # Print HTML for debugging
    print(response.content.decode())
    
    # Or save to file
    with open('/tmp/test_output.html', 'w') as f:
        f.write(response.content.decode())
```

---

## Performance Testing

### Page Load Times
```bash
# Use curl to test response times
time curl "http://localhost:8000/streamflow/stations/all/"

# With Apache Bench
ab -n 100 -c 10 http://localhost:8000/
```

### Database Query Count
```python
from django.test.utils import override_settings
from django.db import connection

@override_settings(DEBUG=True)
def test_query_count(self):
    with self.assertNumQueries(5):  # Expect 5 queries max
        response = self.client.get(url)
```

---

## Continuous Integration

### GitHub Actions Example
```yaml
# .github/workflows/frontend-tests.yml
name: Frontend Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.11
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install beautifulsoup4 lxml selenium
      - name: Run tests
        run: |
          python manage.py test tests.test_frontend_ui
```

---

## Resources

- [Django Testing Documentation](https://docs.djangoproject.com/en/4.2/topics/testing/)
- [Selenium Python Docs](https://selenium-python.readthedocs.io/)
- [Bootstrap 5 Documentation](https://getbootstrap.com/docs/5.0/)
- [Web Accessibility Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)

---

## Summary

**Use Django template tests for:**
- ✅ Quick validation during development
- ✅ CI/CD pipelines
- ✅ Template logic and context testing

**Use Selenium E2E tests for:**
- ✅ Critical user workflows
- ✅ JavaScript/AJAX functionality
- ✅ Pre-release validation

**Use manual testing for:**
- ✅ Visual design review
- ✅ UX flow evaluation
- ✅ Cross-browser compatibility
- ✅ Accessibility audit
