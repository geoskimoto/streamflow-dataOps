"""Tests for ResidCast settings integration."""
from django.test import TestCase
from django.conf import settings


class ResidCastSettingsTest(TestCase):
    def test_residcast_api_base_setting_exists(self):
        self.assertTrue(hasattr(settings, "RESIDCAST_API_BASE"))
        self.assertIsInstance(settings.RESIDCAST_API_BASE, str)
        self.assertTrue(settings.RESIDCAST_API_BASE.startswith("http"))

    def test_residcast_api_token_setting_exists(self):
        self.assertTrue(hasattr(settings, "RESIDCAST_API_TOKEN"))
        self.assertIsInstance(settings.RESIDCAST_API_TOKEN, str)
