"""Tests for ai_agent.config — Settings model and get_settings() cache."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ai_agent.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Ensure get_settings cache is cleared before and after each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------


class TestSettingsModel:
    def test_default_values(self):
        """Settings has expected default values."""
        s = Settings(_env_file=None)
        assert s.model_name == "claude-sonnet-4-5"
        assert s.db_host == "mysql"
        assert s.db_port == 3306
        assert s.openemr_username == "admin"
        assert s.api_key == ""
        assert s.langsmith_tracing is True
        assert s.langsmith_project == "openemr-agent"

    def test_env_var_override(self, monkeypatch):
        """Environment variables override default values."""
        monkeypatch.setenv("MODEL_NAME", "test-model")
        s = Settings(_env_file=None)
        assert s.model_name == "test-model"

    def test_type_coercion(self, monkeypatch):
        """String env vars are coerced to the correct type."""
        monkeypatch.setenv("DB_PORT", "5432")
        s = Settings(_env_file=None)
        assert s.db_port == 5432
        assert isinstance(s.db_port, int)


# ---------------------------------------------------------------------------
# get_settings() cache
# ---------------------------------------------------------------------------


class TestGetSettings:
    def test_returns_settings_instance(self):
        result = get_settings()
        assert isinstance(result, Settings)

    def test_cached_returns_same_object(self):
        """Two calls return the same cached object."""
        a = get_settings()
        b = get_settings()
        assert a is b

    def test_cache_clear_returns_new_object(self):
        """After cache_clear(), a new object is returned."""
        a = get_settings()
        get_settings.cache_clear()
        b = get_settings()
        assert a is not b

    def test_reads_env_vars(self, monkeypatch):
        """get_settings() picks up environment variables."""
        monkeypatch.setenv("MODEL_NAME", "from-env")
        result = get_settings()
        assert result.model_name == "from-env"

    def test_env_file_branch_with_file(self):
        """When .env file exists, Settings is constructed with _env_file."""
        with patch("os.path.isfile", return_value=True):
            result = get_settings()
            assert isinstance(result, Settings)

    def test_env_file_branch_without_file(self):
        """When .env file doesn't exist, Settings is constructed without _env_file."""
        with patch("os.path.isfile", return_value=False):
            result = get_settings()
            assert isinstance(result, Settings)
