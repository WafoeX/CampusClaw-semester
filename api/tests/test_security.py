# pyright: basic, reportMissingImports=false
import pytest

from campusclaw.domain.security import PasswordService


def fast_hasher() -> PasswordService:
    return PasswordService(memory_cost=8192, time_cost=1, parallelism=1)


def test_argon2id_hashes_verify_and_use_unique_salts() -> None:
    hasher = fast_hasher()
    first = hasher.hash("correct horse battery staple")
    second = hasher.hash("correct horse battery staple")
    assert first.startswith("$argon2id$")
    assert first != second
    assert hasher.verify(first, "correct horse battery staple")
    assert not hasher.verify(first, "wrong")


def test_rehash_required_when_policy_changes() -> None:
    old = PasswordService(memory_cost=8192, time_cost=1, parallelism=1)
    current = PasswordService(memory_cost=8192, time_cost=2, parallelism=1)
    encoded = old.hash("password")
    assert old.needs_rehash(encoded) is False
    assert current.needs_rehash(encoded) is True
    valid, replacement = current.verify_and_rehash(encoded, "password")
    assert valid is True
    assert replacement is not None
    assert current.verify(replacement, "password")
    assert current.needs_rehash(replacement) is False


def test_rehash_helper_does_not_replace_current_or_invalid_hashes() -> None:
    hasher = fast_hasher()
    encoded = hasher.hash("password")
    assert hasher.verify_and_rehash(encoded, "password") == (True, None)
    assert hasher.verify_and_rehash(encoded, "wrong") == (False, None)


def test_invalid_hash_and_empty_password_are_safe() -> None:
    hasher = fast_hasher()
    with pytest.raises(ValueError, match="must not be empty"):
        hasher.hash("")
    assert hasher.verify("not-a-hash", "password") is False
    assert hasher.needs_rehash("not-a-hash") is False
