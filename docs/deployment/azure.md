# Deployment: Azure (App Service + Postgres)

The production target while the Azure credits last. Compute and database on
Azure; media on DigitalOcean Spaces.

## Components

- **Azure App Service for Linux**, running the container image (not source build).
- **Azure Database for PostgreSQL – Flexible Server**, Burstable `B1ms`.
- **DigitalOcean Spaces** for static/media (unchanged).

## Provisioning

Infrastructure is defined as code, see **[Terraform](terraform.md)**. That is
the source of truth; resources are not assembled in the portal by hand.

## How the app is built and shipped

`.github/workflows/deploy.yml` runs on every push to `main` (excluding docs):

1. **Build + push** the container image to GitHub Container Registry (GHCR).
   This half is provider-neutral.
2. **Deploy** the new image tag to App Service via `azure/webapps-deploy`. This
   is the *only* Azure-specific block, about ten lines, and is what gets swapped
   to move to another host.

### One-time setup

Create an Azure service principal and store it as the `AZURE_CREDENTIALS` repo
secret:

```bash
az ad sp create-for-rbac --name secretcodes-deploy \
  --role contributor \
  --scopes /subscriptions/<sub-id>/resourceGroups/secretcodes-rg \
  --sdk-auth
```

!!! danger "Create `AZURE_CREDENTIALS` once — a re-run invalidates it"
    Each `az ad sp create-for-rbac --name secretcodes-deploy` run **resets** the
    SP password, so any earlier JSON's `clientSecret` stops working. If
    `azure/login` fails with `Invalid client secret provided`, you stored a stale
    one. Create it once, capture to a file (stdout only — the `--sdk-auth`
    deprecation warning goes to stderr), eyeball it, then store it:
    ```bash
    az ad sp create-for-rbac --name secretcodes-deploy --role contributor \
      --scopes "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/secretcodes-rg" \
      --sdk-auth > creds.json
    gh secret set AZURE_CREDENTIALS < creds.json && rm creds.json
    ```
    `clientSecret` should be a long value, not a GUID (a GUID is the secret *ID*,
    which is exactly what Azure's error warns against).

!!! warning "GHCR package needs the repo's Actions token to have write access"
    If the image was first pushed **manually**, the package isn't linked to the
    repo, so the CI `docker push` fails with `denied` / `permission_denied`. Grant
    it once: GHCR → the `secretcodes` package → **Package settings → Manage Actions
    access → add the repo with Write**. (Or delete the package and let CI recreate
    it — a token-pushed package links to the repo with write access automatically.)

!!! note "GHCR tags must be lowercase"
    `github.repository` keeps the owner's case (`Mariatta/...`), but Docker/GHCR
    reject mixed-case tags (`repository name must be lowercase`). `deploy.yml`
    lowercases it via `ghcr.io/${GITHUB_REPOSITORY,,}`.

## Container contract

The image must:

- Listen on the port from `$PORT` (App Service sets it; `WEBSITES_PORT=8000` is
  also set).
- Run migrations on boot and start gunicorn, see `entrypoint.sh`.

## Known gotchas (read before a manual deploy)

These are real failures from the first deployment, with their fixes.

!!! danger "Build the image for `linux/amd64`"
    App Service runs **amd64**. Building manually on an Apple Silicon Mac
    produces an **arm64** image, and the container dies in ~200ms with
    `exec /entrypoint.sh: exec format error`. Azure reports this misleadingly as
    `ContainerTimeout` ("did not start within 230s"), but the log shows the
    image pulling in ~1s, the container "running", then instantly stopping. The
    fix:
    ```bash
    docker build --platform linux/amd64 -t ghcr.io/<user>/secretcodes:latest .
    ```
    The `deploy.yml` CI runner is already amd64, so **push-to-deploy avoids this
    entirely**, only manual local builds on ARM Macs are affected.

!!! warning "`DEBUG` must be an empty string, not `\"0\"`"
    `settings.py` does `DEBUG = bool(os.environ.get("DEBUG", 0))`, and any
    non-empty string (including `"0"`) is truthy. Setting `DEBUG="0"` would run
    production in debug mode. The Terraform sets `DEBUG = ""` (the only falsy
    value). This is also why `FERNET_KEY` is mandatory on Azure (required
    whenever `DEBUG` is off).

!!! warning "Reuse `FERNET_KEY` and `SECRET_KEY` from Heroku, don't regenerate"
    `FERNET_KEY` encrypts data at rest; a new key makes migrated rows
    permanently undecryptable. `SECRET_KEY` signs sessions/tokens; a new one logs
    everyone out and breaks pending reset links. Pull both from
    `heroku config:get <NAME> -a <app>`. Generate fresh keys **only** for a
    brand-new empty database.

!!! note "Private GHCR image needs a read PAT"
    The image is published private by default. App Service can't pull it without
    `TF_VAR_ghcr_pat` (a classic PAT with `read:packages`). A pull-auth failure
    looks like `unauthorized` / `manifest unknown` in the log.

!!! note "`.dockerignore` is mandatory: secrets and size"
    The `Dockerfile` does `COPY . /code/`, which **ignores `.gitignore`**.
    Without `.dockerignore`, `.env` and `client_secret_*.json` get baked into a
    layer and pushed to the registry, and `venv/` bloats the image by ~300 MB.
    The committed `.dockerignore` excludes secrets, the virtualenv, VCS, and
    local DBs.

!!! tip "Reading container logs"
    ```bash
    az webapp log config -n secretcodes-web -g secretcodes-rg --docker-container-logging filesystem
    az webapp log tail   -n secretcodes-web -g secretcodes-rg
    ```
    Rule of thumb: a container that dies in **milliseconds** is *crashing* (arch
    mismatch, bad env var), read the app traceback. A container that runs for
    **minutes** then gets killed is a genuine *timeout* (slow pull/boot),
    `WEBSITES_CONTAINER_START_TIME_LIMIT` (set to `1800`) buys time, but a
    smaller `python:3.13-slim` image is the durable fix.

    `ContainerTimeout` is **misleading** — App Service reports it for a fast boot
    *crash* too, not just real slowness. `az webapp log tail` is dominated by
    platform (`ContainerStatus`) and Kudu (`/opt/Kudu`, port 8181) noise, which
    is **not** your app. To see the container's own stdout (the real traceback),
    download the logs and read `*_default_docker.log`:
    ```bash
    az webapp log download -n secretcodes-web -g secretcodes-rg --log-file /tmp/azlogs.zip
    unzip -o /tmp/azlogs.zip -d /tmp/azlogs
    tail -n 80 /tmp/azlogs/LogFiles/*default_docker.log
    ```
    A `dj_database_url.ParseError` at settings import, for example, surfaces here
    (see [Terraform → URL-encode the DB password](terraform.md#gotchas-worth-knowing)).

!!! note "Run docker/tofu from the right directory"
    `docker build` runs from the **repo root** (it needs the `Dockerfile` and the
    full project as build context). `tofu` runs from **`infra/terraform/`**.

## Cost note

Without credits, this stack is ~\$28–33/month (B1 App Service + B1ms Postgres),
which is *more* than the all-DigitalOcean equivalent (~\$20/month). The credits
are the entire reason to be on Azure, so the [migration](migration.md) playbook
out is the important safety net, not an afterthought.
