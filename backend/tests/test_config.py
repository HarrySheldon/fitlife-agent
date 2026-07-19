from backend.config import Settings


def test_settings_ignore_non_backend_values_in_shared_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=test\n"
        "FRONTEND_PORT=3000\n"
        "VITE_API_BASE_URL=http://127.0.0.1:8000\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.app_env == "test"
