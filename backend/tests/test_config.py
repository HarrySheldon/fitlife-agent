from backend.config import Settings


def test_database_path_defaults_to_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("SQLITE_DATABASE_PATH", raising=False)
    settings = Settings(data_dir=tmp_path, _env_file=None)

    assert settings.database_path == tmp_path / "fitlife.sqlite3"


def test_database_path_uses_explicit_env_override(tmp_path, monkeypatch):
    database_path = tmp_path / "custom.sqlite3"
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(database_path))
    settings = Settings(
        data_dir=tmp_path / "data",
        _env_file=None,
    )

    assert settings.database_path == database_path


def test_blank_database_path_in_env_file_uses_data_dir_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SQLITE_DATABASE_PATH", raising=False)
    data_dir = tmp_path / "data"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DATA_DIR={data_dir}\n"
        "SQLITE_DATABASE_PATH=\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.database_path == data_dir / "fitlife.sqlite3"


def test_whitespace_database_path_in_env_uses_data_dir_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_DATABASE_PATH", "   ")

    settings = Settings(data_dir=tmp_path, _env_file=None)

    assert settings.database_path == tmp_path / "fitlife.sqlite3"


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
