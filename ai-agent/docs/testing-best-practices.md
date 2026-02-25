# Testing Best Practices

> **Note:** This document describes aspirational patterns for integration testing
> in multi-service systems. It is a reference guide, not a description of the
> current implementation. For the actual test setup used by the ai-agent today,
> see `tests/conftest.py` (Docker + tmpfs + `INTEGRATION_TEST` env gating) and
> `ai-agent/docs/integration-tests.md`.

## Integration Test Harness Model

### What the harness should own

The integration harness should be responsible for:

- **Starting containers/services** — DB, auth mock/provider, OpenEMR sandbox or mocks, backend service(s)
- **Waiting for readiness** — DB accepts connections, services healthy, migrations can run safely
- **Applying schema** — usually by running your real migration tool
- **Seeding baseline data** — roles, users, reference tables, config, feature flags, code sets
- **Creating per-test/per-suite scenario data** — patients, encounters, appointments, etc.
- **Resetting isolation between tests** — transaction rollback, truncate, schema-per-test, or DB-per-test
- **Tearing down / preserving artifacts on failure** — logs, SQL dumps, traces

This should all be one command in local + CI.

---

## Seeding: Mostly Harness-Driven, Not Manual

Seed the DB automatically — but not as one giant all-purpose script. Use layered seeding:

### Layer A: Baseline seed (harness-managed)

Stable, reusable data needed for many tests:

- Roles/permissions
- OAuth clients
- Feature flags
- Code tables
- Organization/site records
- Reference statuses
- Test users (admin/provider/nurse/etc.)

This runs automatically after migrations.

### Layer B: Scenario seed (test-managed via factories/builders)

Data specific to a test case:

- Patient with allergy X
- Encounter with diagnosis Y
- Appointment in timezone Z
- Expired token/session row
- Conflicting duplicate patient names

This should be created inside the test (or via test helper fixtures), not in a giant global seed.

### Layer C: Large golden dataset (optional)

For a few high-value scenario suites:

- Realistic synthetic mini-clinic dataset
- Used for complex integration/E2E flows
- Versioned and intentionally maintained

Do not use this for all tests.

---

## Recommended Approach for Complex Multi-Service Systems

Given: backend + DB + auth + OpenEMR-related services, containers already launched, likely cross-process tests.

Use a hybrid approach:

### Backend integration tests (fast lane)

- DB container starts once per suite
- Harness runs migrations once
- Harness runs baseline seed once
- Per-test transaction rollback or truncate (choose based on framework constraints)
- Scenario data via factories/fixtures

### Cross-service integration / API tests (reliable lane)

- DB container starts once per suite (or per worker)
- Harness runs migrations once
- Harness runs baseline seed once
- Per-test truncate + baseline reseed
- Scenario seed per test
- No shared mutable records

### E2E tests (highest realism)

- Dedicated test DB per suite/run (or per worker)
- Full migrations
- Baseline seed + golden scenario seed
- Minimal number of test scenarios
- Clean teardown and artifacts on failure

---

## How to Structure Seed Scripts

Avoid one monolithic `seed.sql` for everything.

### Good structure

```
migrations/
    production schema migrations only

seeds/baseline/
    reference data
    roles/permissions
    test OAuth clients
    default org/site config
    feature flags

seeds/scenarios/
    reusable scenario seeds (optional)
    patient_with_diabetes
    patient_with_duplicate_name
    provider_schedule_busy
    expired_session_state

tests/factories/ or tests/builders/
    programmatic data builders for most tests
    compose small records quickly
    override fields per test

tests/fixtures/
    fixture wrappers that call factories + return handles/IDs
```

### Why this separation matters

- **Migrations** define structure
- **Baseline seeds** define environment
- **Factories** define test-specific data
- **Scenarios** define reusable complex setups

This keeps integration tests readable and maintainable.

---

## Migration Testing Best Practices

Migrations are first-class. Add explicit migration tests — do not just rely on integration tests incidentally using migrations.

### Required migration checks

| Check | Description |
|-------|-------------|
| Fresh install | Empty DB → latest schema |
| Upgrade path | Previous release schema/data → latest |
| Seed compatibility | Latest migrations + baseline seeds succeeds |
| Rollback (if supported) | At least for critical migrations |
| Idempotency safety | Seed scripts don't duplicate rows unexpectedly if rerun |

### Practical rule

- **CI PR:** run fresh migration test
- **Nightly/pre-release:** run upgrade path matrix

---

## Common Anti-Patterns

| Anti-pattern | Problem |
|-------------|---------|
| Manual pre-test DB setup ("run this seed script before testing") | Not reproducible |
| One giant seed file with everything | Hidden state, brittle tests |
| Separate test-only schema definitions | Drift from production |
| Tests depending on shared row counts | Flaky in parallel |
| No migration execution in CI | Migration bugs discovered late |
| Factories that write too much | Slow tests, accidental coupling |
| Non-deterministic fake data | Assertion instability |
| Not validating seed success | Tests fail later with unclear cause |

---

## Practical Recommendation for Current Setup

The test harness should handle both migrations and seeding.

### Recommended immediate setup

1. Keep container startup in harness
2. Add a bootstrap step:
   - `wait_for_db`
   - `run_migrations`
   - `run_baseline_seed`
3. Add a per-test reset step:
   - Truncate + reseed (simplest cross-service option)
4. Move scenario data creation into test fixtures/factories
5. Add a nightly suite that rebuilds DB from scratch and runs full migrations + seeds + integration tests
6. If you later need speed, add snapshot restore or transaction-based resets for specific test classes

---

## Developer/Agent Policy

Use this as an internal rule set:

1. Never manually migrate or seed for integration tests.
2. The harness always provisions schema and baseline data.
3. Tests create only the scenario data they need.
4. Migrations are the schema source of truth.
5. Baseline seeds are minimal and stable.
6. Factories/builders are preferred for domain records.
7. Integration tests must be runnable from a clean machine/CI with one command.
