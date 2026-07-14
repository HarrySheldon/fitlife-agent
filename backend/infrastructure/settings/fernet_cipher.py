from __future__ import annotations

from cryptography.fernet import Fernet


class FernetCredentialCipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise ValueError("SETTINGS_ENCRYPTION_KEY must be a valid Fernet key") from error

    @classmethod
    def generate(cls) -> "FernetCredentialCipher":
        return cls(Fernet.generate_key().decode("ascii"))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
