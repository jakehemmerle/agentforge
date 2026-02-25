---
name: deploy
description: "Manage GCP staging deployment: status, deploy, update, logs, teardown"
argument-hint: "[action: status|deploy|update|logs|teardown|seed|preview]"
---

Manage the OpenEMR AI Agent staging deployment on GCP Compute Engine.

## Prerequisites

- `gcloud` CLI authenticated with the `openemr-agent-staging` project
- `pulumi` CLI installed and authenticated (PULUMI_ACCESS_TOKEN set)
- Working directory: project root (contains infra/ directory)

## Actions

### `status` — Health check all services

Check the health of all deployed services:

```bash
cd infra && export PULUMI_CONFIG_PASSPHRASE=""

# Get URLs and VM info
OPENEMR_IP=$(pulumi stack output openemr_url --stack staging)
VM_NAME=$(pulumi stack output vm_name --stack staging)
VM_ZONE=$(pulumi stack output vm_zone --stack staging)

# Health checks
curl -sf "$OPENEMR_IP/meta/health/readyz"
curl -sf "$OPENEMR_IP/agent/health"

# Cloud SQL status
gcloud sql instances describe openemr-sql-* --project=openemr-agent-staging --format='value(state)'

# VM status
gcloud compute instances describe "$VM_NAME" --zone="$VM_ZONE" --project=openemr-agent-staging --format='value(status)'

# Pulumi stack status
pulumi stack --stack staging
```

### `deploy` — Full deployment via Pulumi

Run full infrastructure deployment:

```bash
cd infra
pulumi up --stack staging --yes
```

This creates/updates all GCP resources: Cloud SQL, Compute Engine VM, Artifact Registry, Secret Manager secrets.

### `update` — Rebuild and redeploy AI Agent only

Most common operation — rebuild and deploy just the AI Agent:

```bash
GCP_REGION=us-central1
REGISTRY=$GCP_REGION-docker.pkg.dev/openemr-agent-staging/openemr

# Build and push
cd ai-agent
docker buildx build --platform linux/amd64 -t $REGISTRY/ai-agent:latest --push .

# Reset VM to pick up new image
cd ../infra && export PULUMI_CONFIG_PASSPHRASE=""
VM_NAME=$(pulumi stack output vm_name --stack staging)
VM_ZONE=$(pulumi stack output vm_zone --stack staging)
gcloud compute instances reset "$VM_NAME" --zone="$VM_ZONE" --project=openemr-agent-staging

# Wait and verify
OPENEMR_IP=$(pulumi stack output openemr_url --stack staging)
sleep 30 && curl -sf "$OPENEMR_IP/agent/health"
```

### `logs [openemr|ai-agent]` — Tail container logs on the VM

```bash
cd infra && export PULUMI_CONFIG_PASSPHRASE=""
VM_NAME=$(pulumi stack output vm_name --stack staging)
VM_ZONE=$(pulumi stack output vm_zone --stack staging)

# AI Agent logs (default)
gcloud compute ssh "$VM_NAME" --zone="$VM_ZONE" --project=openemr-agent-staging \
  --command 'sudo docker logs --tail 100 -f $(sudo docker ps -qf name=ai-agent)'

# OpenEMR logs
gcloud compute ssh "$VM_NAME" --zone="$VM_ZONE" --project=openemr-agent-staging \
  --command 'sudo docker logs --tail 100 -f $(sudo docker ps -qf name=openemr)'
```

### `teardown` — Destroy all resources

**WARNING: This destroys all staging resources including the database.**

```bash
cd infra
pulumi destroy --stack staging --yes
```

### `seed` — Seed demo data

Run the seed script against Cloud SQL:

```bash
# Get Cloud SQL connection info
CONNECTION=$(gcloud sql instances describe openemr-sql-* --project=openemr-agent-staging --format='value(connectionName)')

# Use cloud-sql-proxy for local connection
cloud-sql-proxy $CONNECTION &
sleep 3

# Run seed script
cd ai-agent
uv run python scripts/seed_data.py --host=127.0.0.1 --port=3306

kill %1  # stop proxy
```

### `preview` — Preview pending changes

```bash
cd infra
pulumi preview --stack staging
```
