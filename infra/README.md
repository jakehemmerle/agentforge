# OpenEMR Staging Infra (GCP)

Pulumi program for staging runs from this directory.

## Quick Commands

```bash
python ../ai-agent/scripts/validate_engineering_contract.py

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
- Health endpoint interpretation (`502` vs `setup_required`)
- Staging DB reset runbook
- Seed data source references
