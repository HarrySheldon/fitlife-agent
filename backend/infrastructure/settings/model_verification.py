"""Short-lived domain-separated receipts. No credential is serialized into a receipt."""
import base64
import hashlib
import hmac
import json
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.domain.errors import model_verification_required_error


PROBE_VERSION = "generation-structured-v2"


class SignedModelVerification:
    def __init__(self, key: str, *, clock=time.time):
        raw = base64.urlsafe_b64decode(key.encode("ascii"))
        if len(raw) != 32:
            raise ValueError("Invalid deployment encryption key")
        self._signing_key = self._derive(raw, b"fitlife:model-verification:v1")
        self._fingerprint_key = self._derive(raw, b"fitlife:model-credential-fingerprint:v1")
        self.clock = clock

    @staticmethod
    def _derive(raw, info):
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(raw)

    def fingerprint(self, credential: str) -> str:
        return hmac.new(self._fingerprint_key, credential.encode(), hashlib.sha256).hexdigest()

    def issue(self, binding: dict) -> str:
        payload = {"v": PROBE_VERSION, "issued_at": self.clock(), "binding_digest": self._binding_digest(binding),
                   "generation": "passed", "structured": "passed"}
        encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode()
        signature = hmac.new(self._signing_key, encoded.encode(), hashlib.sha256).hexdigest()
        return encoded + "." + signature

    def verify(self, token: str, binding: dict) -> None:
        try:
            if len(token) > 4096:
                raise ValueError()
            encoded, signature = token.split(".")
            expected = hmac.new(self._signing_key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(encoded))
            age = self.clock() - payload["issued_at"]
            if not -30 <= age < 900 or payload["v"] != PROBE_VERSION:
                raise ValueError()
            if not hmac.compare_digest(payload["binding_digest"], self._binding_digest(binding)):
                raise ValueError()
            if payload["generation"] != "passed" or payload["structured"] != "passed":
                raise ValueError()
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
            raise model_verification_required_error() from None

    @staticmethod
    def _binding_digest(binding: dict) -> str:
        canonical = json.dumps(binding, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
