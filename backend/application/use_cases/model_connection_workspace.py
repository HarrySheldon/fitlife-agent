"""Configuration writes: no model calls, one atomic workspace transition."""
from backend.application.use_cases.model_connection_preview import setup_error
from backend.domain.model_connection import credential_hint, utc_now_iso


class ModelConnectionWorkspaceService:
    def __init__(self, preview):
        self.preview = preview
        self.repository = preview.repository

    def _save(self, user_id, current, **changes):
        updated = current.model_copy(update={**changes, "revision": current.revision + 1})
        return self.repository.compare_and_set(user_id, expected_revision=current.revision, workspace=updated).to_public()

    def _current(self, user_id, revision):
        current = self.repository.get_workspace(user_id)
        if current.revision != revision:
            raise setup_error("MODEL_CONFIGURATION_CONFLICT", "The model configuration changed. Reload before saving.")
        return current

    def _credential_connection(self, connection, credential):
        return connection.model_copy(update={"encrypted_api_key": self.preview.cipher.encrypt(credential),
            "api_key_hint": credential_hint(credential)})

    def save_draft(self, user_id, payload):
        current, connection, credential, _ = self.preview.prepare(user_id, payload)
        return self._save(user_id, current, draft=self._credential_connection(connection, credential))

    def activate(self, user_id, payload):
        current, connection, credential, binding = self.preview.prepare(user_id, payload)
        self.preview.verification.verify(payload.verification_token, binding)
        active = self._credential_connection(connection, credential).model_copy(update={"enabled": True,
            "test_status": "success", "generation_status": "passed", "structured_status": "passed", "tested_at": utc_now_iso()})
        return self._save(user_id, current, active=active, draft=None)

    def disable(self, user_id, revision):
        current = self._current(user_id, revision)
        active = current.active.model_copy(update={"enabled": False, "updated_at": utc_now_iso()}) if current.active else None
        return self._save(user_id, current, active=active)

    def clear_credential(self, user_id, revision, slot):
        if slot not in ("active", "draft"):
            raise setup_error("MODEL_SLOT_INVALID", "Choose active or draft.", 422)
        current = self._current(user_id, revision)
        connection = getattr(current, slot)
        if connection:
            connection = connection.model_copy(update={"enabled": False, "encrypted_api_key": None,
                "api_key_hint": None, "test_status": "untested", "generation_status": "not_run",
                "tool_status": "not_run", "structured_status": "not_run", "tested_at": None, "test_error_code": None, "updated_at": utc_now_iso()})
        return self._save(user_id, current, **{slot: connection})
