# Local Staging Deploy Runbook (Manual, No CI/CD)

This runbook is for manual deploys from a local machine to GCP staging.

It covers:

1. Preparing injected OpenEMR frontend/backend changes
2. Building OpenEMR + AI agent images locally
3. Pushing images to Artifact Registry
4. Deploying with Pulumi
5. Verifying health and injected artifacts on the running VM

## Scope and assumptions

- Target stack: `staging`
- Target project: `openemr-agent-staging`
- Target region: `us-central1`
- You are running commands from repo root (the `agentforge/` repo)

## Prerequisites

- `docker` (with buildx support; on Apple Silicon, the default `desktop-linux` builder handles `--platform linux/amd64` via emulation)
- `gcloud` authenticated with permissions for Artifact Registry, Compute, Cloud SQL, Secret Manager
- `pulumi` authenticated (`PULUMI_ACCESS_TOKEN` if using Pulumi Cloud backend)
- `python3`

Recommended:

```bash
export PULUMI_CONFIG_PASSPHRASE=""
```

## Variables for this run

Pick a unique deploy tag. Use git SHA by default.

```bash
export GCP_PROJECT="openemr-agent-staging"
export GCP_REGION="us-central1"
export PULUMI_STACK="staging"
export REGISTRY="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/openemr"
export IMAGE_TAG="$(git rev-parse HEAD)"
```

If you want a human tag:

```bash
export IMAGE_TAG="staging-$(date -u +%Y%m%d-%H%M%S)"
```

## Step 1: Apply injectables

```bash
./injectables/openemr-customize.sh apply
```

Sanity-check required injected files exist:

```bash
test -f openemr/interface/main/tabs/main.php && echo "OK: main.php" || echo "MISSING: main.php"
test -f openemr/interface/main/tabs/js/ai-chat-widget.js && echo "OK: widget JS" || echo "MISSING: widget JS"
test -f openemr/interface/main/tabs/css/ai-chat-widget.css && echo "OK: widget CSS" || echo "MISSING: widget CSS"
test -f openemr/src/Common/Auth/OpenIDConnect/Repositories/UserRepository.php && echo "OK: UserRepository" || echo "MISSING: UserRepository"
```

## Step 2: Authenticate Docker to Artifact Registry

```bash
gcloud auth configure-docker "${GCP_REGION}-docker.pkg.dev"
```

## Step 3: Build and push OpenEMR image (frontend + backend)

```bash
docker buildx build \
  --platform linux/amd64 \
  -t "${REGISTRY}/openemr:${IMAGE_TAG}" \
  -t "${REGISTRY}/openemr:latest" \
  --push \
  .
```

## Step 4: Build and push AI agent image

```bash
docker buildx build \
  --platform linux/amd64 \
  -t "${REGISTRY}/ai-agent:${IMAGE_TAG}" \
  -t "${REGISTRY}/ai-agent:latest" \
  --push \
  ./ai-agent
```

## Step 5: Deploy infra with pinned image tags

```bash
cd infra
pulumi stack select "${PULUMI_STACK}"
pulumi config set openemr-agent-staging:openemrImageTag "${IMAGE_TAG}" --stack "${PULUMI_STACK}"
pulumi config set openemr-agent-staging:aiAgentImageTag "${IMAGE_TAG}" --stack "${PULUMI_STACK}"
pulumi up --stack "${PULUMI_STACK}" --yes
```

Read outputs:

```bash
export OPENEMR_IP="$(pulumi stack output openemr_ip --stack "${PULUMI_STACK}")"
export VM_NAME="$(pulumi stack output vm_name --stack "${PULUMI_STACK}")"
export VM_ZONE="$(pulumi stack output vm_zone --stack "${PULUMI_STACK}")"
cd ..
```

## Step 6: Watch VM startup logs

The VM startup script installs Docker, pulls images, and starts containers.
Wait for it to finish before checking endpoints. Poll the serial log for the
completion marker (`Finished running startup scripts`):

```bash
echo "Waiting for startup script to finish..."
for i in $(seq 1 30); do
  if gcloud compute instances get-serial-port-output "${VM_NAME}" \
       --zone "${VM_ZONE}" --project "${GCP_PROJECT}" 2>&1 \
     | grep -q "Finished running startup scripts"; then
    echo "Startup script finished."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "WARNING: Timed out waiting for startup script (10 min)."
    echo "Check logs manually:"
    echo "  gcloud compute instances get-serial-port-output ${VM_NAME} --zone ${VM_ZONE} --project ${GCP_PROJECT} | tail -40"
  fi
  sleep 20
done
```

If the script fails (e.g. image pull auth error), inspect the full log:

```bash
gcloud compute instances get-serial-port-output "${VM_NAME}" \
  --zone "${VM_ZONE}" --project "${GCP_PROJECT}" 2>&1 | tail -60
```

## Step 7: Verify external endpoints

Once the startup script has finished, poll until all 3 endpoints respond
(containers may still need a few seconds to become healthy):

```bash
for i in $(seq 1 30); do
  echo "--- Attempt $i/30 ---"
  ok=true
  curl -fsS --connect-timeout 5 --max-time 10 "http://${OPENEMR_IP}/meta/health/readyz" 2>/dev/null && echo " [OK] readyz" || { echo " [WAIT] readyz"; ok=false; }
  curl -fsS --connect-timeout 5 --max-time 10 "http://${OPENEMR_IP}/agent/health" 2>/dev/null && echo " [OK] agent" || { echo " [WAIT] agent"; ok=false; }
  curl -fsS --connect-timeout 5 --max-time 10 "http://${OPENEMR_IP}/interface/main/tabs/js/ai-chat-widget.js" >/dev/null 2>&1 && echo " [OK] widget" || { echo " [WAIT] widget"; ok=false; }
  $ok && echo "=== ALL PASSED ===" && break
  sleep 20
done
```

> **Note:** The readyz `installed` check may report `false` even when OpenEMR
> is fully functional. This is an upstream variable-collision bug in
> `library/sql.inc.php` (it overwrites the `$config` flag). The other checks
> (`database`, `oauth_keys`, `filesystem`, etc.) are reliable.

## Step 8: Verify injected artifacts inside the live OpenEMR container

```bash
gcloud compute ssh "${VM_NAME}" --zone "${VM_ZONE}" --project "${GCP_PROJECT}" --command '
set -euo pipefail
cid="$(sudo docker ps --filter "name=openemr-openemr" --format "{{.ID}}" | head -n1)"
if [ -z "${cid}" ]; then
  cid="$(sudo docker ps --filter "name=openemr" --format "{{.ID}}" | head -n1)"
fi
[ -n "${cid}" ]
sudo docker exec "${cid}" test -f /var/www/localhost/htdocs/openemr/interface/main/tabs/js/ai-chat-widget.js
sudo docker exec "${cid}" test -f /var/www/localhost/htdocs/openemr/interface/main/tabs/css/ai-chat-widget.css
sudo docker exec "${cid}" grep -q "ai-chat-widget.js" /var/www/localhost/htdocs/openemr/interface/main/tabs/main.php
sudo docker exec "${cid}" grep -q "USER_ROLE_SYSTEM" /var/www/localhost/htdocs/openemr/src/Common/Auth/OpenIDConnect/Repositories/UserRepository.php
echo "All injected artifacts verified."
'
```

## Repeatable process for new changes

For every new change set, repeat Steps 1 through 7 with a new `IMAGE_TAG`.

## Rollback

Set `IMAGE_TAG` to a known-good previous tag and repeat Steps 5 through 7.

> **Caveat:** Each deploy pushes `:latest` in addition to the SHA tag. If you
> need to roll back, always pin to an explicit SHA tag — do not rely on
> `:latest` as it points to the most recent (possibly broken) build.
