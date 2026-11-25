from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from backend.application.use_cases.delete_account import DeleteAccount
from backend.application.use_cases.export_account_data import ExportAccountData
from backend.config import PROJECT_ROOT, get_settings
from backend.domain.errors import ApplicationError
from backend.domain.model_connection import ModelConnection, ModelConnectionWorkspace
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.auth.file_identity_repository import hash_password
from backend.infrastructure.auth.sqlite_identity_repository import SQLiteIdentityRepository
from backend.infrastructure.migration.legacy_account_state import LegacyAccountStateMigrator
from backend.infrastructure.repositories.sqlite_profile_target_repository import SQLiteProfileTargetRepository
from backend.infrastructure.settings.fernet_cipher import FernetCredentialCipher
from backend.infrastructure.settings.sqlite_model_connection_repository import SQLiteModelConnectionRepository
from backend.infrastructure.settings.sqlite_user_preferences_repository import SQLiteUserPreferencesRepository
from backend.infrastructure.sqlite.backup import backup_database, restore_database_backup, verify_database_backup
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
from backend.infrastructure.startup import run_startup
from backend.schemas import AuthenticatedPrincipal


def test_legacy_account_state_migrates_idempotently_preserving_originals_and_ciphertext(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    user1 = "a" * 32
    user2 = "b" * 32
    key = Fernet.generate_key().decode()
    cipher = FernetCredentialCipher(key)
    enc_secret_1 = cipher.encrypt("sk-legacy-one-9876")
    enc_secret_2 = cipher.encrypt("sk-legacy-two-4321")

    legacy_users = [
        {
            "user_id": user1,
            "username": "legacyone",
            "email": "one@example.com",
            "phone": None,
            "display_name": "Legacy One",
            "password_hash": hash_password("password123"),
            "created_at": "2026-07-01T00:00:00+00:00",
            "token_version": 2,
        },
        {
            "user_id": user2,
            "username": "legacytwo",
            "email": None,
            "phone": "13800138000",
            "display_name": "Legacy Two",
            "password_hash": hash_password("password456"),
            "created_at": "2026-07-02T00:00:00+00:00",
        },
    ]
    users_bytes = json.dumps(legacy_users, indent=2).encode("utf-8")
    (data_dir / "users.json").write_bytes(users_bytes)

    u1_dir = data_dir / "users" / user1
    u2_dir = data_dir / "users" / user2
    u1_dir.mkdir(parents=True)
    u2_dir.mkdir(parents=True)

    pref1_bytes = json.dumps({"language": "zh-CN", "unit_system": "metric", "timezone": "Asia/Shanghai"}).encode("utf-8")
    (u1_dir / "preferences.json").write_bytes(pref1_bytes)

    # v2 workspace format for user1, v1 flat format for user2
    model1_bytes = json.dumps({
        "schema_version": 2,
        "revision": 3,
        "active": {
            "provider": "custom",
            "provider_id": "custom",
            "protocol": "chat_completions",
            "base_url": "https://models.example.com/v1",
            "model": "model-v2",
            "encrypted_api_key": enc_secret_1,
            "api_key_hint": "********9876",
            "enabled": True,
            "test_status": "success",
        },
        "draft": None,
    }).encode("utf-8")
    model2_bytes = json.dumps({
        "provider": "openai",
        "protocol": "responses",
        "model": "model-v1",
        "encrypted_api_key": enc_secret_2,
        "api_key_hint": "********4321",
        "enabled": False,
    }).encode("utf-8")
    (u1_dir / "model_connection.json").write_bytes(model1_bytes)
    (u2_dir / "model_connection.json").write_bytes(model2_bytes)

    db = SQLiteDatabase(data_dir / "fitlife.sqlite3")
    summary_first = run_startup(db, data_dir)
    assert summary_first.status == "ready"
    assert summary_first.schema_version == 15

    # Original files remain untouched as read-only backup.
    assert (data_dir / "users.json").read_bytes() == users_bytes
    assert (u1_dir / "preferences.json").read_bytes() == pref1_bytes
    assert (u1_dir / "model_connection.json").read_bytes() == model1_bytes
    assert (u2_dir / "model_connection.json").read_bytes() == model2_bytes

    identities = SQLiteIdentityRepository(db, data_dir)
    prefs_repo = SQLiteUserPreferencesRepository(db, data_dir)
    models_repo = SQLiteModelConnectionRepository(db, data_dir)

    assert identities.authenticate("legacyone", "password123").user_id == user1
    assert identities.authenticate("13800138000", "password456").user_id == user2
    assert identities.get_token_version(user1) == 2
    assert identities.get_token_version(user2) == 0
    assert prefs_repo.get(user1) == UserPreferences(language="zh-CN", unit_system="metric", timezone="Asia/Shanghai")

    ws1 = models_repo.get_workspace(user1)
    assert ws1.revision == 3
    assert ws1.active is not None
    assert ws1.active.encrypted_api_key == enc_secret_1
    assert cipher.decrypt(ws1.active.encrypted_api_key) == "sk-legacy-one-9876"

    ws2 = models_repo.get_workspace(user2)
    assert ws2.active is not None
    assert ws2.active.model == "model-v1"
    assert ws2.active.encrypted_api_key == enc_secret_2

    # Ensure plaintext API keys are never written to SQLite text columns.
    with db.connection() as conn:
        raw_rows = conn.execute("SELECT active_json, draft_json FROM model_connections").fetchall()
        serialized = " ".join((row["active_json"] or "") + (row["draft_json"] or "") for row in raw_rows)
        assert "sk-legacy-one-9876" not in serialized
        assert "sk-legacy-two-4321" not in serialized

    # Second startup run & direct migrator replay are idempotent.
    summary_second = run_startup(db, data_dir)
    assert summary_second.status == "ready"
    replay = LegacyAccountStateMigrator(db, data_dir).migrate()
    assert replay.status == "skipped"


def test_sqlite_repositories_support_optimistic_concurrency_export_and_deletion(tmp_path):
    data_dir = tmp_path / "sqlite-only"
    db = SQLiteDatabase(data_dir / "fitlife.sqlite3")
    run_migrations(db, RECORDS_MIGRATIONS)

    identities = SQLiteIdentityRepository(db, data_dir)
    prefs_repo = SQLiteUserPreferencesRepository(db, data_dir)
    models_repo = SQLiteModelConnectionRepository(db, data_dir)

    u1 = identities.register("alice", None, None, "password123", "Alice")
    u2 = identities.register("bob", None, None, "password456", "Bob")
    prefs_repo.save(u1.user_id, UserPreferences(language="zh-CN", unit_system="metric", timezone="Asia/Shanghai"))
    prefs_repo.save(u2.user_id, UserPreferences(language="en-US", unit_system="imperial", timezone="UTC"))

    cipher = FernetCredentialCipher(Fernet.generate_key().decode())
    ws_next = models_repo.compare_and_set(
        u1.user_id,
        expected_revision=0,
        workspace=ModelConnectionWorkspace(
            revision=1,
            active=ModelConnection(
                provider="custom",
                provider_id="custom",
                protocol="chat_completions",
                base_url="https://models.example.com/v1",
                model="m-active",
                encrypted_api_key=cipher.encrypt("sk-export-secret"),
                api_key_hint="********cret",
                enabled=True,
                test_status="success",
            ),
            draft=ModelConnection(
                provider="openai",
                provider_id="openai",
                protocol="responses",
                model="m-draft",
                encrypted_api_key=cipher.encrypt("sk-draft-secret"),
                api_key_hint="********cret",
                enabled=False,
            ),
        ),
    )
    assert ws_next.revision == 1
    models_repo.save(u2.user_id, ModelConnection(model="bob-model", encrypted_api_key=cipher.encrypt("sk-bob")))

    # Stale expected_revision triggers 409 MODEL_CONFIGURATION_CONFLICT.
    with pytest.raises(ApplicationError) as exc_info:
        models_repo.compare_and_set(
            u1.user_id,
            expected_revision=0,
            workspace=ModelConnectionWorkspace(revision=1),
        )
    assert exc_info.value.code == "MODEL_CONFIGURATION_CONFLICT"
    assert exc_info.value.status_code == 409

    # Export works cleanly even without users.json, preferences.json, or model_connection.json on disk.
    assert not (data_dir / "users.json").exists()
    archive_bytes = ExportAccountData(
        data_dir,
        identities,
        models_repo,
        user_preferences=prefs_repo,
    ).execute(u1.user_id)
    with zipfile.ZipFile(BytesIO(archive_bytes)) as zf:
        names = zf.namelist()
        assert {"identity.json", "preferences.json", "model-connection.json", "model-connection-draft.json"} <= set(names)
        payload_blob = b"\n".join(zf.read(name) for name in names)
        assert b"sk-export-secret" not in payload_blob
        assert b"sk-draft-secret" not in payload_blob
        assert b"encrypted_api_key" not in payload_blob
        assert b"api_key_hint" not in payload_blob
        exported_model = json.loads(zf.read("model-connection.json"))
        assert exported_model["model"] == "m-active"
        assert exported_model["api_key_configured"] is True

    # Deleting user1 removes only user1's SQLite rows while keeping user2 intact.
    DeleteAccount(
        data_dir,
        identities,
        SQLiteProfileTargetRepository(db),
        user_preferences=prefs_repo,
        model_connections=models_repo,
    ).execute(
        AuthenticatedPrincipal(user=u1, token_version=0),
        password="password123",
        confirmation="DELETE",
    )
    assert identities.get_by_id(u1.user_id) is None
    assert prefs_repo.get(u1.user_id) is None
    assert models_repo.has_stored_workspace(u1.user_id) is False

    assert identities.get_by_id(u2.user_id) == u2
    assert prefs_repo.get(u2.user_id) is not None
    assert models_repo.get(u2.user_id).model == "bob-model"


def test_backup_verify_restore_and_cli_manifest(tmp_path):
    data_dir = tmp_path / "data"
    db_path = data_dir / "fitlife.sqlite3"
    db = SQLiteDatabase(db_path)
    run_migrations(db, RECORDS_MIGRATIONS)
    identities = SQLiteIdentityRepository(db, data_dir)
    models_repo = SQLiteModelConnectionRepository(db, data_dir)
    u = identities.register("backup-user", None, None, "password123", "Backup User")
    models_repo.save(u.user_id, ModelConnection(model="gpt-5.5", encrypted_api_key="cipher-val"))

    backup_path = tmp_path / "snapshots" / "snapshot.sqlite3"
    created = backup_database(db, backup_path)
    assert created.integrity_check == "ok"
    assert created.schema_version == 15
    assert created.user_count == 1
    assert created.model_connection_count == 1

    verified = verify_database_backup(backup_path)
    assert verified.checksum == created.checksum
    assert verified.schema_version == 15

    restored_path = tmp_path / "restored" / "fitlife.sqlite3"
    restored = restore_database_backup(backup_path, restored_path)
    assert restored.integrity_check == "ok"
    assert restored.user_count == 1
    assert restored.model_connection_count == 1

    # CLI --manifest and --verify-only never print any secret key value.
    secret_marker = Fernet.generate_key().decode()
    cli_backup = tmp_path / "cli" / "fitlife-cli.sqlite3"
    env = {
        **os.environ,
        "DATA_DIR": str(data_dir),
        "SQLITE_DATABASE_PATH": str(db_path),
        "SETTINGS_ENCRYPTION_KEY": secret_marker,
    }
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "backup_sqlite.py"), "--output", str(cli_backup), "--manifest"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    output_json = json.loads(proc.stdout)
    assert output_json["integrity_check"] == "ok"
    assert output_json["schema_version"] == 15
    assert output_json["user_count"] == 1
    assert output_json["model_connection_count"] == 1
    assert "SETTINGS_ENCRYPTION_KEY" in output_json["encryption_key_notice"]
    assert secret_marker not in proc.stdout
    manifest_file = Path(output_json["manifest_path"])
    assert manifest_file.is_file()
    assert secret_marker not in manifest_file.read_text(encoding="utf-8")

    verify_proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "backup_sqlite.py"), "--verify-only", str(cli_backup)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert json.loads(verify_proc.stdout)["sha256"] == output_json["sha256"]
