"""Password checks beyond length (NIST SP 800-63B section 3.1.1.2).

No composition rules (they push people towards predictable patterns); instead, refuse
passwords that are known to be common or that are built from the account's own context.
The list is bundled and checked offline - nothing is sent to a third party.
"""

from functools import lru_cache
from pathlib import Path

_LIST = Path(__file__).with_name("data") / "common_passwords.txt"
_SERVICE_WORDS = ("syncforge",)


@lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    lines = _LIST.read_text(encoding="utf-8").splitlines()
    return frozenset(line for line in lines if line and not line.startswith("#"))


def password_problem(password: str, email: str | None = None) -> str | None:
    """A message explaining why the password is refused, or None if it is acceptable.

    The message never repeats the password."""
    lowered = password.lower()
    if lowered in common_passwords():
        return "This password is too common. Choose one that is not on lists of leaked passwords."
    if len(set(lowered)) == 1:
        return "This password repeats a single character."
    if any(word in lowered for word in _SERVICE_WORDS):
        return "The password must not contain the name of this service."
    if email:
        name = email.split("@", 1)[0].lower()
        if len(name) >= 4 and name in lowered:
            return "The password must not contain your email address."
    return None
