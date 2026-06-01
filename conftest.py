"""Root pytest configuration for streamflow-dataOps.

Sets up Django settings for tests that use django.test.TestCase or
@pytest.mark.django_db. Tests that use raw SQLAlchemy or do not need
Django are unaffected.
"""

import os


def pytest_configure(config):
    """Configure Django settings before test collection begins."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # Use SQLite for tests — avoids needing a running Postgres instance.
    os.environ.setdefault("DB_ENGINE", "sqlite")
