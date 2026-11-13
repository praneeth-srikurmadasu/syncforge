"""Opaque cursors for keyset pagination (API v2).

A cursor is base64url-encoded JSON with three parts:

* `s` - the sort it was made for;
* `k` - the sort key of the last row on the previous page;
* `q` - a fingerprint of the filters it was made for.

It is not secret and not signed: it only says where to continue, and every query is
still limited to the caller's organization, so an edited cursor can at worst skip rows
the caller may see anyway. It is checked, though: a cursor used with a different sort or
different filters is refused (422 `invalid_cursor`) rather than returning a page from
somewhere else in another result set.
"""

import base64
import binascii
import hashlib
import json
from typing import Any

from app.core.errors import UnprocessableError


def _invalid(message: str) -> UnprocessableError:
    return UnprocessableError(message, code="invalid_cursor")


def fingerprint(filters: dict[str, Any]) -> str:
    canonical = json.dumps(filters, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def encode_cursor(sort: str, key: list[str], filters_fingerprint: str) -> str:
    raw = json.dumps({"s": sort, "k": key, "q": filters_fingerprint}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, *, sort: str, filters_fingerprint: str) -> list[str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        key, cursor_sort, cursor_filters = data["k"], data["s"], data["q"]
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise _invalid("The cursor is not valid. Start again without a cursor.") from exc
    if not isinstance(key, list) or not all(isinstance(v, str) for v in key):
        raise _invalid("The cursor is not valid. Start again without a cursor.")
    if cursor_sort != sort or cursor_filters != filters_fingerprint:
        raise _invalid(
            "The cursor belongs to a different sort or different filters. Use the same "
            "query parameters as the request that returned it, or start without a cursor."
        )
    return key
