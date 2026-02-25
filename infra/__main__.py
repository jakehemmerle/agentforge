"""Pulumi program for OpenEMR AI Agent staging infrastructure on GCP."""

import base64

import pulumi
import pulumi_gcp as gcp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

config = pulumi.Config()
gcp_config = pulumi.Config("gcp")

project = gcp_config.require("project")
region = gcp_config.require("region")

# Database
# NOTE: keep fallback for backward compatibility with existing stack state.
# Set `dbPassword` as a Pulumi secret in all environments.
db_password = config.get_secret("dbPassword") or pulumi.Output.secret("change-me-on-first-deploy")
db_tier = config.get("dbTier") or "db-f1-micro"

# Compute Engine
vm_name = config.get("vmName") or "openemr-staging-vm"
vm_zone = config.get("vmZone") or f"{region}-a"
vm_machine_type = config.get("vmMachineType") or "e2-standard-4"
vm_boot_disk_gb = config.get_int("vmBootDiskGb") or 50
vm_data_disk_gb = config.get_int("vmDataDiskGb") or 100
network_name = config.get("network") or "default"
subnetwork_name = config.get("subnetwork")
ssh_source_ranges = config.get_object("sshSourceRanges") or ["0.0.0.0/0"]

# Images
openemr_image_tag = config.get("openemrImageTag") or "latest"
ai_agent_image_tag = config.get("aiAgentImageTag") or "latest"

# ---------------------------------------------------------------------------
# Artifact Registry
# ---------------------------------------------------------------------------

registry = gcp.artifactregistry.Repository(
    "openemr-registry",
    repository_id="openemr",
    location=region,
    format="DOCKER",
    description="Docker images for OpenEMR and AI Agent",
)

registry_path = pulumi.Output.concat(
    region, "-docker.pkg.dev/", project, "/", registry.repository_id
)
openemr_image = pulumi.Output.concat(
    region, "-docker.pkg.dev/", project, "/openemr/openemr:", openemr_image_tag
)
ai_agent_image = pulumi.Output.concat(
    region, "-docker.pkg.dev/", project, "/openemr/ai-agent:", ai_agent_image_tag
)

# ---------------------------------------------------------------------------
# Cloud SQL — MySQL 8.0
# ---------------------------------------------------------------------------

sql_instance = gcp.sql.DatabaseInstance(
    "openemr-sql",
    database_version="MYSQL_8_0",
    region=region,
    deletion_protection=False,
    settings=gcp.sql.DatabaseInstanceSettingsArgs(
        tier=db_tier,
        ip_configuration=gcp.sql.DatabaseInstanceSettingsIpConfigurationArgs(
            ipv4_enabled=True,
        ),
        backup_configuration=gcp.sql.DatabaseInstanceSettingsBackupConfigurationArgs(
            enabled=True,
            binary_log_enabled=True,
        ),
    ),
)

sql_database = gcp.sql.Database(
    "openemr-db",
    name="openemr",
    instance=sql_instance.name,
)

db_password_resource = gcp.sql.User(
    "openemr-db-user",
    name="openemr",
    instance=sql_instance.name,
    password=db_password,
)

db_root_user = gcp.sql.User(
    "openemr-db-root",
    name="root",
    instance=sql_instance.name,
    password=db_password,
)

# ---------------------------------------------------------------------------
# Secret Manager — secret shells (versions managed externally)
# ---------------------------------------------------------------------------

SECRET_NAMES = [
    "ANTHROPIC_API_KEY",
    "LANGSMITH_API_KEY",
    "AI_AGENT_API_KEY",
    "OPENEMR_CLIENT_ID",
    "OPENEMR_CLIENT_SECRET",
]

secrets: dict[str, gcp.secretmanager.Secret] = {}
for name in SECRET_NAMES:
    secrets[name] = gcp.secretmanager.Secret(
        f"secret-{name.lower().replace('_', '-')}",
        secret_id=name,
        replication=gcp.secretmanager.SecretReplicationArgs(
            auto=gcp.secretmanager.SecretReplicationAutoArgs(),
        ),
    )

# ---------------------------------------------------------------------------
# Service Account + IAM for VM runtime
# ---------------------------------------------------------------------------

vm_service_account = gcp.serviceaccount.Account(
    "openemr-vm-sa",
    account_id="openemr-vm-sa",
    display_name="OpenEMR staging VM runtime",
)

project_roles = [
    "roles/cloudsql.client",
    "roles/artifactregistry.reader",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
]

vm_project_iam_members: list[pulumi.Resource] = []
for role in project_roles:
    vm_project_iam_members.append(
        gcp.projects.IAMMember(
            f"openemr-vm-role-{role.split('/')[-1].replace('.', '-')}",
            project=project,
            role=role,
            member=vm_service_account.email.apply(lambda email: f"serviceAccount:{email}"),
        )
    )

vm_secret_iam_members: list[pulumi.Resource] = []
for secret_name, secret in secrets.items():
    vm_secret_iam_members.append(
        gcp.secretmanager.SecretIamMember(
            f"openemr-vm-secret-access-{secret_name.lower().replace('_', '-')}",
            secret_id=secret.id,
            role="roles/secretmanager.secretAccessor",
            member=vm_service_account.email.apply(lambda email: f"serviceAccount:{email}"),
        )
    )

# ---------------------------------------------------------------------------
# Compute Engine networking
# ---------------------------------------------------------------------------

openemr_static_ip = gcp.compute.Address(
    "openemr-static-ip",
    name="openemr-static-ip",
    region=region,
    description="Static IP for OpenEMR + AI Agent gateway",
)

gcp.compute.Firewall(
    "openemr-http-firewall",
    name="openemr-http",
    network=network_name,
    direction="INGRESS",
    source_ranges=["0.0.0.0/0"],
    target_tags=["openemr-vm"],
    allows=[
        gcp.compute.FirewallAllowArgs(protocol="tcp", ports=["80"]),
    ],
)

gcp.compute.Firewall(
    "openemr-ssh-firewall",
    name="openemr-ssh",
    network=network_name,
    direction="INGRESS",
    source_ranges=ssh_source_ranges,
    target_tags=["openemr-vm"],
    allows=[
        gcp.compute.FirewallAllowArgs(protocol="tcp", ports=["22"]),
    ],
)

openemr_data_disk = gcp.compute.Disk(
    "openemr-data-disk",
    name="openemr-data",
    zone=vm_zone,
    size=vm_data_disk_gb,
    type="pd-balanced",
)


# ---------------------------------------------------------------------------
# Startup script
# ---------------------------------------------------------------------------


def _render_startup_script(args: tuple[str, str, str, str, str, str]) -> str:
    (
        project_id,
        connection_name,
        db_password_plain,
        openemr_image_name,
        ai_agent_image_name,
        static_ip,
    ) = args

    db_password_b64 = base64.b64encode(db_password_plain.encode("utf-8")).decode("ascii")

    return f"""#!/bin/bash
set -euo pipefail

PROJECT_ID=\"{project_id}\"
CLOUD_SQL_CONNECTION=\"{connection_name}\"
OPENEMR_IMAGE=\"{openemr_image_name}\"
AI_AGENT_IMAGE=\"{ai_agent_image_name}\"
STATIC_IP=\"{static_ip}\"
DB_PASSWORD=\"$(printf '%s' '{db_password_b64}' | base64 -d)\"

# Install runtime dependencies once.
if ! command -v docker >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg jq

  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  . /etc/os-release
  echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $VERSION_CODENAME stable\" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

mkdir -p /opt/openemr
DATA_ROOT=\"/srv/openemr-data\"

# Attach and mount persistent data disk if present.
DISK_DEVICE=\"/dev/disk/by-id/google-openemr-data\"
if [ -b \"$DISK_DEVICE\" ]; then
  if ! blkid \"$DISK_DEVICE\" >/dev/null 2>&1; then
    mkfs.ext4 -F \"$DISK_DEVICE\"
  fi
  mkdir -p /mnt/disks/openemr-data
  if ! grep -q \"$DISK_DEVICE /mnt/disks/openemr-data\" /etc/fstab; then
    echo \"$DISK_DEVICE /mnt/disks/openemr-data ext4 defaults,nofail,discard 0 2\" >> /etc/fstab
  fi
  mount /mnt/disks/openemr-data || mount -a
  DATA_ROOT=\"/mnt/disks/openemr-data\"
fi
# Helper: fetch latest secret version from Secret Manager.
get_access_token() {{
  curl -sS -H \"Metadata-Flavor: Google\" \
    \"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token\" \
    | jq -r '.access_token'
}}

fetch_secret() {{
  local secret_name=\"$1\"
  local fallback=\"${{2:-}}\"
  local token response payload decoded

  token=\"$(get_access_token)\"
  response=\"$(curl -fsS -H \"Authorization: Bearer $token\" \
    \"https://secretmanager.googleapis.com/v1/projects/${{PROJECT_ID}}/secrets/${{secret_name}}/versions/latest:access\" \
    2>/dev/null || true)\"
  payload=\"$(echo \"$response\" | jq -r '.payload.data // empty')\"

  if [ -n \"$payload\" ]; then
    decoded=\"$(echo \"$payload\" | tr '_-' '/+' | base64 -d 2>/dev/null || true)\"
    if [ -n \"$decoded\" ]; then
      printf '%s' \"$decoded\"
      return 0
    fi
  fi

  printf '%s' \"$fallback\"
}}

artifact_registry_login() {{
  local image_ref registry_host token
  image_ref=\"$1\"
  registry_host=\"$(echo \"$image_ref\" | cut -d'/' -f1)\"
  token=\"$(get_access_token)\"

  echo \"$token\" | docker login -u oauth2accesstoken --password-stdin \"https://$registry_host\"
}}

artifact_registry_login \"$OPENEMR_IMAGE\"
artifact_registry_login \"$AI_AGENT_IMAGE\"

ANTHROPIC_API_KEY=\"$(fetch_secret ANTHROPIC_API_KEY '')\"
LANGSMITH_API_KEY=\"$(fetch_secret LANGSMITH_API_KEY '')\"
AI_AGENT_API_KEY=\"$(fetch_secret AI_AGENT_API_KEY '')\"
OPENEMR_CLIENT_ID=\"$(fetch_secret OPENEMR_CLIENT_ID '')\"
OPENEMR_CLIENT_SECRET=\"$(fetch_secret OPENEMR_CLIENT_SECRET '')\"

cat > /opt/openemr/.env <<EOF
OPENEMR_IMAGE=${{OPENEMR_IMAGE}}
AI_AGENT_IMAGE=${{AI_AGENT_IMAGE}}
CLOUD_SQL_CONNECTION=${{CLOUD_SQL_CONNECTION}}
DATA_ROOT=${{DATA_ROOT}}
DB_PASSWORD=${{DB_PASSWORD}}
OPENEMR_EXTERNAL_URL=http://${{STATIC_IP}}
AI_AGENT_EXTERNAL_URL=http://${{STATIC_IP}}/agent
ANTHROPIC_API_KEY=${{ANTHROPIC_API_KEY}}
LANGSMITH_API_KEY=${{LANGSMITH_API_KEY}}
AI_AGENT_API_KEY=${{AI_AGENT_API_KEY}}
OPENEMR_CLIENT_ID=${{OPENEMR_CLIENT_ID}}
OPENEMR_CLIENT_SECRET=${{OPENEMR_CLIENT_SECRET}}
EOF

cat > /opt/openemr/nginx.conf <<'NGINX'
events {{}}

http {{
  client_max_body_size 10m;

  upstream openemr_upstream {{
    server openemr:80;
  }}

  upstream ai_agent_upstream {{
    server ai-agent:8350;
  }}

  server {{
    listen 80;
    server_name _;

    location = /agent {{
      return 302 /agent/;
    }}

    location /agent/ {{
      proxy_pass http://ai_agent_upstream/;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_buffering off;
      proxy_read_timeout 3600;
    }}

    location / {{
      proxy_pass http://openemr_upstream;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
    }}
  }}
}}
NGINX

cat > /opt/openemr/docker-compose.yml <<'COMPOSE'
services:
  cloud-sql-proxy:
    image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.18.3
    command:
      - "--structured-logs"
      - "--address=0.0.0.0"
      - "--port=3306"
      - "${{CLOUD_SQL_CONNECTION}}"
    restart: always

  openemr:
    image: "${{OPENEMR_IMAGE}}"
    depends_on:
      - cloud-sql-proxy
    environment:
      MYSQL_HOST: cloud-sql-proxy
      MYSQL_PORT: 3306
      MYSQL_ROOT_PASS: "${{DB_PASSWORD}}"
      MYSQL_USER: openemr
      MYSQL_PASS: "${{DB_PASSWORD}}"
      MYSQL_DATABASE: openemr
      OE_USER: admin
      OE_PASS: pass
      OPENEMR_SETTING_rest_api: "1"
      OPENEMR_SETTING_rest_fhir_api: "1"
      OPENEMR_SETTING_rest_portal_api: "1"
      OPENEMR_SETTING_rest_system_scopes_api: "1"
      OPENEMR_SETTING_oauth_password_grant: "3"
      AI_AGENT_URL: "${{AI_AGENT_EXTERNAL_URL}}"
      AI_AGENT_API_KEY: "${{AI_AGENT_API_KEY}}"
    restart: always

  ai-agent:
    image: "${{AI_AGENT_IMAGE}}"
    depends_on:
      - cloud-sql-proxy
      - openemr
    environment:
      API_KEY: "${{AI_AGENT_API_KEY}}"
      ANTHROPIC_API_KEY: "${{ANTHROPIC_API_KEY}}"
      LANGSMITH_API_KEY: "${{LANGSMITH_API_KEY}}"
      LANGSMITH_TRACING: "true"
      LANGSMITH_PROJECT: "openemr-agent"
      OPENEMR_BASE_URL: "http://openemr"
      CORS_ORIGINS: "${{OPENEMR_EXTERNAL_URL}}"
      DB_HOST: cloud-sql-proxy
      DB_PORT: 3306
      DB_NAME: openemr
      DB_USER: openemr
      DB_PASSWORD: "${{DB_PASSWORD}}"
      OPENEMR_CLIENT_ID: "${{OPENEMR_CLIENT_ID}}"
      OPENEMR_CLIENT_SECRET: "${{OPENEMR_CLIENT_SECRET}}"
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
"""


startup_script = pulumi.Output.all(
    project,
    sql_instance.connection_name,
    db_password,
    openemr_image,
    ai_agent_image,
    openemr_static_ip.address,
).apply(_render_startup_script)

# ---------------------------------------------------------------------------
# Compute Engine VM
# ---------------------------------------------------------------------------

openemr_vm = gcp.compute.Instance(
    "openemr-vm",
    name=vm_name,
    zone=vm_zone,
    machine_type=vm_machine_type,
    allow_stopping_for_update=True,
    boot_disk=gcp.compute.InstanceBootDiskArgs(
        auto_delete=True,
        initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(
            image="projects/debian-cloud/global/images/family/debian-12",
            size=vm_boot_disk_gb,
            type="pd-balanced",
        ),
    ),
    attached_disks=[
        gcp.compute.InstanceAttachedDiskArgs(
            source=openemr_data_disk.id,
            device_name="openemr-data",
        )
    ],
    network_interfaces=[
        gcp.compute.InstanceNetworkInterfaceArgs(
            network=network_name,
            subnetwork=subnetwork_name,
            access_configs=[
                gcp.compute.InstanceNetworkInterfaceAccessConfigArgs(
                    nat_ip=openemr_static_ip.address,
                )
            ],
        )
    ],
    service_account=gcp.compute.InstanceServiceAccountArgs(
        email=vm_service_account.email,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    ),
    metadata_startup_script=startup_script,
    tags=["openemr-vm"],
    opts=pulumi.ResourceOptions(
        depends_on=[*vm_project_iam_members, *vm_secret_iam_members],
    ),
)

# ---------------------------------------------------------------------------
# Stack Outputs
# ---------------------------------------------------------------------------

pulumi.export("openemr_ip", openemr_static_ip.address)
pulumi.export("openemr_url", pulumi.Output.concat("http://", openemr_static_ip.address))
pulumi.export("ai_agent_url", pulumi.Output.concat("http://", openemr_static_ip.address, "/agent"))
pulumi.export("vm_name", openemr_vm.name)
pulumi.export("vm_zone", openemr_vm.zone)
pulumi.export("cloud_sql_connection", sql_instance.connection_name)
pulumi.export("artifact_registry", registry_path)
