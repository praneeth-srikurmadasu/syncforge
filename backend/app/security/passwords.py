"""Password hashing with Argon2id.

Argon2id is the current OWASP recommendation: it is deliberately slow and
memory-hard, so stolen hashes are expensive to brute-force. Each hash embeds its
own random salt and parameters, e.g. "$argon2id$v=19$m=65536,t=3,p=4$...".
"""

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_hasher = PasswordHash((Argon2Hasher(),))

# Verified against when the email is unknown, so "no such user" takes as long as
# "wrong password" - response timing does not reveal which emails are registered.
_DUMMY_HASH = _hasher.hash("timing-equalisation-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Return (is_valid, new_hash). new_hash is set when the stored hash uses
    outdated parameters and should be replaced (transparent rehashing)."""
    return _hasher.verify_and_update(password, password_hash)


def burn_verification_time(password: str) -> None:
    _hasher.verify(password, _DUMMY_HASH)
