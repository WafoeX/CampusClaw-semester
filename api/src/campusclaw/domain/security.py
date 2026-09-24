# pyright: basic, reportMissingImports=false
"""Password hashing and verification primitives."""

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type


class PasswordService:
    """Argon2id policy with rehash support."""

    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost: int = 65_536,
        parallelism: int = 2,
    ) -> None:
        self._hasher = Argon2PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )

    def hash(self, password: str) -> str:
        if not password:
            raise ValueError("password must not be empty")
        return self._hasher.hash(password)

    def verify(self, encoded_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(encoded_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def needs_rehash(self, encoded_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(encoded_hash)
        except InvalidHashError:
            return False

    def verify_and_rehash(self, encoded_hash: str, password: str) -> tuple[bool, str | None]:
        """Verify once and return a replacement hash when policy parameters changed."""
        if not self.verify(encoded_hash, password):
            return False, None
        if self.needs_rehash(encoded_hash):
            return True, self.hash(password)
        return True, None
