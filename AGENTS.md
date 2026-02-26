**Always start every session with reading ALL of the README.md documents.**

- [ai-agent/README.md](ai-agent/README.md)
- [ai-agent/docs/integration-tests.md](ai-agent/docs/integration-tests.md)
- [chat-widget/README.md](chat-widget/README.md)
- [injectables/README.md](injectables/README.md)
- [infra/README.md](infra/README.md)

This repository is a workspace for building a fork of OpenEMR that contains an LLM-driven chat interface and
server. The submodule is in `openemr/`, and we NEVER write to it, we only inject changes into it.

CHANGES TO openemr/ MUST BE DONE THROUGH THE injectables/ MODULE!
