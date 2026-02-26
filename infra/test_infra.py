"""Unit tests for the startup script renderer."""

from __future__ import annotations

import base64

from startup import render_startup_script

SAMPLE_KWARGS = {
    "project_id": "my-project-id",
    "cloud_sql_connection": "my-project-id:us-central1:openemr-sql-abc123",
    "db_password": "s3cret!",
    "openemr_image": "us-central1-docker.pkg.dev/my-project-id/openemr/openemr:latest",
    "ai_agent_image": "us-central1-docker.pkg.dev/my-project-id/openemr/ai-agent:latest",
    "static_ip": "34.56.78.90",
}


class TestRenderStartupScript:
    """Tests for render_startup_script."""

    def test_returns_string(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert isinstance(result, str)

    def test_starts_with_shebang(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert result.startswith("#!/bin/bash")

    def test_contains_project_id(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert 'PROJECT_ID="my-project-id"' in result

    def test_contains_cloud_sql_connection(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert "my-project-id:us-central1:openemr-sql-abc123" in result

    def test_password_is_base64_encoded(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        expected_b64 = base64.b64encode(b"s3cret!").decode("ascii")
        assert expected_b64 in result
        # Raw password should NOT appear directly in the script
        assert 'DB_PASSWORD="s3cret!"' not in result

    def test_contains_openemr_image(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert (
            "us-central1-docker.pkg.dev/my-project-id/openemr/openemr:latest" in result
        )

    def test_contains_ai_agent_image(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert (
            "us-central1-docker.pkg.dev/my-project-id/openemr/ai-agent:latest"
            in result
        )

    def test_contains_static_ip(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert 'STATIC_IP="34.56.78.90"' in result

    def test_contains_docker_compose_up(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert "docker compose" in result
        assert "up -d" in result

    def test_contains_nginx_config(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert "nginx.conf" in result
        assert "proxy_pass" in result

    def test_contains_secret_fetch_helper(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        assert "fetch_secret" in result
        assert "secretmanager.googleapis.com" in result

    def test_env_file_references_secrets(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        for key in [
            "ANTHROPIC_API_KEY",
            "LANGSMITH_API_KEY",
            "AI_AGENT_API_KEY",
            "OPENEMR_CLIENT_ID",
            "OPENEMR_CLIENT_SECRET",
        ]:
            assert key in result

    def test_different_password_produces_different_output(self) -> None:
        kwargs_alt = {**SAMPLE_KWARGS, "db_password": "different-password"}
        result_a = render_startup_script(**SAMPLE_KWARGS)
        result_b = render_startup_script(**kwargs_alt)
        assert result_a != result_b

    def test_no_unreplaced_placeholders(self) -> None:
        result = render_startup_script(**SAMPLE_KWARGS)
        for marker in [
            "__PROJECT_ID__",
            "__CLOUD_SQL_CONNECTION__",
            "__DB_PASSWORD_B64__",
            "__OPENEMR_IMAGE__",
            "__AI_AGENT_IMAGE__",
            "__STATIC_IP__",
        ]:
            assert marker not in result, f"Unreplaced placeholder: {marker}"
