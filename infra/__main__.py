"""Pulumi program for OpenEMR AI Agent staging infrastructure on GCP."""

import pulumi
import pulumi_gcp as gcp

from startup import render_startup_script

# ---------------------------------------------------------------------------
# Common resource labels
# ---------------------------------------------------------------------------

COMMON_LABELS = {
    "environment": "staging",
    "project": "openemr",
    "managed-by": "pulumi",
}

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
db_tier = config.get("dbTier") or "db-g1-small"

# Compute Engine
vm_name = config.get("vmName") or "openemr-staging-vm"
vm_zone = config.get("vmZone") or f"{region}-a"
vm_machine_type = config.get("vmMachineType") or "e2-standard-4"
vm_boot_disk_gb = config.get_int("vmBootDiskGb") or 50
vm_data_disk_gb = config.get_int("vmDataDiskGb") or 100
network_name = config.get("network") or "default"
subnetwork_name = config.get("subnetwork")
ssh_source_ranges = config.require_object("sshSourceRanges")

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
    labels=COMMON_LABELS,
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
        user_labels=COMMON_LABELS,
        ip_configuration=gcp.sql.DatabaseInstanceSettingsIpConfigurationArgs(
            ipv4_enabled=True,
            authorized_networks=[],
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
        labels=COMMON_LABELS,
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

# Grant write access (addVersion) for secrets the VM self-healing may update.
WRITABLE_SECRETS = ["OPENEMR_CLIENT_ID", "OPENEMR_CLIENT_SECRET"]
for secret_name in WRITABLE_SECRETS:
    vm_secret_iam_members.append(
        gcp.secretmanager.SecretIamMember(
            f"openemr-vm-secret-write-{secret_name.lower().replace('_', '-')}",
            secret_id=secrets[secret_name].id,
            role="roles/secretmanager.secretVersionAdder",
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
    labels=COMMON_LABELS,
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
    labels=COMMON_LABELS,
)


# ---------------------------------------------------------------------------
# Startup script
# ---------------------------------------------------------------------------

startup_script = pulumi.Output.all(
    project,
    sql_instance.connection_name,
    db_password,
    openemr_image,
    ai_agent_image,
    openemr_static_ip.address,
).apply(lambda args: render_startup_script(
    project_id=args[0],
    cloud_sql_connection=args[1],
    db_password=args[2],
    openemr_image=args[3],
    ai_agent_image=args[4],
    static_ip=args[5],
))

# ---------------------------------------------------------------------------
# Compute Engine VM
# ---------------------------------------------------------------------------

openemr_vm = gcp.compute.Instance(
    "openemr-vm",
    name=vm_name,
    zone=vm_zone,
    machine_type=vm_machine_type,
    labels=COMMON_LABELS,
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
