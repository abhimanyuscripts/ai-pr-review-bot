"""Password hashing and an in-memory user store, used as the target of the demo PRs."""

from __future__ import annotations

import hashlib
import hmac
import os

ITERATIONS = 200_000
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return salt, digest


def verify_password(password: str, salt: bytes, expected: bytes) -> bool:
    _, digest = hash_password(password, salt)
    return hmac.compare_digest(digest, expected)


class UserStore:
    def __init__(self) -> None:
        self._users: dict[str, tuple[bytes, bytes]] = {}

    def register(self, username: str, password: str) -> None:
        if not username:
            raise ValueError("username is required")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
        if username in self._users:
            raise ValueError("username already exists")
        self._users[username] = hash_password(password)

    def login(self, username: str, password: str) -> bool:
        record = self._users.get(username)
        if record is None:
            return False
        salt, digest = record
        return verify_password(password, salt, digest)
