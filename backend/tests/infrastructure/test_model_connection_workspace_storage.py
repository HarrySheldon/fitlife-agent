"""Connection workspace behavior, using synthetic records only."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.domain.model_connection import ModelConnection
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository


def test_disabled_draft_does_not_replace_active(tmp_path):
    from backend.domain.model_connection import ModelConnectionWorkspace

    repo = FileModelConnectionRepository(tmp_path)
    active = ModelConnection(model="active", enabled=True)
    repo.save("user-a", active)
    before = repo.get_workspace("user-a")
    draft = ModelConnection(model="candidate", enabled=False)
    after = repo.compare_and_set("user-a", expected_revision=before.revision,
        workspace=ModelConnectionWorkspace(revision=before.revision + 1, active=active, draft=draft))

    assert after.draft.model == "candidate"
    assert repo.get("user-a") == active
    assert repo.get_workspace("user-b").active is None


def test_legacy_read_has_no_write_side_effect(tmp_path):
    repo = FileModelConnectionRepository(tmp_path)
    path = tmp_path / "users" / "user-a" / "model_connection.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(ModelConnection(model="legacy", enabled=True,
        test_status="success").model_dump()), encoding="utf-8")
    before = path.read_bytes()
    workspace = repo.get_workspace("user-a")
    assert workspace.revision == 0
    assert workspace.active.enabled
    assert workspace.active.generation_status == "not_run"
    assert path.read_bytes() == before


def test_compare_and_set_has_one_winner(tmp_path):
    from backend.domain.errors import ApplicationError
    from backend.domain.model_connection import ModelConnectionWorkspace

    def save(model):
        try:
            FileModelConnectionRepository(tmp_path).compare_and_set("user-a", expected_revision=0,
                workspace=ModelConnectionWorkspace(revision=1, draft=ModelConnection(model=model)))
            return "saved"
        except ApplicationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(save, ["a", "b"]))
    assert sorted(results) == ["MODEL_CONFIGURATION_CONFLICT", "saved"]


def test_failed_atomic_replace_preserves_previous_snapshot(tmp_path, monkeypatch):
    from backend.domain.model_connection import ModelConnectionWorkspace

    repo = FileModelConnectionRepository(tmp_path)
    repo.save("user-a", ModelConnection(model="old"))
    path = tmp_path / "users" / "user-a" / "model_connection.json"
    before = path.read_bytes()
    def fail(*_args):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(repo, "replace_file", fail)
    with pytest.raises(OSError):
        repo.compare_and_set("user-a", expected_revision=1,
            workspace=ModelConnectionWorkspace(revision=2, draft=ModelConnection(model="new")))
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_enabled_draft_and_unknown_envelope_version_fail_closed(tmp_path):
    from pydantic import ValidationError
    from backend.domain.model_connection import ModelConnectionWorkspace
    with pytest.raises(ValidationError):
        ModelConnectionWorkspace(draft=ModelConnection(enabled=True))
    path = tmp_path / "users" / "user-a" / "model_connection.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": 99}', encoding="utf-8")
    with pytest.raises(ValidationError):
        FileModelConnectionRepository(tmp_path).get_workspace("user-a")
