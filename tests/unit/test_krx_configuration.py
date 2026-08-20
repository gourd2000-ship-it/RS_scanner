from app.core.config import Settings


def test_krx_auth_key_is_an_optional_runtime_setting():
    settings = Settings(_env_file=None, KRX_AUTH_KEY="test-secret")

    assert settings.krx_auth_key == "test-secret"


def test_krx_auth_key_defaults_to_none_when_not_configured():
    settings = Settings(_env_file=None)

    assert settings.krx_auth_key is None


def test_krx_shadow_ingestion_is_disabled_until_explicitly_enabled():
    assert Settings(_env_file=None).krx_shadow_ingestion_enabled is False
    assert Settings(_env_file=None, KRX_SHADOW_INGESTION_ENABLED=True).krx_shadow_ingestion_enabled is True
