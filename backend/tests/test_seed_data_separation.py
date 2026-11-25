from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from backend.config import get_settings
from backend.infrastructure.agent_runtime.factory import get_agent_runtime
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.startup import run_startup
from backend.tools.data_access import read_eval_cases


def test_external_empty_data_dir_boots_using_bundled_code_seeds(tmp_path, monkeypatch):
    external_data_dir = tmp_path / "external-user-data"
    monkeypatch.setenv("DATA_DIR", str(external_data_dir))
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.data_dir == external_data_dir
        assert settings.seed_dir != external_data_dir
        assert settings.food_catalog_seed_path.is_file()
        assert settings.exercise_catalog_seed_path.is_file()
        assert settings.eval_dataset_path.is_file()
        assert settings.runtime_database_path == external_data_dir / "agent_runtime.sqlite3"

        summary = run_startup(SQLiteDatabase(settings.database_path), external_data_dir)
        assert summary.status == "ready"
        assert summary.schema_version == 15
        assert (external_data_dir / "fitlife.sqlite3").is_file()
        assert (external_data_dir / "vector_index-releases").is_dir()

        # Bundled seed directories are NOT copied into runtime DATA_DIR.
        assert not (external_data_dir / "catalog").exists()
        assert not (external_data_dir / "safety").exists()
        assert not (external_data_dir / "eval_questions.json").exists()

        # Catalog seeds were imported from SEED_DIR into SQLite.
        with sqlite3.connect(settings.database_path) as connection:
            food_count = connection.execute("SELECT COUNT(*) FROM food_catalog WHERE source = 'public'").fetchone()[0]
            exercise_count = connection.execute("SELECT COUNT(*) FROM exercise_catalog WHERE source = 'public'").fetchone()[0]
        assert food_count > 0
        assert exercise_count > 0

        # Eval cases resolve from SEED_DIR when DATA_DIR has no override.
        eval_cases = read_eval_cases()
        assert len(eval_cases) > 0

        # Agent runtime database lives inside DATA_DIR.
        _ = get_agent_runtime()
        assert (external_data_dir / "agent_runtime.sqlite3").is_file()
    finally:
        get_settings.cache_clear()


def test_eval_dataset_prefers_data_dir_override_when_present(tmp_path, monkeypatch):
    external_data_dir = tmp_path / "custom-eval-data"
    external_data_dir.mkdir(parents=True)
    override_file = external_data_dir / "eval_questions.json"
    override_file.write_text(
        json.dumps([
            {
                "question": "Custom dataset override check",
                "expected_tool": None,
                "expected_retrieval_doc": None,
                "expected_answer_format": "markdown",
                "expected_keywords": ["override"],
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(external_data_dir))
    get_settings.cache_clear()
    try:
        cases = read_eval_cases()
        assert len(cases) == 1
        assert cases[0].question == "Custom dataset override check"
    finally:
        get_settings.cache_clear()
