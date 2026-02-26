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
