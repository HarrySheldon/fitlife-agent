from backend.config import Settings


def test_database_schema_defaults_to_none(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)
    settings = Settings(data_dir=tmp_path, _env_file=None)

    assert settings.database_schema is None


def test_database_url_and_schema_use_explicit_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fitlife:fitlife@127.0.0.1:15432/fitlife_test")
    monkeypatch.setenv("DATABASE_SCHEMA", "custom_schema")
    settings = Settings(
        data_dir=tmp_path / "data",
        _env_file=None,
    )

    assert settings.database_url == "postgresql://fitlife:fitlife@127.0.0.1:15432/fitlife_test"
    assert settings.database_schema == "custom_schema"


def test_blank_database_schema_in_env_file_uses_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)
    data_dir = tmp_path / "data"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DATA_DIR={data_dir}\n"
        "DATABASE_SCHEMA=\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.data_dir == data_dir
    assert settings.database_schema is None


def test_whitespace_database_schema_in_env_uses_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_SCHEMA", "   ")

    settings = Settings(data_dir=tmp_path, _env_file=None)

    assert settings.database_schema is None


def test_unrelated_blank_env_value_remains_blank(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKEND_CORS_ORIGINS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("BACKEND_CORS_ORIGINS=\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.backend_cors_origins == ""


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
