# OpenEMR Staging Infra (GCP)

Pulumi program for staging runs from this directory.

Read [local-deploy.md](local-deploy.md) for instructions on deploying the system locally.

## Quick Commands

```bash
cd infra
export PULUMI_CONFIG_PASSPHRASE=""
pulumi stack select staging
pulumi preview --stack staging
pulumi up --stack staging --yes
```

## Common Outputs

```bash
pulumi stack output openemr_url --stack staging
pulumi stack output ai_agent_url --stack staging
pulumi stack output vm_name --stack staging
pulumi stack output vm_zone --stack staging
```

## Troubleshooting

See:

- `infra/TROUBLESHOOTING.md`

This includes:

- Artifact Registry auth failures on VM startup
- Staging DB reset runbook
- Seed data source references
