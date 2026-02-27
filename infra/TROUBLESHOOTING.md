# OpenEMR Staging Infra Troubleshooting

This runbook captures common failure modes for the Compute Engine staging
deployment.

## 1) `pulumi stack output` fails due to passphrase

Symptom:

- `pulumi stack output ...` errors with:
- `constructing secrets manager ... passphrase must be set ...`

Recovery:

```bash
cd infra
export PULUMI_CONFIG_PASSPHRASE=""

pulumi stack output vm_name --stack staging
pulumi stack output vm_zone --stack staging
```

## 2) VM startup cannot pull from Artifact Registry

Symptom:

- Serial output shows `Unauthenticated request` when pulling:
- `us-central1-docker.pkg.dev/...`

Cause:

- Docker is not logged in on the VM runtime before `docker compose pull`.

Required fix in startup script:

- Login with metadata service account token before image pull:

```bash
TOKEN="$(curl -sS -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
  | jq -r .access_token)"
echo "$TOKEN" | docker login -u oauth2accesstoken --password-stdin https://us-central1-docker.pkg.dev
```

## 3) OpenEMR first boot appears hung

This shouldn't happen anymore because you shouldn't be destroying the cloud SQL instance ever, but IF WE EXPLICITLY AGREE TO, then we should note these.

Symptom:

- Gateway returns `502`
- OpenEMR logs show `First boot: running database setup...` for a long time.

Important:

- On tiny DB tier (`db-f1-micro`) initial OpenEMR seed can be very slow.
- Check progress in InnoDB transaction rows modified:

```bash
gcloud compute ssh openemr-staging-vm --zone us-central1-a --project openemr-agent-staging --command '
PASS=$(sudo docker inspect openemr-openemr-1 --format "{{range .Config.Env}}{{println .}}{{end}}" | sed -n "s/^MYSQL_ROOT_PASS=//p" | head -n1)
sudo docker exec openemr-openemr-1 sh -lc "mysql --skip-ssl -hcloud-sql-proxy -P3306 -uroot -p\"$PASS\" -e \"SELECT trx_id, trx_rows_modified, trx_operation_state FROM information_schema.innodb_trx;\""
'
```

If `trx_rows_modified` increases over time, setup is still progressing.

## 5) Volume mount pitfalls

This is unconfirmed.

Avoid these mounts for OpenEMR runtime:

- Do not mount over `/var/www/localhost/htdocs/openemr/sites/default` unless the
  mounted directory already contains required OpenEMR site files.
- Do not mount `/var/log` from host in this setup; it can break Apache expected
  paths.

## 6) Staging DB reset runbook

Use only for staging recovery:

```bash
gcloud sql databases delete openemr \
  --instance openemr-sql-478495d \
  --project openemr-agent-staging \
  --quiet

gcloud sql databases create openemr \
  --instance openemr-sql-478495d \
  --project openemr-agent-staging

gcloud compute ssh openemr-staging-vm --zone us-central1-a --project openemr-agent-staging --command '
sudo docker compose --env-file /opt/openemr/.env -f /opt/openemr/docker-compose.yml up -d --force-recreate
'
```

## 7) Seed data source (where installer data comes from)

Seed/schema data is from upstream OpenEMR installer files inside the OpenEMR
source cloned in the image:

- `sql/database.sql`
- `contrib/util/language_translations/currentLanguage_utf8.sql`
- `sql/cvx_codes.sql` (if present)
- `sql/official_additional_users.sql`

Reference:

- `openemr/library/classes/Installer.class.php` (`initialize_dumpfile_list`)

## 8) OAuth2 "Security error - problem with authorization server keys"

Symptom:

- OAuth2 endpoints return 500 with `"Security error - problem with authorization server keys"`
- Apache error log shows `Decryption failed HMAC Authentication!` and
  `oauth2 encryption key was blank after it was decrypted`

Cause:

OpenEMR uses a dual-key encryption system: drive keys (files on disk) encrypt
values stored in the database, and vice versa. The `oauth2key` and
`oauth2passphrase` rows in the `keys` table are encrypted using drive key files
at `sites/default/documents/logs_and_misc/methods/`. If the container is
rebuilt (new image deploy, VM reset) without persisting those files, new drive
keys are generated that cannot decrypt the old database values.

Prevention:

The startup script mounts the crypto directories to the persistent data disk so
drive keys survive container rebuilds. If this mount is missing, restore it in
`startup_script.sh.tpl`.

Recovery (if mounts were not in place):

```bash
gcloud compute ssh openemr-staging-vm --zone us-central1-a --project openemr-agent-staging --command '
# 1. Delete stale encrypted rows
sudo docker exec openemr-openemr-1 mysql --skip-ssl -hcloud-sql-proxy -P3306 \
  -uopenemr -p"$DB_PASSWORD" openemr \
  -e "DELETE FROM \`keys\` WHERE name IN ('\''oauth2key'\'', '\''oauth2passphrase'\'');"

# 2. Delete stale key files
sudo docker exec openemr-openemr-1 rm -f \
  /var/www/localhost/htdocs/openemr/sites/default/documents/certificates/oaprivate.key \
  /var/www/localhost/htdocs/openemr/sites/default/documents/certificates/oapublic.key

# 3. Trigger regeneration via non-OAuth API call
curl -s http://localhost/apis/default/fhir/metadata > /dev/null

# 4. Verify
curl -s http://localhost/oauth2/default/registration \
  -X POST -H "Content-Type: application/json" \
  -d "{\"application_type\":\"private\",\"client_name\":\"probe\",\"redirect_uris\":[\"https://localhost\"],\"scope\":\"openid\"}"
'
```

## 9) Security note

Never enable `set -x` in VM startup scripts that fetch or render secrets. It can
write secret values to serial logs.

