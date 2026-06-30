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

!!! warning "Build from *current* code, not a stale `:latest`"
    A resumed migration may already have an old `:latest` in GHCR from an earlier
    attempt. Build fresh from the current branch or App Service serves old code
    (routes/apps that didn't exist yet 404). After pushing, `az webapp restart`;
    if it still serves the old layer, force a pull:
    ```bash
    az webapp config container set -n secretcodes-web -g secretcodes-rg \
      --docker-custom-image-name ghcr.io/<user>/secretcodes:latest \
      --docker-registry-server-url https://ghcr.io
    ```

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
# --- inside the container: the exec shell does NOT inherit the secure env, so
# --- set the URLs by hand (single-quoted; verify each starts with postgres://)
export AZURE_URL='postgres://...'      # paste from the laptop
export HEROKU_URL='postgres://...'
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

!!! danger "`az container exec` does **not** inherit `--secure-environment-variables`"
    The interactive shell starts without the container's secure env, so
    `$AZURE_URL`/`$HEROKU_URL` are empty and `psql` silently falls back to a local
    socket (`/var/run/postgresql/.s.PGSQL.5432 ... No such file or directory`).
    Set them inside the container by hand. Two traps when you do:

    - **A failed `tofu output` gets captured as the value.** `AZURE_URL=$(tofu
      output -raw database_url)` run in the wrong directory / without env loaded
      captures the *error text* (you'll see box-drawing chars `╷ │`, length ~530).
      `echo "$AZURE_URL"` and confirm it starts with `postgres://`.
    - **Trailing `%`.** `tofu output -raw` prints no newline, so a zsh copy appends
      a `%`, and psql fails with `invalid percent-encoded token: "require%"`. Strip
      it: `export AZURE_URL="${AZURE_URL%\%}"`. Single-quote the value so the
      `%`-encoded password survives.

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

!!! note "Harmless restore warnings: Heroku event triggers / `_heroku` schema"
    `pg_restore` also reports ~20 ignored errors recreating event triggers
    (`01_configure_extension_drop`, `01_extension_before_drop`) and the `_heroku`
    schema — Heroku's internal management objects that don't exist on (or apply
    to) Azure. They aren't your data; `errors ignored on restore: N` means
    everything else loaded.

For a community-platform-sized DB, the window is typically **5–30 minutes**.

### 6. Verify, then cut over traffic
First verify on `https://secretcodes-web.azurewebsites.net` — and hit the MCP
calendar endpoint (`POST /mcp/`, `check_availability`) to confirm the migrated
Google token **decrypts and refreshes** (`"connected": true`); that only works
because Azure's `FERNET_KEY` matches Heroku's. Then bind the apex and flip DNS:

1. **App values:** `az webapp show -n secretcodes-web -g secretcodes-rg --query
   customDomainVerificationId -o tsv` for the ownership ID, and the inbound IP via
   `dig +short secretcodes-web.azurewebsites.net` (the `inboundIpAddress` query
   often returns null).
2. **DNS (registrar):** `TXT asuid` → the verification ID, and `A @` → the
   inbound IP. (Lower the TTL a day ahead for a near-instant flip.)
3. **Hostname + cert:** `az webapp config hostname add --webapp-name
   secretcodes-web -g secretcodes-rg --hostname secretcodes.dev`, then create the
   free managed cert **in the Portal** (Custom domains → Add binding → SNI SSL →
   *Create App Service Managed Certificate*). The CLI `az webapp config ssl
   create` is in preview and throws a `JSONDecodeError`. The cert can only be
   issued *after* the A record points at Azure (Azure validates by reaching the
   domain), so expect a brief HTTPS-pending window.

!!! danger "Trust the apex host or it 500s with `DisallowedHost`"
    The app answers on `azurewebsites.net` but Django rejects `secretcodes.dev`
    until it's allowed. Set `custom_domain = "secretcodes.dev"` in
    `terraform.tfvars` and `tofu apply` — that adds the apex to
    `DJANGO_ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS` and sets the OAuth redirect
    URI. (A missing host shows as a 500 here, not a 400, because the branded error
    page itself reads the host.)

**Keep Heroku intact for a few days** as rollback before deleting anything.

### 7. Automate ongoing deploys
`deploy.yml` is already wired; from here, pushing to `main` ships automatically.

## Rollback
Before DNS cutover: nothing to roll back, Heroku is still live. After: flip DNS
back (Heroku intact) and turn its maintenance off. Low TTL keeps this quick.

## Decommission Heroku (once Azure has proven itself)

!!! warning "Maintenance mode does **not** stop billing"
    Dynos and add-ons keep charging while they exist, and Heroku has no true
    "pause". Do this only after a few days of confidence, in stages from
    "keep rollback" to "$0".

**1. Stop dyno (compute) charges — keeps the rollback DB live:**
```bash
heroku ps:scale web=0 -a <heroku-app>      # plus worker=0 etc. if you have them
```

**2. The Postgres add-on is the main ongoing cost** (it's the rollback data).
See what bills with `heroku addons -a <heroku-app>`, then either keep it a few
more days, or capture a backup and remove it (rollback becomes the dump):
```bash
heroku pg:backups:capture  -a <heroku-app>
heroku pg:backups:download -a <heroku-app>      # -> latest.dump, keep it safe
heroku addons:destroy <postgres-addon-name> -a <heroku-app>
```

**3. Stop all charges** once you're sure you won't roll back:
```bash
heroku apps:destroy -a <heroku-app>             # irreversible; prompts for the name
```

The DigitalOcean Spaces bucket (media + this docs site) is separate and stays —
it was never a Heroku resource.

## Leaving Azure later (same playbook, reversed)
- **App:** point a new host at the *same* GHCR image; recreate the env vars.
- **DB:** `pg_dump` from Azure → `pg_restore` into the new Postgres. Step 5 in
  reverse.
- **CI/CD:** swap only the `deploy` job in `deploy.yml`.
- **Media:** untouched, it never left Spaces.

Exit cost: one planned maintenance window. That's the whole point.
