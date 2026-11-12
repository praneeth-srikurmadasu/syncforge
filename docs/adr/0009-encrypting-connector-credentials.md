# ADR-0009: Encrypting connector credentials at rest

- **Status:** Accepted
- **Date:** 2026-11-11

## Context
Connectors store secrets that grant powerful access to other systems: a Slack SCIM token
can create and deactivate every account in a workspace, and an OAuth client secret can act
on a whole Google domain. SyncForge must call the vendors itself, so it needs the plaintext
secrets at call time and cannot store only a hash.

## Problem
Limit the damage of a database leak (backup copied, SQL injection, a read replica shared
too widely) without making the secrets unusable for the application.

## Considered alternatives
| Option | Assessment |
|---|---|
| Plaintext in the database | Any database read exposes every tenant's integrations. Unacceptable. |
| PostgreSQL `pgcrypto` | The key travels in SQL statements and can end up in database logs; it ties encryption to SQL. |
| External secrets manager (Vault, AWS Secrets Manager, Azure Key Vault) | Strongest operationally: access policies, auditing, managed rotation. But it adds infrastructure the local, self-contained project cannot assume. |
| **Application-level authenticated encryption (Fernet) with the key outside the database** | A database leak alone reveals nothing. Simple, well-reviewed library; tamper-evident; supports key rotation. |

## Decision
- Credentials are validated, serialized to JSON and encrypted with **Fernet** (from the
  `cryptography` package): AES-128-CBC plus HMAC-SHA256, with a random IV per value.
- The key comes from `CONNECTOR_ENCRYPTION_KEY`, an environment or secret-store value,
  never the database.
- The setting accepts **several comma-separated keys** (`MultiFernet`): the first encrypts,
  all decrypt. Rotation steps:
  1. Prepend a new key.
  2. Re-save the credentials (the `PATCH` endpoint re-encrypts with the first key).
  3. Remove the old key.
- Ciphertext lives in its own table (`connector_credentials`), so list queries never load
  it. It is decrypted only when an adapter is built for a call, and is never returned,
  logged or echoed in validation errors. The API shows a 4-character fingerprint.
- Without a key, creating a connector fails with `503 encryption_not_configured`, and
  production refuses to start. A blank value counts as "not set".

## Trade-offs
- Anyone who has both the database and the key can decrypt. The key must be guarded like
  any production secret (a secrets manager in production; see the deployment guide in
  Phase 10).
- Rotation re-encrypts row by row through the application; there is no bulk re-encryption
  command yet (future improvement).
- The decrypted secrets exist in process memory during a call.

## Consequences
- `test_encryption.py` covers round trip, tamper detection, wrong key, rotation,
  blank or missing key and the production check.
- `test_create_connector_encrypts_credentials_and_never_returns_them` asserts that the
  plaintext appears neither in the API response nor in the stored ciphertext.
- Moving to a secrets manager later changes only `CredentialCipher.from_settings` (or
  replaces it with an envelope-encryption key provider), not the service or schema.
