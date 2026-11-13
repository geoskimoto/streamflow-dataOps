"""Pins the settings the USGS Water Data client and rolling re-fetch depend on."""

from django.conf import settings


def test_waterdata_base_default():
    assert settings.USGS_WATERDATA_BASE == (
        "https://api.waterdata.usgs.gov/ogcapi/v1"
    )


def test_api_key_is_a_string_never_none():
    # An absent key is legal — the API answers unauthenticated requests but
    # returns HTTP 429 under load — so the contract is only "always a str",
    # letting the client do `if self.api_key:`. This deliberately does NOT
    # assert a key is present, so the suite still passes without .env.
    assert isinstance(settings.USGS_API_KEY, str)


def test_refetch_window_is_180_days():
    assert settings.OBSERVATION_REFETCH_WINDOW_DAYS == 180
