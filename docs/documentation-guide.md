# OpenEMR Documentation Guide

Comprehensive index of all documentation in the OpenEMR repository. This guide covers only the core OpenEMR product documentation — AI agent docs are listed separately at the end.

---

## Root-Level Documents

These are the primary entry points for understanding and contributing to OpenEMR.

| File | Purpose |
|------|---------|
| [README.md](../README.md) | Project overview, CI status badges, links to support/issues/contributing, and build instructions (`composer install`, `npm install`, `npm run build`). Start here if you're new. |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Full contributor guide. Covers conventional commit format (types, scopes, breaking changes), local development setup with Docker, pre-commit hooks, code quality commands, isolated testing, and the complete advanced Docker devtools index (Xdebug, API testing, multisite, CouchDB, LDAP, SSL certs, data snapshots, random patients, and more). |
| [API_README.md](../API_README.md) | REST and FHIR API overview. Quick start for enabling APIs, registering OAuth2 clients, and making first requests. Links to the full documentation suite in `Documentation/api/`. Covers FHIR R4, US Core 8.0, SMART on FHIR v2.2.0, bulk data export, scope examples, and migration from V1 to V2 scopes. |
| [FHIR_README.md](../FHIR_README.md) | FHIR-specific documentation. Standards compliance table (FHIR R4, US Core 8.0, SMART v2.2.0, Bulk Data v1.0, USCDI v1), supported resources (30+), search examples by patient/category/date, authentication scopes, granular scopes, bulk export workflows, CCD generation via `$docref`, and SMART on FHIR launch flows. |
| [DOCKER_README.md](../DOCKER_README.md) | Docker documentation hub. Describes the two categories of Docker images: Production (tagged releases like `7.0.3`) and Development (`flex` series for dev environments, `dev`/`next` nightly builds). Links to docker-compose examples and the Easy/Insane development environments. |
| [CHANGELOG.md](../CHANGELOG.md) | Version history following Keep a Changelog format. Documents added features, bug fixes, and changes for each release with links to GitHub issues/PRs. Current version: 8.0.0 (2026-02-11). |
| [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Community code of conduct. Covers expected behavior, unacceptable behavior (harassment, discrimination, violence), consequences, and reporting guidelines via the community forum at community.open-emr.org. Based on the Citizen Code of Conduct. |
| [README-Isolated-Testing.md](../README-Isolated-Testing.md) | Explains the isolated testing suite that runs PHPUnit tests without database or service dependencies. Describes the problem (default bootstrap loads `globals.php` which requires a full OpenEMR environment), the solution (bypass bootstrap, provide only Composer autoloader), what's not loaded (DB, sessions, config, modules), benefits, usage commands, and how to write isolated tests with dependency injection and mocking. |

---

## API Documentation (`Documentation/api/`)

A comprehensive, modular API documentation suite. The root-level `API_README.md` and `FHIR_README.md` serve as entry points that link here.

| File | Purpose |
|------|---------|
| [README.md](../Documentation/api/README.md) | Documentation index. Table of contents linking all API docs. Quick start prerequisites (SSL, base URL, enabling APIs). Decision tree for choosing your integration path: FHIR for healthcare apps, SMART on FHIR for app integration, Standard API for custom integrations, Developer Guide for internal use. |
| [AUTHENTICATION.md](../Documentation/api/AUTHENTICATION.md) | OAuth2 authentication guide. Covers authorization code grant, client credentials grant, refresh tokens, client registration, PKCE for public apps, asymmetric authentication (JWKS), token introspection, and POST-based authorization. |
| [AUTHORIZATION.md](../Documentation/api/AUTHORIZATION.md) | Scopes and permissions reference. Defines FHIR API scopes (`patient/`, `user/`, `system/` contexts), Standard API scopes, permission flags (`cruds`), granular scopes with category filtering (SMART v2.2.0), and V1 backward compatibility. |
| [STANDARD_API.md](../Documentation/api/STANDARD_API.md) | OpenEMR REST API reference (`/api/` endpoints). Documents all standard REST endpoints for patients, encounters, appointments, billing, prescriptions, documents, and more. Includes the Patient Portal API (experimental). |
| [FHIR_API.md](../Documentation/api/FHIR_API.md) | FHIR R4 API reference (`/fhir/` endpoints). Documents all supported FHIR resources, search parameters, operations ($export, $docref), bulk data export, and examples in JavaScript, Python, and cURL. |
| [SMART_ON_FHIR.md](../Documentation/api/SMART_ON_FHIR.md) | SMART on FHIR app integration guide. Covers EHR launch and standalone launch flows, app registration, launch contexts (patient, encounter, user), SMART configuration endpoint discovery, and troubleshooting. |
| [DEVELOPER_GUIDE.md](../Documentation/api/DEVELOPER_GUIDE.md) | Internal development guide. Covers using APIs from within OpenEMR code, adding new endpoints, controller and service architecture, routing, multisite support, and security best practices. |

---

## Other Product Documentation (`Documentation/`)

Legacy and supplementary documentation files (mostly `.txt` format).

| File | Purpose |
|------|---------|
| `Documentation/Direct_Messaging_README.txt` | Direct messaging functionality for secure clinical message exchange. |
| `Documentation/Emergency_User_README.txt` | Emergency user access — how to create and use emergency login credentials. |
| `Documentation/README-Log-Backup.txt` | Log backup procedures and configuration. |
| `Documentation/SystemArchitecture.txt` | System architecture overview of OpenEMR's internal design. |
| `Documentation/README.phpgacl` | phpGACL (Generic Access Control Lists) — the access control system used by OpenEMR. |
| `Documentation/EHI_Export/docs/deletionOrder.txt` | EHI (Electronic Health Information) export — table deletion order for data export compliance. |
| `Documentation/EHI_Export/docs/insertionOrder.txt` | EHI export — table insertion order for data import. |
| `Documentation/EHI_Export/docs/info-html.txt` | EHI export — HTML documentation template for exported data packages. |
| `Documentation/privileged_db/priv_db_HOWTO.txt` | How to set up and use privileged database access for administrative operations. |

---

## GitHub Community Files (`.github/`)

Standard GitHub community health files.

| File | Purpose |
|------|---------|
| [SECURITY.md](../.github/SECURITY.md) | Security vulnerability reporting instructions. Two options: GitHub Security Advisories (preferred) or email to security@open-emr.org with PGP encryption. |
| [PULL_REQUEST_TEMPLATE.md](../.github/PULL_REQUEST_TEMPLATE.md) | Template for pull request descriptions. |
| [ISSUE_TEMPLATE/bug_report.md](../.github/ISSUE_TEMPLATE/bug_report.md) | Bug report issue template. |
| [ISSUE_TEMPLATE/feature_request.md](../.github/ISSUE_TEMPLATE/feature_request.md) | Feature request issue template. |
| [ISSUE_TEMPLATE/user_story.md](../.github/ISSUE_TEMPLATE/user_story.md) | User story issue template. |
| [copilot-instructions.md](../.github/copilot-instructions.md) | AI coding assistant instructions for GitHub Copilot. |

---

## PHPStan Custom Rules (`.phpstan/`)

Documentation for OpenEMR's custom static analysis rules that enforce modern coding patterns.

| File | Purpose |
|------|---------|
| [README.md](../.phpstan/README.md) | Comprehensive guide to all custom PHPStan rules. **ForbiddenGlobalsAccessRule**: prevents `$GLOBALS` access, requires `OEGlobalsBag::getInstance()`. **ForbiddenFunctionsRule**: prevents legacy `sql.inc.php` functions, `call_user_func()`, and `error_log()` (use `SystemLogger` instead). **ForbiddenClassesRule**: prevents `laminas-db` outside `zend_modules/`. **NoCoversAnnotationRule**: prevents `@covers` in tests. **Disallowed empty()**: prevents `empty()` (use explicit checks). **ForbiddenCurlFunctionsRule**: prevents raw `curl_*` functions (use GuzzleHttp or `oeHttp`). Includes before/after code examples for every rule and baseline management instructions. |
| [MIGRATION_GUIDE.md](../.phpstan/MIGRATION_GUIDE.md) | Migration guide for adopting the new coding patterns enforced by PHPStan rules. |
| [MIGRATION_GUIDE_CURL.md](../.phpstan/MIGRATION_GUIDE_CURL.md) | Specific migration guide for replacing raw `curl_*` calls with GuzzleHttp/`oeHttp`. |

---

## Continuous Integration (`ci/`)

| File | Purpose |
|------|---------|
| [README.md](../ci/README.md) | CI system documentation. Explains the directory layout (subdirectories named `{webserver}_{phpversion}_{dbversion}`), the dynamic test matrix system in GitHub Actions, test types (unit, E2E, API, fixtures, services, validators, controllers, common), code coverage configuration (enabled for `apache_84_114`), the Docker Compose extension system for DRY configurations, how to add new test configurations, and debugging/troubleshooting commands. |
| [README-COVERAGE.md](../ci/README-COVERAGE.md) | Code coverage reporting configuration and setup. |
| [inferno/README.md](../ci/inferno/README.md) | Inferno certification testing — automated ONC compliance testing using the Inferno framework. |

---

## Docker Environments (`docker/`)

Some subdirectories contain a Docker Compose environment with its own README.

| File | Purpose |
|------|---------|
| [development-easy-light/README.md](../docker/development-easy-light/README.md) | Lightweight variant of the easy development environment with reduced resource usage. |
| [development-easy-redis/README.md](../docker/development-easy-redis/README.md) | Easy development environment with Redis integration for session/cache storage. |
| [development-insane/README.md](../docker/development-insane/README.md) | Insane Development Docker Environment — a complex multi-container setup for advanced testing scenarios (multiple PHP versions, databases, web servers). |
| [library/couchdb-config-ssl-cert-keys/README.md](../docker/library/couchdb-config-ssl-cert-keys/README.md) | CouchDB SSL certificate and key configuration for document storage integration. |
| [library/ldap-ssl-certs-keys/README.md](../docker/library/ldap-ssl-certs-keys/README.md) | LDAP SSL certificate and key configuration for directory authentication. |
| [library/sql-ssl-certs-keys/README.md](../docker/library/sql-ssl-certs-keys/README.md) | MySQL/MariaDB SSL certificate and key configuration for encrypted database connections. |

---

## Testing (`tests/`)

| File | Purpose |
|------|---------|
| [README.md](../tests/README.md) | Test suite overview. Directory structure (`Tests/` for PHPUnit, `api/` for legacy helpers, `certification/` for MU mappings, `eventdispatcher/` for event utilities, `js/` for Jest). Commands for Docker-based testing (`openemr-cmd` shortcuts), isolated host-based testing, Twig template validation, and JavaScript tests. |
| [Tests/README.md](../tests/Tests/README.md) | Detailed PHPUnit test documentation. Test suite organization, naming conventions, and guidelines. |
| [Tests/Isolated/Common/Twig/fixtures/render/README.md](../tests/Tests/Isolated/Common/Twig/fixtures/render/README.md) | Twig template render test fixtures. Explains how to add new test cases and update fixture files when templates change. |
| [Tests/E2e/Email/README.md](../tests/Tests/E2e/Email/README.md) | E2E email testing configuration and setup. |
| [Tests/ECQM/README](../tests/Tests/ECQM/README) | ECQM (Electronic Clinical Quality Measures) test documentation. |
| [PHPStan/Rules/README.md](../tests/PHPStan/Rules/README.md) | PHPStan custom rules test documentation. |
| [certification/tests.md](../tests/certification/tests.md) | Meaningful Use certification test mappings. Links OpenEMR features to official ONC test procedures and test data for manual QA — not automated tests. |
| [eventdispatcher/oe-modify-patient-menu-example/README.md](../tests/eventdispatcher/oe-modify-patient-menu-example/README.md) | Example: modifying the patient menu using the event dispatcher system. |
| [eventdispatcher/oe-patient-create-update-hooks-example/README.md](../tests/eventdispatcher/oe-patient-create-update-hooks-example/README.md) | Example: hooking into patient create/update events. |

---

## Database (`db/`)

| File | Purpose |
|------|---------|
| [README.md](../db/README.md) | Database migrations documentation built on `doctrine/migrations`. Covers creating migration scripts (`migration:generate`), applying migrations (`migrate`), reverting migrations (`migrate prev`, with data loss warnings), and the immutability rule — once a migration is in a tagged release, it cannot be altered. Note: the Doctrine Migrations system is not yet fully integrated (see issue #10708). |

---

## UI and Theming (`interface/`)

| File | Purpose |
|------|---------|
| [README.md](../interface/README.md) | OpenEMR UI documentation. The UI is built with SASS on Bootstrap, compiled with Gulp. Describes theme types: `light` (default modern), `manila` (legacy+modern hybrid), and `colors` (color palette variants). Covers RTL theme generation, file naming conventions, special CSS classes, and build commands (`npm run dev` for compilation, `npm run dev-sync` for BrowserSync live reload). |

---

## Custom Modules (`interface/modules/custom_modules/`)

Each module has its own README (and often a CHANGELOG) documenting installation, configuration, and usage.

| Module | Files | Purpose |
|--------|-------|---------|
| **ClaimRev Connect** | `oe-module-claimrev-connect/README.md`, `CHANGELOG.md` | Claims review integration module. |
| **Comlink Telehealth** | `oe-module-comlink-telehealth/Readme.md`, `CHANGELOG.md` | Telehealth/video visit integration via Comlink. |
| **Dashboard Context** | `oe-module-dashboard-context/README.md`, `Dashboard_Context_Manager_User_Guide.md` | Dashboard context management with a full user guide. |
| **EHI Exporter** | `oe-module-ehi-exporter/Readme.md`, `CHANGELOG.md` | Electronic Health Information (EHI) data export for ONC compliance. |
| **Fax/SMS** | `oe-module-faxsms/README.md`, `README-GUIDE.md`, `README-SETUP.md`, `FAX_QUEUE_STORAGE_REFACTORING.md`, `WARP.md` | Fax and SMS communication module. Includes setup guide, user guide, fax queue refactoring notes, and WARP integration docs. |
| **Prior Authorizations** | `oe-module-prior-authorizations/README.md` | Insurance prior authorization management. |
| **Weno** | `oe-module-weno/README.md` | Weno e-prescribing integration. |
| **Custom Modules Overview** | `README.md` (directory-level) | General guide to the custom modules system. |

---

## Zend/Laminas Modules (`interface/modules/zend_modules/`)

| File | Purpose |
|------|---------|
| `module/Multipledb/Readme.md` | Multiple database support module — connecting to multiple OpenEMR instances. |
| `module/Patientvalidation/Readme.md` | Patient validation module — data validation rules for patient records. |

---

## C-CDA Service (`ccdaservice/`)

| File | Purpose |
|------|---------|
| [README.md](../ccdaservice/README.md) | C-CDA (Consolidated Clinical Document Architecture) service documentation. Provides the template engine for Patient Summary CCD generation from the Patient Portal or Carecoordination Module. Also includes oe-schematron-service (QRDA/CDA validation, port 6662) and oe-cqm-service (CQM calculator, port 6660). Covers preparation, updating, Ubuntu/Windows setup, and Node.js requirements (v24.1.0 tested). |
| `packages/oe-cda-schematron/README.md` | Schematron validation service for CDA/QRDA document validation. |

---

## Contributed Tools and Data (`contrib/`)

Community-contributed utilities, medical code sets, and tools. Most use plain `README` files (no `.md` extension).

| File | Purpose |
|------|---------|
| `forms/README.md` | Guide for contributing custom encounter forms. |
| `cqm_valueset/README` | CQM (Clinical Quality Measures) value set data import tools. |
| `dsmiv/README` | DSM-IV (Diagnostic and Statistical Manual) code data. |
| `icd10/README` | ICD-10 diagnosis code import tools and data. |
| `icd9/README` | ICD-9 diagnosis code import tools and data (legacy). |
| `rxnorm/README` | RxNorm drug terminology import tools. |
| `snomed/README` | SNOMED CT clinical terminology import tools. |
| `util/language_translations/README` | Language translation utilities for internationalization. |
| `util/undelete_from_log/README.TXT` | Utility to recover deleted records from the audit log. |
| `venom/README` | Venom testing framework contribution. |

---

## Other Scattered Documentation

| File | Purpose |
|------|---------|
| `src/Cqm/README` | CQM (Clinical Quality Measures) module in the PSR-4 source tree. |
| `src/PaymentProcessing/Rainforest/README.md` | Rainforest payment processing integration. |
| `library/ESign/README` | E-signature functionality for signing clinical documents. |
| `gacl/README` | Generic Access Control Lists — the ACL system underlying OpenEMR's permissions. |
| `gacl/docs/manual.txt` | Full GACL manual for the access control system. |
| `modules/sms_email_reminder/readme.txt` | SMS and email appointment reminder module. |
| `custom/readme_rx_printtofax.txt` | Custom prescription print-to-fax configuration. |
| `custom/rx_addendum.txt` | Prescription addendum customization. |
| `interface/forms/questionnaire_assessments/lforms/README.md` | LForms — NLM's Lister Hill Center form component for questionnaire assessments. |
| `public/assets/modified/dygraphs-2-0-0/README.md` | Dygraphs 2.0 charting library (modified for OpenEMR use). |

---

## AI Agent Documentation (Not Core OpenEMR)

These files are specific to the AI agent deployment built on top of OpenEMR and are not part of the upstream OpenEMR project.

### Operational Docs

| File | Purpose |
|------|---------|
| [ai-agent/README.md](../ai-agent/README.md) | AI agent entry point — tool development pattern, running tests, Docker service, OpenEMR API notes. |
| [ai-agent/docs/deployment.md](../ai-agent/docs/deployment.md) | GCP Compute Engine staging deployment guide for the AI agent. |
| [ai-agent/docs/testing-best-practices.md](../ai-agent/docs/testing-best-practices.md) | AI agent testing best practices (integration test harness, seeding strategy). |
| [ai-agent/docs/integration-tests.md](../ai-agent/docs/integration-tests.md) | Full integration test reference — ephemeral test env, fixture chain, troubleshooting. |
| [ai-agent/contracts/engineering_contract.json](../ai-agent/contracts/engineering_contract.json) | Executable contract for docs/infra/workflow consistency. Validated by `ai-agent/scripts/validate_engineering_contract.py`. |
| `.claude/skills/deploy/SKILL.md` | Claude Code deploy skill for managing GCP staging. |
| `.claude/skills/langsmith/SKILL.md` | Claude Code LangSmith skill for observability. |

### Research Archives (`docs/research/`)

Completed bead investigation reports — point-in-time artifacts, not living docs. See [docs/research/README.md](research/README.md) for the full index.

| File | Purpose |
|------|---------|
| [research-scaffolding-bd313.md](research/research-scaffolding-bd313.md) | Research report on initial agent scaffolding. |
| [research-seed-data-bd-t1a.md](research/research-seed-data-bd-t1a.md) | Research report on seed data strategy. |
| [research-get-encounter-context-bd-1as.md](research/research-get-encounter-context-bd-1as.md) | Research report on the `get_encounter_context` tool implementation. |
| [research-structured-logging-bd-2qj.md](research/research-structured-logging-bd-2qj.md) | Research report on structured logging implementation. |
| [observability-verification-bd-1i9.md](research/observability-verification-bd-1i9.md) | End-to-end observability verification report (LangSmith + Docker logs). |

---

## Navigation Quick Reference

**New to OpenEMR?** Start with [README.md](../README.md) then [CONTRIBUTING.md](../CONTRIBUTING.md).

**Building an integration?** Start with [API_README.md](../API_README.md) or [FHIR_README.md](../FHIR_README.md), then dive into `Documentation/api/`.

**Setting up development?** See [CONTRIBUTING.md](../CONTRIBUTING.md) for Docker setup, or [README-Isolated-Testing.md](../README-Isolated-Testing.md) for host-based testing without Docker.

**Working on code quality?** See [.phpstan/README.md](../.phpstan/README.md) for coding rules and [ci/README.md](../ci/README.md) for the CI pipeline.

**Adding a module?** See `interface/modules/custom_modules/README.md` and the existing module READMEs for patterns.

**Working on the UI?** See [interface/README.md](../interface/README.md) for the SASS/Gulp theming system.

**Database changes?** See [db/README.md](../db/README.md) for the Doctrine Migrations workflow.

**Troubleshooting Docker dev environment?** See [CONTRIBUTING.md](../CONTRIBUTING.md) steps 3 and 7 for the build completion signal ("Love OpenEMR?" message), `docker compose down -v` vs `docker compose down` volume behavior, and the devtools commands (`build-themes`, `register-oauth2-client`, `dev-reset-install-demodata`).
