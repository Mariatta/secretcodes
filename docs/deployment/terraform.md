# Deployment: Infrastructure as Code (Terraform)

The Azure side is provisioned with Terraform, in `infra/terraform/`. This is the
declarative successor to the earlier `provision-azure.sh` script, same
resources, but reproducible, reviewable, and diffable.

## What it creates

| Resource | Terraform resource | Notes |
|---|---|---|
| Resource group | `azurerm_resource_group` | Container for everything |
| Postgres | `azurerm_postgresql_flexible_server` | Burstable `B_Standard_B1ms`, 32 GB |
| Database | `azurerm_postgresql_flexible_server_database` | UTF8 |
| DB firewall | `azurerm_postgresql_flexible_server_firewall_rule` | Allow Azure services (+ optional laptop IP) |
| App plan | `azurerm_service_plan` | Linux, `B1` |
| Web app | `azurerm_linux_web_app` | Container from GHCR, app settings |

## Files

- `providers.tf`: provider + (commented) remote state backend.
- `variables.tf`: all inputs; secrets marked `sensitive`.
- `main.tf`: the resources above.
- `outputs.tf`: app URL and (sensitive) `database_url` for the migration.
- `terraform.tfvars.example`: copy to `terraform.tfvars` and fill in.

## Usage

```bash
cd infra/terraform

# Secrets via environment (preferred over the tfvars file):
export ARM_SUBSCRIPTION_ID='...'
export TF_VAR_postgres_admin_password='...'
export TF_VAR_ghcr_pat='...'
export TF_VAR_django_secret_key='...'
export TF_VAR_spaces_key='...' TF_VAR_spaces_secret='...'

cp terraform.tfvars.example terraform.tfvars   # edit non-secret values

terraform init
terraform plan      # review what will change
terraform apply

# The restore target for the DB migration:
terraform output -raw database_url
```

## Gotchas worth knowing

!!! warning "docker_registry_url needs the protocol"
    The provider rejects `ghcr.io`, it must be `https://ghcr.io`. And do **not**
    also set `DOCKER_REGISTRY_SERVER_*` in `app_settings`; the provider manages
    those via `application_stack`, and setting both causes a perpetual diff.

!!! note "Image name vs registry"
    `application_stack.docker_image_name` is the path + tag *without* the
    registry host (`your-user/secretcodes:latest`); the host goes in
    `docker_registry_url`. `main.tf` strips `ghcr.io/` from the `image` variable
    to handle this.

!!! note "Postgres version must match Heroku"
    Set `postgres_version` to the Heroku Postgres major version before applying,
    or the dump/restore can fail.

!!! warning "`tofu init` fails on a stale `.terraform` cache"
    If a previous run left a `.terraform/` provider cache, `tofu init` can fail
    with `existing cached package ... does not match the content of the
    downloaded package; does it contain local modifications?`. The cache is
    local and regenerable, so clear it and re-init:
    ```bash
    rm -rf .terraform
    tofu init
    ```
    If it still complains (a lock-hash mismatch rather than a cache mismatch),
    also remove `.terraform.lock.hcl` and re-init.

!!! danger "URL-encode the DB password (or the app won't boot)"
    `main.tf` builds `DATABASE_URL` with `urlencode(var.postgres_admin_password)`.
    This matters: modern `dj-database-url` **rejects** a `DATABASE_URL` whose
    parts aren't percent-encoded, so a password containing `+`, `/`, or `=`
    (exactly what `openssl rand -base64` produces) makes the container crash at
    settings import with `dj_database_url.ParseError` — which Azure then reports
    as the misleading `ContainerTimeout`. With `urlencode()` any password is
    safe; without it, use a URL-safe password like `openssl rand -hex 24`.

## State and portability

State is local until the backend in `providers.tf` is uncommented. Two thoughts:

- Remote state is worth setting up before this is more than a side project.
- The backend is itself a lock-in choice. The example uses Azure Blob; an
  S3-compatible backend pointed at DigitalOcean Spaces keeps even the state
  vendor-neutral, consistent with the rest of the architecture.

When leaving Azure, the web app and Postgres resources are replaced by the new
provider's equivalents; the variables (image, env vars, Spaces creds) carry over
unchanged.
