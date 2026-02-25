# OpenEMR AI Agent — Staging Deployment (Compute Engine)

## Architecture Overview

```
Users
  │
  └──► Compute Engine VM (static external IP)
          ├── nginx gateway
          │     ├── /        -> openemr:80
          │     └── /agent/* -> ai-agent:8350
          ├── openemr container (custom image with mandatory chat widget)
          ├── ai-agent container (FastAPI)
          └── cloud-sql-proxy container

Cloud SQL (MySQL 8.0)  <----- cloud-sql-proxy
Artifact Registry      <----- VM pulls openemr/ai-agent images
Secret Manager         <----- VM startup fetches runtime secrets
```

This staging environment intentionally uses a **reserved static IP** and **HTTP**
(no domain). Until a domain exists, managed TLS is not available in the normal
path. Treat this as staging only.

## What Pulumi Manages

`infra/__main__.py` now provisions:

- Artifact Registry repository
- Cloud SQL instance + database + users
- Secret Manager secret shells
- VM service account + IAM roles
- Compute Engine static IP
- Compute Engine firewall rules (HTTP + SSH)
- Compute Engine VM with startup script
- Persistent data disk mounted into container volumes

## Runtime on VM

Startup script performs:

1. Installs Docker + Compose plugin (idempotent)
2. Mounts persistent disk at `/mnt/disks/openemr-data` when present
3. Fetches secrets from Secret Manager
4. Writes:
- `/opt/openemr/.env`
- `/opt/openemr/nginx.conf`
- `/opt/openemr/docker-compose.yml`
5. Runs:
- `docker compose pull`
- `docker compose up -d --remove-orphans`

### Routes

- `http://<STATIC_IP>/` -> OpenEMR
- `http://<STATIC_IP>/agent/health` -> AI agent health

OpenEMR receives:

- `AI_AGENT_URL=http://<STATIC_IP>/agent`
- `AI_AGENT_API_KEY=<secret>`

This is required for the mandatory in-app chat widget.

## Required Secrets

Secret shells are created by Pulumi; populate versions out-of-band:

- `ANTHROPIC_API_KEY`
- `LANGSMITH_API_KEY` (optional but recommended)
- `AI_AGENT_API_KEY`
- `OPENEMR_CLIENT_ID`
- `OPENEMR_CLIENT_SECRET`

Also set Pulumi secret config:

```bash
cd infra
pulumi config set --secret openemr-agent-staging:dbPassword '<strong-password>' --stack staging
```

### Where DB Password Is Stored

The staging DB password is sourced from Pulumi encrypted stack config
(`infra/Pulumi.staging.yaml` under `openemr-agent-staging:dbPassword`).

Retrieve from Pulumi stack config:

```bash
cd infra
PULUMI_CONFIG_PASSPHRASE="" pulumi config get openemr-agent-staging:dbPassword --stack staging
```

## Engineering Contract

Cross-repo deployment/process invariants are enforced by:

- `ai-agent/contracts/engineering_contract.json`
- `ai-agent/scripts/validate_engineering_contract.py`

Run locally:

```bash
python ai-agent/scripts/validate_engineering_contract.py
```

## Manual Deployment (if needed)

```bash
# Build and push images
GCP_REGION=us-central1
PROJECT=openemr-agent-staging
REGISTRY=$GCP_REGION-docker.pkg.dev/$PROJECT/openemr

gcloud auth configure-docker $GCP_REGION-docker.pkg.dev

docker buildx build --platform linux/amd64 \
  -t $REGISTRY/openemr:<tag> \
  -t $REGISTRY/openemr:latest \
  --push \
  .

(cd ai-agent && docker buildx build --platform linux/amd64 \
  -t $REGISTRY/ai-agent:<tag> \
  -t $REGISTRY/ai-agent:latest \
  --push \
  .)

# Apply infra with pinned tags
cd infra
export PULUMI_CONFIG_PASSPHRASE=""
pulumi stack select staging
pulumi config set openemr-agent-staging:openemrImageTag <tag> --stack staging
pulumi config set openemr-agent-staging:aiAgentImageTag <tag> --stack staging
pulumi up --stack staging --yes

# Reboot VM to re-run startup deployment
VM_NAME=$(pulumi stack output vm_name --stack staging)
VM_ZONE=$(pulumi stack output vm_zone --stack staging)
gcloud compute instances reset "$VM_NAME" --zone "$VM_ZONE" --project "$PROJECT"
```

## Seed Data Source

OpenEMR initial schema and seed data are loaded by upstream OpenEMR installer
logic in `openemr/library/classes/Installer.class.php`. Main files:

- `sql/database.sql`
- `contrib/util/language_translations/currentLanguage_utf8.sql`
- `sql/cvx_codes.sql` (if present)
- `sql/official_additional_users.sql`

Because this image clones OpenEMR `master` during build, installer seed behavior
tracks upstream `master`.

## CI/CD Pipeline (GitHub Actions)

### Workflow: `.github/workflows/deploy-staging.yml`

#### 1. `build-openemr`

- Builds top-level `Dockerfile`
- Pushes:
- `openemr:${GITHUB_SHA}`
- `openemr:latest`

#### 2. `build-agent`

- Builds `ai-agent/Dockerfile`
- Pushes:
- `ai-agent:${GITHUB_SHA}`
- `ai-agent:latest`

#### 3. `deploy`

- Sets Pulumi config image tags to `${GITHUB_SHA}`
- Runs `pulumi up --stack staging --yes`
- Reads stack outputs (`openemr_ip`, `vm_name`, `vm_zone`)
- Resets VM so startup script pulls the new pinned tags and recreates containers

#### 4. `verify`

- Polls until both pass:
- `http://<openemr_ip>/meta/health/readyz`
- `http://<openemr_ip>/agent/health`

### Why we reset VM in CI

The startup script is the deployment entrypoint for runtime composition and
secret materialization. Reset guarantees a consistent rollout path on each
deploy without requiring SSH remote execution logic.

## Rollback

Rollback is tag-based:

1. Set prior known-good tags in Pulumi config:

```bash
cd infra
pulumi config set openemr-agent-staging:openemrImageTag <old-tag> --stack staging
pulumi config set openemr-agent-staging:aiAgentImageTag <old-tag> --stack staging
pulumi up --stack staging --yes
```

2. Reset VM:

```bash
VM_NAME=$(pulumi stack output vm_name --stack staging)
VM_ZONE=$(pulumi stack output vm_zone --stack staging)
gcloud compute instances reset "$VM_NAME" --zone "$VM_ZONE" --project openemr-agent-staging
```

## Operational Notes

- No domain means no managed TLS endpoint yet; use staging only.
- Firewall currently allows HTTP from anywhere and SSH per Pulumi config
  `sshSourceRanges`.
- Use immutable image tags (git SHA) for safer rollbacks.
- Data persists in Cloud SQL. Avoid mounting over OpenEMR core runtime paths.
- Cloud SQL persists separately from VM lifecycle.

## Known Failure Modes

- `pulumi stack output` fails:
  set `PULUMI_CONFIG_PASSPHRASE` before output commands.
- VM cannot pull Artifact Registry images:
  ensure startup script performs Docker login using metadata token.
- Long OpenEMR first boot:
  on small Cloud SQL tiers, installer can run for a long time while loading
  language and seed data.
- `502` from gateway:
  OpenEMR upstream not listening yet.
- `/meta/health/readyz` returns `setup_required`:
  service is reachable, but OpenEMR setup is not finished.

See detailed infra runbook:

- `infra/TROUBLESHOOTING.md`

## Teardown

```bash
cd infra
pulumi destroy --stack staging --yes
```

This destroys VM, IP, firewall, Cloud SQL, Artifact Registry resources, and
Secret Manager shells managed by this stack.
