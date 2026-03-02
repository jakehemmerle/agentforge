#!/bin/bash
set -euo pipefail

PROJECT_ID="__PROJECT_ID__"
CLOUD_SQL_CONNECTION="__CLOUD_SQL_CONNECTION__"
OPENEMR_IMAGE="__OPENEMR_IMAGE__"
AI_AGENT_IMAGE="__AI_AGENT_IMAGE__"
STATIC_IP="__STATIC_IP__"
DB_PASSWORD="$(printf '%s' '__DB_PASSWORD_B64__' | base64 -d)"

# Install runtime dependencies once.
if ! command -v docker >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg jq

  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $VERSION_CODENAME stable"     > /etc/apt/sources.list.d/docker.list

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

mkdir -p /opt/openemr
DATA_ROOT="/srv/openemr-data"

# Attach and mount persistent data disk if present.
DISK_DEVICE="/dev/disk/by-id/google-openemr-data"
if [ -b "$DISK_DEVICE" ]; then
  if ! blkid "$DISK_DEVICE" >/dev/null 2>&1; then
    mkfs.ext4 -F "$DISK_DEVICE"
  fi
  mkdir -p /mnt/disks/openemr-data
  if ! grep -q "$DISK_DEVICE /mnt/disks/openemr-data" /etc/fstab; then
    echo "$DISK_DEVICE /mnt/disks/openemr-data ext4 defaults,nofail,discard 0 2" >> /etc/fstab
  fi
  mount /mnt/disks/openemr-data || mount -a
  DATA_ROOT="/mnt/disks/openemr-data"
fi

# Ensure persistent directories for OpenEMR crypto keys exist.
# These must survive container rebuilds so the drive keys stay in sync
# with encrypted values in Cloud SQL (oauth2key, oauth2passphrase).
SITE_DIR="$DATA_ROOT/openemr-site"
mkdir -p "$SITE_DIR/documents/certificates"
mkdir -p "$SITE_DIR/documents/logs_and_misc/methods"
chown -R 1000:101 "$SITE_DIR"

# Helper: fetch latest secret version from Secret Manager.
get_access_token() {
  curl -sS -H "Metadata-Flavor: Google"     "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"     | jq -r '.access_token'
}

fetch_secret() {
  local secret_name="$1"
  local fallback="${2:-}"
  local token response payload decoded

  token="$(get_access_token)"
  response="$(curl -fsS -H "Authorization: Bearer $token"     "https://secretmanager.googleapis.com/v1/projects/${PROJECT_ID}/secrets/${secret_name}/versions/latest:access"     2>/dev/null || true)"
  payload="$(echo "$response" | jq -r '.payload.data // empty')"

  if [ -n "$payload" ]; then
    decoded="$(echo "$payload" | tr '_-' '/+' | base64 -d 2>/dev/null || true)"
    if [ -n "$decoded" ]; then
      printf '%s' "$decoded"
      return 0
    fi
  fi

  printf '%s' "$fallback"
}

artifact_registry_login() {
  local image_ref registry_host token
  image_ref="$1"
  registry_host="$(echo "$image_ref" | cut -d'/' -f1)"
  token="$(get_access_token)"

  echo "$token" | docker login -u oauth2accesstoken --password-stdin "https://$registry_host"
}

artifact_registry_login "$OPENEMR_IMAGE"
artifact_registry_login "$AI_AGENT_IMAGE"

ANTHROPIC_API_KEY="$(fetch_secret ANTHROPIC_API_KEY '')"
LANGSMITH_API_KEY="$(fetch_secret LANGSMITH_API_KEY '')"
AI_AGENT_API_KEY="$(fetch_secret AI_AGENT_API_KEY '')"
OPENEMR_CLIENT_ID="$(fetch_secret OPENEMR_CLIENT_ID '')"
OPENEMR_CLIENT_SECRET="$(fetch_secret OPENEMR_CLIENT_SECRET '')"

cat > /opt/openemr/.env <<EOF
OPENEMR_IMAGE=${OPENEMR_IMAGE}
AI_AGENT_IMAGE=${AI_AGENT_IMAGE}
CLOUD_SQL_CONNECTION=${CLOUD_SQL_CONNECTION}
DATA_ROOT=${DATA_ROOT}
DB_PASSWORD=${DB_PASSWORD}
OPENEMR_EXTERNAL_URL=http://${STATIC_IP}
AI_AGENT_EXTERNAL_URL=http://${STATIC_IP}/agent
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
LANGSMITH_API_KEY=${LANGSMITH_API_KEY}
AI_AGENT_API_KEY=${AI_AGENT_API_KEY}
OPENEMR_CLIENT_ID=${OPENEMR_CLIENT_ID}
OPENEMR_CLIENT_SECRET=${OPENEMR_CLIENT_SECRET}
EOF

cat > /opt/openemr/nginx.conf <<'NGINX'
events {}

http {
  client_max_body_size 10m;

  upstream openemr_upstream {
    server openemr:80;
  }

  upstream ai_agent_upstream {
    server ai-agent:8350;
  }

  server {
    listen 80;
    server_name _;

    location = /agent {
      return 302 /agent/;
    }

    location /agent/ {
      proxy_pass http://ai_agent_upstream/;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_buffering off;
      proxy_read_timeout 3600;
    }

    location / {
      proxy_pass http://openemr_upstream;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
    }
  }
}
NGINX

cat > /opt/openemr/docker-compose.yml <<'COMPOSE'
services:
  cloud-sql-proxy:
    image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.18.3
    command:
      - "--structured-logs"
      - "--address=0.0.0.0"
      - "--port=3306"
      - "${CLOUD_SQL_CONNECTION}"
    restart: always

  openemr:
    image: "${OPENEMR_IMAGE}"
    depends_on:
      - cloud-sql-proxy
    environment:
      MYSQL_HOST: cloud-sql-proxy
      MYSQL_PORT: 3306
      MYSQL_ROOT_PASS: "${DB_PASSWORD}"
      MYSQL_USER: openemr
      MYSQL_PASS: "${DB_PASSWORD}"
      MYSQL_DATABASE: openemr
      OE_USER: admin
      OE_PASS: pass
      OPENEMR_SETTING_rest_api: "1"
      OPENEMR_SETTING_rest_fhir_api: "1"
      OPENEMR_SETTING_rest_portal_api: "1"
      OPENEMR_SETTING_rest_system_scopes_api: "1"
      OPENEMR_SETTING_oauth_password_grant: "3"
      AI_AGENT_URL: "${AI_AGENT_EXTERNAL_URL}"
      AI_AGENT_API_KEY: "${AI_AGENT_API_KEY}"
    volumes:
      - ${DATA_ROOT}/openemr-site/documents/certificates:/var/www/localhost/htdocs/openemr/sites/default/documents/certificates
      - ${DATA_ROOT}/openemr-site/documents/logs_and_misc/methods:/var/www/localhost/htdocs/openemr/sites/default/documents/logs_and_misc/methods
    restart: always

  ai-agent:
    image: "${AI_AGENT_IMAGE}"
    depends_on:
      - cloud-sql-proxy
      - openemr
    environment:
      API_KEY: "${AI_AGENT_API_KEY}"
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"
      LANGSMITH_API_KEY: "${LANGSMITH_API_KEY}"
      LANGSMITH_TRACING: "true"
      LANGSMITH_PROJECT: "openemr-agent"
      OPENEMR_BASE_URL: "http://openemr"
      CORS_ORIGINS: "${OPENEMR_EXTERNAL_URL}"
      DB_HOST: cloud-sql-proxy
      DB_PORT: 3306
      DB_NAME: openemr
      DB_USER: openemr
      DB_PASSWORD: "${DB_PASSWORD}"
      OPENEMR_CLIENT_ID: "${OPENEMR_CLIENT_ID}"
      OPENEMR_CLIENT_SECRET: "${OPENEMR_CLIENT_SECRET}"
    restart: always

  gateway:
    image: nginx:1.27-alpine
    depends_on:
      - openemr
      - ai-agent
    ports:
      - "80:80"
    volumes:
      - /opt/openemr/nginx.conf:/etc/nginx/nginx.conf:ro
    restart: always
COMPOSE

cd /opt/openemr

docker compose --env-file /opt/openemr/.env -f /opt/openemr/docker-compose.yml pull
docker compose --env-file /opt/openemr/.env -f /opt/openemr/docker-compose.yml up -d --remove-orphans

docker image prune -f || true

# ---------------------------------------------------------------------------
# Self-healing: detect and fix crypto key / OAuth credential mismatches
# ---------------------------------------------------------------------------
# Disable strict error handling — self-healing is best-effort; containers
# should stay running even if healing fails so CI can report the real error.
set +e

DC="docker compose --env-file /opt/openemr/.env -f /opt/openemr/docker-compose.yml"

log() { echo "[self-heal] $(date '+%H:%M:%S') $*"; }

OPENEMR_URL="http://localhost"
PROBE_CLIENT_NAME="openemr-ai-agent-probe"
CLIENT_NAME="openemr-ai-agent"
OAUTH_SCOPES="openid api:oemr user/appointment.read user/encounter.read user/patient.read user/insurance.read user/vital.read user/soap_note.read user/AllergyIntolerance.read user/Condition.read user/MedicationRequest.read"

CERT_DIR="$DATA_ROOT/openemr-site/documents/certificates"
METHODS_DIR="$DATA_ROOT/openemr-site/documents/logs_and_misc/methods"

# MySQL helper — runs SQL against the openemr database via the OpenEMR container
# (which has the mysql/mariadb client installed).
run_sql() {
  $DC exec -T openemr sh -c \
    "mysql -h cloud-sql-proxy -u openemr -p'${DB_PASSWORD}' openemr -sNe \"$1\"" 2>/dev/null
}

# Write a secret version to Secret Manager via REST API.
write_secret() {
  local secret_name="$1" value="$2"
  local token payload
  token="$(get_access_token)"
  payload="$(printf '%s' "$value" | base64 -w0)"
  curl -fsS -X POST \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "{\"payload\":{\"data\":\"$payload\"}}" \
    "https://secretmanager.googleapis.com/v1/projects/${PROJECT_ID}/secrets/${secret_name}:addVersion" \
    >/dev/null
}

# ---- wait_for_install ------------------------------------------------------
# Wait for OpenEMR to be fully installed (readyz installed=true).  The first
# boot auto-setup can take a while on a fresh DB.  Returns 0 if installed,
# 1 if timed out.
OPENEMR_INSTALLED=false
wait_for_install() {
  if [ "$OPENEMR_INSTALLED" = "true" ]; then return 0; fi
  log "Waiting for OpenEMR to be installed..."
  local i readyz_json installed
  for i in $(seq 1 90); do
    readyz_json="$(curl -sS "$OPENEMR_URL/meta/health/readyz" 2>/dev/null || echo "{}")"
    installed="$(echo "$readyz_json" | jq -r '.checks.installed // false')"
    if [ "$installed" = "true" ]; then
      log "OpenEMR installed (attempt $i)"
      OPENEMR_INSTALLED=true
      return 0
    fi
    sleep 5
  done
  log "WARNING: OpenEMR not installed after 90 attempts"
  return 1
}

# ---- ensure_oauth_keys ----------------------------------------------------
# Probe the OAuth registration endpoint to verify filesystem crypto keys and
# DB keys are in sync.  Only HTTP 500 indicates a key mismatch — other codes
# mean the API isn't ready yet (not a key issue).
ensure_oauth_keys() {
  if ! wait_for_install; then
    log "Skipping key probe — OpenEMR not installed"
    return 0
  fi

  local attempt
  for attempt in 1 2 3; do
    log "Probe attempt $attempt: testing OAuth registration endpoint..."

    local probe_resp
    probe_resp="$(curl -sS -o /dev/null -w '%{http_code}' \
      -X POST "$OPENEMR_URL/oauth2/default/registration" \
      -H 'Content-Type: application/json' \
      -d "{\"application_type\":\"private\",\"client_name\":\"$PROBE_CLIENT_NAME\",\"redirect_uris\":[\"https://localhost\"],\"scope\":\"$OAUTH_SCOPES\"}" \
      2>/dev/null || echo "000")"

    if [ "$probe_resp" = "200" ] || [ "$probe_resp" = "201" ]; then
      log "Probe succeeded (HTTP $probe_resp) — keys are consistent"
      # Clean up probe client from DB
      run_sql "DELETE FROM oauth_clients WHERE client_name='$PROBE_CLIENT_NAME'" || true
      return 0
    fi

    # Only treat 500 as a key mismatch.  Other codes (404, 400, etc.)
    # mean the API isn't ready or the request is malformed — not a key issue.
    if [ "$probe_resp" != "500" ]; then
      log "Probe returned HTTP $probe_resp (not 500) — not a key mismatch, skipping healing"
      return 0
    fi

    log "Probe returned HTTP 500 — clearing keys and restarting OpenEMR..."

    # Clear DB crypto keys
    run_sql "DELETE FROM \`keys\`" || log "WARNING: failed to clear keys table"

    # Clear drive crypto keys
    rm -f "$CERT_DIR/oaprivate.key" "$CERT_DIR/oapublic.key" 2>/dev/null || true
    # Clear all method key files (sevena, sevenb, etc.)
    find "$METHODS_DIR" -type f -delete 2>/dev/null || true

    # Restart OpenEMR to regenerate fresh matched keys
    $DC restart openemr
    log "Waiting for OpenEMR to come back..."
    for i in $(seq 1 60); do
      if curl -fsS "$OPENEMR_URL/meta/health/readyz" >/dev/null 2>&1; then
        break
      fi
      sleep 5
    done
  done

  log "WARNING: OAuth key healing failed after 3 attempts — continuing anyway"
}

# ---- ensure_oauth_client ---------------------------------------------------
# Verify the AI-agent's OAuth client credentials work.  If not, register a new
# client, enable it, write the credentials to Secret Manager, update the .env,
# and restart the ai-agent container.
ensure_oauth_client() {
  if ! wait_for_install; then
    log "Skipping OAuth client check — OpenEMR not installed"
    return 0
  fi
  log "Checking OAuth client credentials..."

  # Fast path: test existing credentials
  if [ -n "$OPENEMR_CLIENT_ID" ] && [ -n "$OPENEMR_CLIENT_SECRET" ]; then
    local token_resp
    token_resp="$(curl -sS -X POST "$OPENEMR_URL/oauth2/default/token" \
      -d "grant_type=password&username=admin&password=pass&client_id=$OPENEMR_CLIENT_ID&client_secret=$OPENEMR_CLIENT_SECRET&scope=$OAUTH_SCOPES&user_role=users" \
      2>/dev/null || echo "{}")"
    if echo "$token_resp" | jq -e '.access_token' >/dev/null 2>&1; then
      log "Existing OAuth credentials are valid — skipping registration"
      return 0
    fi
    log "Existing credentials failed — re-registering"
  else
    log "No OAuth credentials found — registering new client"
  fi

  # Register a new OAuth client
  local reg_resp
  reg_resp="$(curl -sS -X POST "$OPENEMR_URL/oauth2/default/registration" \
    -H 'Content-Type: application/json' \
    -d "{\"application_type\":\"private\",\"client_name\":\"$CLIENT_NAME\",\"redirect_uris\":[\"https://localhost\"],\"scope\":\"$OAUTH_SCOPES\"}" \
    2>/dev/null || echo "{}")"

  local new_client_id new_client_secret
  new_client_id="$(echo "$reg_resp" | jq -r '.client_id // empty')"
  new_client_secret="$(echo "$reg_resp" | jq -r '.client_secret // empty')"

  if [ -z "$new_client_id" ] || [ -z "$new_client_secret" ]; then
    log "WARNING: OAuth client registration failed — response: $reg_resp"
    return 1
  fi
  log "Registered OAuth client: ${new_client_id:0:20}..."

  # Enable the client (new registrations default to disabled)
  run_sql "UPDATE oauth_clients SET is_enabled=1 WHERE client_name='$CLIENT_NAME'" \
    || log "WARNING: failed to enable OAuth client"

  # Write new credentials to Secret Manager
  write_secret "OPENEMR_CLIENT_ID" "$new_client_id" \
    && log "Wrote OPENEMR_CLIENT_ID to Secret Manager" \
    || log "WARNING: failed to write OPENEMR_CLIENT_ID to Secret Manager"
  write_secret "OPENEMR_CLIENT_SECRET" "$new_client_secret" \
    && log "Wrote OPENEMR_CLIENT_SECRET to Secret Manager" \
    || log "WARNING: failed to write OPENEMR_CLIENT_SECRET to Secret Manager"

  # Update local .env and restart ai-agent
  OPENEMR_CLIENT_ID="$new_client_id"
  OPENEMR_CLIENT_SECRET="$new_client_secret"
  sed -i "s|^OPENEMR_CLIENT_ID=.*|OPENEMR_CLIENT_ID=${new_client_id}|" /opt/openemr/.env
  sed -i "s|^OPENEMR_CLIENT_SECRET=.*|OPENEMR_CLIENT_SECRET=${new_client_secret}|" /opt/openemr/.env

  $DC restart ai-agent
  log "Restarted ai-agent with new credentials"

  # Validate new credentials
  sleep 5
  local validate_resp
  validate_resp="$(curl -sS -X POST "$OPENEMR_URL/oauth2/default/token" \
    -d "grant_type=password&username=admin&password=pass&client_id=$new_client_id&client_secret=$new_client_secret&scope=$OAUTH_SCOPES&user_role=users" \
    2>/dev/null || echo "{}")"
  if echo "$validate_resp" | jq -e '.access_token' >/dev/null 2>&1; then
    log "New OAuth credentials validated successfully"
    return 0
  fi

  log "WARNING: New OAuth credentials failed validation"
  return 1
}

ensure_oauth_keys || log "WARNING: ensure_oauth_keys did not fully succeed"
ensure_oauth_client || log "WARNING: ensure_oauth_client did not fully succeed"
log "Self-healing complete"
