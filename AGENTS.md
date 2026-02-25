# AI Agent Development Guide

This repository is a workspace for building a fork of OpenEMR that contains an LLM-driven chat interface and
server. The forked version is in `openemr/` and should probably be a submodule, but we have made some minor frontend changes.

For OpenEMR-wide development setup and standards, see
[docs/openemr-development-guide.md](docs/openemr-development-guide.md).

## Scope

- AI agent backend (chat interface talks to this, server communicates with database, this only handles LLM calls, harness, etc): `/ai-agent/` . This is where almost all of our feature work will go.
- Pulumi IaC for GCP: `/infra/`
- Documentation: `/docs/`


## Key AI Agent Docs

- [ai-agent/README.md](ai-agent/README.md)
- [ai-agent/docs/deployment.md](ai-agent/docs/deployment.md)
- [ai-agent/docs/testing-best-practices.md](ai-agent/docs/testing-best-practices.md)
- [ai-agent/docs/integration-tests.md](ai-agent/docs/integration-tests.md)
