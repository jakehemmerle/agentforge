# OpenEMR Development Guide

This guide contains OpenEMR-wide development practices and repository workflow
details that are not specific to the AI agent.

For AI-agent-specific development instructions, see [AGENTS.md](../AGENTS.md)
and [ai-agent/README.md](../ai-agent/README.md).

See [CONTRIBUTING.md](../CONTRIBUTING.md) for full Docker setup and contributor
guidelines.

## Project Structure

```
/src/              - Modern PSR-4 code (OpenEMR\ namespace)
/library/          - Legacy procedural PHP code
/interface/        - Web UI controllers and templates
/templates/        - Smarty/Twig templates
/tests/            - Test suite (unit, e2e, api, services)
/sql/              - Database schema and migrations
/public/           - Static assets
/docker/           - Docker configurations
/ai-agent/         - Python LangGraph AI agent (separate sub-project with its own deps)
/docs/             - Documentation guide and research archives (see docs/research/)
/modules/          - Custom and third-party modules
```

## Technology Stack

- **PHP:** 8.2+ required
- **Backend:** Laminas MVC, Symfony components
- **Templates:** Twig 3.x (modern), Smarty 4.5 (legacy)
- **Frontend:** Angular 1.8, jQuery 3.7, Bootstrap 4.6
- **Build:** Gulp 4, SASS
- **Database:** MySQL via ADODB wrapper
- **Testing:** PHPUnit 11, Jest 29

## Local Development

See `CONTRIBUTING.md` for full setup instructions. Quick start:

```bash
cd docker/development-easy
docker compose up --detach --wait
```

- **App URL:** http://localhost:8300/ or https://localhost:9300/
- **Login:** `admin` / `pass`
- **phpMyAdmin:** http://localhost:8310/

## Testing

Tests run inside Docker via devtools. Run from `docker/development-easy/`:

```bash
# Run all tests
docker compose exec openemr /root/devtools clean-sweep-tests

# Individual test suites
docker compose exec openemr /root/devtools unit-test
docker compose exec openemr /root/devtools api-test
docker compose exec openemr /root/devtools e2e-test
docker compose exec openemr /root/devtools services-test

# View PHP error log
docker compose exec openemr /root/devtools php-log
```

**Tip:** Install [openemr-cmd](https://github.com/openemr/openemr-devops/tree/master/utilities/openemr-cmd)
for shorter commands (for example, `openemr-cmd ut`) from any directory.

### Isolated tests (no Docker required)

Isolated tests run on the host without a database or Docker:

```bash
composer phpunit-isolated
```

### Twig Template Tests

Twig templates have two layers of testing (both isolated):

- **Compilation tests** verify every `.twig` file parses and references valid
  filters/functions/tests.
- **Render tests** render specific templates with known parameters and compare
  full HTML output to fixtures in
  `tests/Tests/Isolated/Common/Twig/fixtures/render/`.

When modifying a Twig template with render-test coverage, update fixtures:

```bash
composer update-twig-fixtures
```

See the fixtures README for adding new test cases:
`tests/Tests/Isolated/Common/Twig/fixtures/render/README.md`.

## Code Quality

These run on the host (requires local PHP and Node):

```bash
# Run all PHP quality checks
composer code-quality

# Individual checks
composer phpstan
composer phpcs
composer phpcbf
composer rector-check

# JavaScript/CSS
npm run lint:js
npm run lint:js-fix
npm run stylelint
```

## Build Commands

```bash
npm run build
npm run dev
npm run gulp-build
```

## Coding Standards

- **Indentation:** 4 spaces
- **Line endings:** LF (Unix)
- **No strict_types:** Project does not use `declare(strict_types=1)`
- **Namespaces:** PSR-4 with `OpenEMR\` prefix for `/src/`
- New code goes in `/src/`, legacy helpers in `/library/`

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

**Types:** feat, fix, docs, style, refactor, perf, test, build, ci, chore,
revert

Examples:
- `feat(api): add PATCH support for patient resource`
- `fix(calendar): correct date parsing for recurring events`
- `chore(deps): bump monolog/monolog to 3.10.0`

## Service Layer Pattern

New services should extend `BaseService`:

```php
namespace OpenEMR\Services;

class ExampleService extends BaseService
{
    public const TABLE_NAME = "table_name";

    public function __construct()
    {
        parent::__construct(self::TABLE_NAME);
    }
}
```

## File Headers

When modifying PHP files, ensure proper docblock:

```php
/**
 * Brief description
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Your Name <your@email.com>
 * @copyright Copyright (c) YEAR Your Name or Organization
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */
```

Preserve existing authors and copyrights when editing files.

## Common Gotchas

- Multiple template engines: check extension (`.twig`, `.html`, `.php`)
- Event system uses Symfony EventDispatcher
- Pre-commit hooks are available via `.pre-commit-config.yaml`

## Beads Workflow Integration

This project uses [beads_viewer](https://github.com/Dicklesworthstone/beads_viewer)
for issue tracking. Issues are stored in `.beads/` and tracked in git.

### Essential Commands

```bash
# View issues (launches TUI - avoid in automated sessions)
bv

# CLI commands for agents
br ready
br list --status=open
br show <id>
br create -t task -p 2 "Issue title here"
br update <id> --status=in_progress
br close <id> --reason="Completed"
br close <id1> <id2>
br sync
```

### Workflow Pattern

1. Run `br ready` to find actionable work.
2. Use `br update <id> --status=in_progress` to claim.
3. Implement the task.
4. Use `br close <id>` when complete.
5. Run `br sync` at session end.

### Key Concepts

- **Dependencies:** issues can block other issues.
- **Priority:** P0 critical, P1 high, P2 medium, P3 low, P4 backlog.
- **Types:** task, bug, feature, epic, question, docs.
- **Blocking:** `br dep add <issue> <depends-on>`.

### Session Protocol

Before ending a session:

```bash
git status
br sync
git add <files>
git commit -m "..."
git push
```

## bv Robot Triage

`bv` is graph-aware triage for Beads projects (`.beads/beads.jsonl`).

Use only `--robot-*` flags. Running bare `bv` opens an interactive TUI.

### Start Here

```bash
bv --robot-triage
bv --robot-next
```

### Planning

- `--robot-plan`: parallel tracks with `unblocks` lists
- `--robot-priority`: priority misalignment detection with confidence

### Graph Analysis

- `--robot-insights`: PageRank, betweenness, HITS, eigenvector, critical path,
  cycles, k-core, articulation points, slack
- `--robot-label-health`: per-label health and staleness
- `--robot-label-flow`: cross-label dependency matrix and bottlenecks
- `--robot-label-attention`: attention-ranked labels

### History and Diffs

- `--robot-history`: bead-to-commit correlations
- `--robot-diff --diff-since <ref>`: issue changes and cycles since a ref

### Other Commands

- `--robot-burndown <sprint>`
- `--robot-forecast <id|all>`
- `--robot-alerts`
- `--robot-suggest`
- `--robot-graph [--graph-format=json|dot|mermaid]`
- `--export-graph <file.html>`

### Scoping and Filtering

```bash
bv --robot-plan --label backend
bv --robot-insights --as-of HEAD~30
bv --recipe actionable --robot-plan
bv --recipe high-impact --robot-triage
bv --robot-triage --robot-triage-by-track
bv --robot-triage --robot-triage-by-label
```

### jq Quick Reference

```bash
bv --robot-triage | jq '.quick_ref'
bv --robot-triage | jq '.recommendations[0]'
bv --robot-plan | jq '.plan.summary.highest_impact'
bv --robot-insights | jq '.status'
bv --robot-insights | jq '.Cycles'
```

## Key Documentation

See [documentation-guide.md](documentation-guide.md) for the full index.

Essential starting points:
- [CONTRIBUTING.md](../CONTRIBUTING.md)
- [API_README.md](../API_README.md)
- [FHIR_README.md](../FHIR_README.md)
- [Documentation/api/AUTHENTICATION.md](../Documentation/api/AUTHENTICATION.md)
- [interface/README.md](../interface/README.md)
- [ai-agent/README.md](../ai-agent/README.md)
- [ai-agent/docs/](../ai-agent/docs/)
- [docs/research/](research/)
