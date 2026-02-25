"""Unit tests for the Pulumi infrastructure startup script renderer."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock pulumi modules before importing __main__.py so the module loads
# without requiring a real Pulumi installation or stack context.
_mock_pulumi = MagicMock()
_mock_pulumi_gcp = MagicMock()
_mock_pulumi_docker = MagicMock()

sys.modules["pulumi"] = _mock_pulumi
sys.modules["pulumi_gcp"] = _mock_pulumi_gcp
sys.modules["pulumi_docker"] = _mock_pulumi_docker

# Load __main__.py as a regular module so we can access _render_startup_script.
_main_path = Path(__file__).parent / "__main__.py"
_spec = importlib.util.spec_from_file_location("infra_main", _main_path)
_infra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_infra)

_render_startup_script = _infra._render_startup_script


SAMPLE_ARGS = (
    "my-project-id",
    "my-project-id:us-central1:openemr-sql-abc123",
    "s3cret!",
    "us-central1-docker.pkg.dev/my-project-id/openemr/openemr:latest",
    "us-central1-docker.pkg.dev/my-project-id/openemr/ai-agent:latest",
    "34.56.78.90",
)


class TestRenderStartupScript:
    """Tests for _render_startup_script."""

    def test_returns_string(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert isinstance(result, str)

    def test_starts_with_shebang(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert result.startswith("#!/bin/bash")

    def test_contains_project_id(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert 'PROJECT_ID="my-project-id"' in result

    def test_contains_cloud_sql_connection(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert "my-project-id:us-central1:openemr-sql-abc123" in result

    def test_password_is_base64_encoded(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        expected_b64 = base64.b64encode(b"s3cret!").decode("ascii")
        assert expected_b64 in result
        # Raw password should NOT appear directly in the script
        assert 'DB_PASSWORD="s3cret!"' not in result

    def test_contains_openemr_image(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert (
            "us-central1-docker.pkg.dev/my-project-id/openemr/openemr:latest" in result
        )

    def test_contains_ai_agent_image(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert (
            "us-central1-docker.pkg.dev/my-project-id/openemr/ai-agent:latest"
            in result
        )

    def test_contains_static_ip(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert 'STATIC_IP="34.56.78.90"' in result

    def test_contains_docker_compose_up(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert "docker compose" in result
        assert "up -d" in result

    def test_contains_nginx_config(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert "nginx.conf" in result
        assert "proxy_pass" in result

    def test_contains_secret_fetch_helper(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        assert "fetch_secret" in result
        assert "secretmanager.googleapis.com" in result

    def test_env_file_references_secrets(self) -> None:
        result = _render_startup_script(SAMPLE_ARGS)
        for key in [
            "ANTHROPIC_API_KEY",
            "LANGSMITH_API_KEY",
            "AI_AGENT_API_KEY",
            "OPENEMR_CLIENT_ID",
            "OPENEMR_CLIENT_SECRET",
        ]:
            assert key in result

    def test_different_password_produces_different_output(self) -> None:
        args_alt = (
            "my-project-id",
            "my-project-id:us-central1:openemr-sql-abc123",
            "different-password",
            "us-central1-docker.pkg.dev/my-project-id/openemr/openemr:latest",
            "us-central1-docker.pkg.dev/my-project-id/openemr/ai-agent:latest",
            "34.56.78.90",
        )
        result_a = _render_startup_script(SAMPLE_ARGS)
        result_b = _render_startup_script(args_alt)
        assert result_a != result_b
