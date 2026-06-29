# Deployment: Heroku → Azure migration

A vendor-neutral move. The same `pg_dump`/`pg_restore` playbook works in reverse
the day of leaving Azure.

## What automates and what doesn't

| Piece | Automated? | How |
|---|---|---|
| Build + ship the app | Fully | `deploy.yml` on push to `main` |
| Provision infra | Fully | `terraform apply` |
| Database cutover | Scripted but **human-supervised** | the steps below |

The DB cutover stays manual on purpose: it's a maintenance window with a point
of no easy return. It is run deliberately, not on a git push.

## Prerequisites

- `az` CLI, Docker, Heroku CLI, and `psql`/`pg_dump`/`pg_restore` whose major
  version is **≥ both** the Heroku and Azure Postgres versions.

!!! danger "Match the Postgres major version to Heroku: check, don't assume"
    The scaffold defaulted `postgres_version` to `16`, but a real Heroku app was
    on **17**. A dump from a newer server cannot be loaded into an older one, and
    `pg_dump` refuses to even read a server newer than itself
    (`aborting because of server version mismatch`). Before provisioning:
    ```bash
    heroku pg:info -a <heroku-app> | grep -i version
    ```
    Set `postgres_version` in `terraform.tfvars` to **match or exceed** that, and
    use dump/restore tools of that version (see the container trick in step 5 if
    the local client is too old). The Azure DB is fine to re-provision at the
    right version *before* loading data, there's nothing in it yet.

!!! warning "`tofu output -raw` has no trailing newline, beware the copied `%`"
    `tofu output -raw database_url` prints no newline, so zsh shows a reverse-video
    `%` at the end. If copied, the URL becomes `...sslmode=require%` and
    `psql` fails with `invalid percent-encoded token`. Pipe to the clipboard
    (`tofu output -raw database_url | pbcopy`) or strip a stray trailing `%`:
    `URL="${URL%\%}"`.

## Steps

### 1. Make the app container-ready
The `Dockerfile` builds a self-starting image and `entrypoint.sh` sets the WSGI
module (`secretcodes.wsgi`). `requirements.txt` already has `gunicorn`,
`dj-database-url`, `psycopg2-binary`, plus the `django-storages` + `boto3`
already used for Spaces.

### 2. Read config from the environment
Already in place in `secretcodes/settings.py`: `SECRET_KEY`, `DEBUG`,
`DJANGO_ALLOWED_HOSTS`, and `DATABASE_URL` (via `dj-database-url`) all come from
the environment, and the existing Spaces (S3) storage config is reused as-is.

### 3. Build & push the image once, by hand
```bash
echo "$GHCR_PAT" | docker login ghcr.io -u your-gh-user --password-stdin
docker build --platform linux/amd64 -t ghcr.io/your-gh-user/secretcodes:latest .
docker push ghcr.io/your-gh-user/secretcodes:latest
```

!!! danger "`--platform linux/amd64` is mandatory on Apple Silicon"
    App Service runs amd64. A default build on an ARM Mac produces an arm64 image
    that dies in ~200ms with `exec format error` (Azure mislabels it as
    `ContainerTimeout`). CI builds on amd64 runners, so push-to-deploy avoids
    this, it only bites manual local builds. See
    [Azure → Gotchas](azure.md#known-gotchas-read-before-a-manual-deploy).

### 4. Provision Azure
`tofu apply` (see [Terraform](terraform.md)). Grab the target URL (mind the
trailing-`%` trap above):
```bash
tofu -chdir=infra/terraform output -raw database_url
```
`operator_ip` is only needed to restore from a **local laptop** (method B below).
The recommended method A runs from *inside* Azure and needs no firewall change.

### 5. Database cutover (supervised)

Get both connection strings (these feed the methods below):
```bash
HEROKU_URL=$(heroku config:get DATABASE_URL -a <heroku-app>)
AZURE_URL=$(tofu -chdir=infra/terraform output -raw database_url)   # mind the trailing %
```

!!! danger "Reset the schema before restoring: the app pre-migrates the DB"
    `entrypoint.sh` runs `migrate` on every boot, so by the time of cutover,
    the Azure DB **already has the schema** (and a few default rows). A plain
    `pg_restore` then collides (`relation already exists`). Reset to empty first:
    ```bash
    psql "$AZURE_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    ```

Two ways to reach the Azure DB for the restore. The DB's default firewall rule
allows *Azure-internal* services but **not** a local laptop.

**Method A: from inside Azure (recommended; no firewall change, version-matched).**
Run a throwaway container with the *exact* Postgres-client version (so it can
dump a newer Heroku server). Its egress is an Azure IP, already allowed.
```bash
RG=secretcodes-rg
heroku maintenance:on -a <heroku-app>                  # stop writes (start window)

az container create -g $RG --name pgmigrate --image postgres:17 \
  --os-type Linux --cpu 1 --memory 1 --restart-policy Never \
  --command-line "sleep 3600" \
  --secure-environment-variables HEROKU_URL="$HEROKU_URL" AZURE_URL="$AZURE_URL"

az container exec -g $RG --name pgmigrate --exec-command "/bin/bash"
# --- inside the container ---
psql "$AZURE_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
pg_dump "$HEROKU_URL" -Fc --no-owner --no-acl \
  | pg_restore --no-owner --no-acl --no-privileges -d "$AZURE_URL"
psql "$AZURE_URL" -c "SELECT count(*) FROM auth_user;"   # must match Heroku
exit

az container delete -g $RG --name pgmigrate -y
az webapp restart -n secretcodes-web -g $RG
```
Match the `postgres:NN` tag to the Heroku major version. Cloud Shell's bundled
client is often too old to dump a current server, this container sidesteps that.

**Method B: from a local laptop (simpler steps, brief external exposure).**
Set `operator_ip` to the laptop's public IP (`curl -s ifconfig.me`) in
`terraform.tfvars`, `tofu apply` to open the firewall, then run the same
`DROP SCHEMA` → `pg_dump | pg_restore` locally. **Blank `operator_ip` and
re-apply afterward** to close it. Requires a local client ≥ the Heroku version.

!!! note "Harmless restore warning: `pg_stat_statements`"
    Heroku enables the `pg_stat_statements` extension; Azure won't let the admin
    `CREATE` it, so `pg_restore` prints two ignored errors about it. This is a
    monitoring extension unrelated to the data, safe to ignore. (To get query
    stats on Azure, allow-list it via the server's `azure.extensions` parameter.)

For a community-platform-sized DB, the window is typically **5–30 minutes**.

### 6. Verify, then cut over traffic
Test on `https://secretcodes-web.azurewebsites.net` first. Then add the custom
domain + cert, lower DNS TTL a day ahead, and point the domain at Azure. **Keep
Heroku intact for a few days** as rollback before deleting anything.

### 7. Automate ongoing deploys
`deploy.yml` is already wired; from here, pushing to `main` ships automatically.

## Rollback
Before DNS cutover: nothing to roll back, Heroku is still live. After: flip DNS
back (Heroku intact) and turn its maintenance off. Low TTL keeps this quick.

## Leaving Azure later (same playbook, reversed)
- **App:** point a new host at the *same* GHCR image; recreate the env vars.
- **DB:** `pg_dump` from Azure → `pg_restore` into the new Postgres. Step 5 in
  reverse.
- **CI/CD:** swap only the `deploy` job in `deploy.yml`.
- **Media:** untouched, it never left Spaces.

Exit cost: one planned maintenance window. That's the whole point.
