# ADR-0001: Modular monolith built with FastAPI

- **Status:** Accepted
- **Date:** 2026-11-11

## Context
SyncForge needs a REST API, background processing of synchronization events, a connector
framework and an admin UI. It is built by a small team and must be easy to run locally and
to explain end to end.

## Problem
Choose the backend framework and the deployment shape of the backend.

## Considered alternatives
| Option | Assessment |
|---|---|
| Microservices (auth, employees, connectors, workers as separate services) | Independent scaling, but adds network calls, distributed transactions and operational overhead with no current scaling need. |
| Modular monolith | One codebase and deployable API; modules separated by layers and folders; workers scale separately. |
| Django + DRF | Mature, but heavier; ORM and admin conventions add less value for an API-first service. |
| Flask | Minimal, but validation, OpenAPI and dependency injection must be assembled by hand. |
| **FastAPI** | Type-hint driven validation (Pydantic), automatic OpenAPI docs, built-in dependency injection. |

## Decision
Build a **modular monolith with FastAPI**. Layers: routers → services → repositories →
models, with cross-cutting code in `app/core`. Background workers (Phase 5) run the same
codebase as separate processes.

## Trade-offs
- All API modules deploy together; a bad release affects every endpoint.
- Module boundaries are enforced by convention and review, not by network boundaries.

## Consequences
- A single transaction can span multiple modules (e.g. save an employee and its outbox
  event atomically), which a microservice split would make much harder.
- OpenAPI documentation is generated from the code and stays current.
- A module can be extracted into its own service later if a real scaling need appears.
