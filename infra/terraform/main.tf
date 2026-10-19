locals {
  app_name    = "${var.name_prefix}-web"
  worker_name = "${var.name_prefix}-worker"
  beat_name   = "${var.name_prefix}-beat"
  pg_name     = "${var.name_prefix}-pg"
  redis_name  = "${var.name_prefix}-redis"

  # Host(s) the app answers on. With a custom apex domain bound, both the
  # azurewebsites.net hostname and the custom domain must be trusted, or Django
  # rejects requests to the custom domain (DisallowedHost / CSRF failures).
  azure_host    = "${var.name_prefix}-web.azurewebsites.net"
  public_host   = var.custom_domain != "" ? var.custom_domain : local.azure_host
  allowed_hosts = var.custom_domain != "" ? "${local.azure_host},${var.custom_domain}" : local.azure_host
  csrf_origins  = var.custom_domain != "" ? "https://${local.azure_host},https://${var.custom_domain}" : "https://${local.azure_host}"

  # sslmode=require is mandatory on Azure Postgres — and harmless everywhere else.
  # urlencode the password: modern dj-database-url rejects a DATABASE_URL whose
  # parts aren't percent-encoded, so a password containing +, /, =, etc. (e.g.
  # from `openssl rand -base64`) would otherwise make the app fail to boot.
  database_url = "postgres://${var.postgres_admin_user}:${urlencode(var.postgres_admin_password)}@${azurerm_postgresql_flexible_server.pg.fqdn}:5432/${var.postgres_db_name}?sslmode=require"

  # application_stack wants the image path + tag WITHOUT the registry host;
  # the host goes in docker_registry_url. Strip "ghcr.io/" from the full ref.
  docker_image_name = replace(var.image, "ghcr.io/", "")

  # Celery broker. Managed Redis speaks TLS (client_protocol Encrypted); rediss://
  # + ssl_cert_reqs is what redis-py needs. hostname is top-level; port and the
  # access key live on the default_database block. Guarded by the publishing flag
  # since the resource only exists then.
  broker_url = var.enable_publishing ? "rediss://:${urlencode(azurerm_managed_redis.redis[0].default_database[0].primary_access_key)}@${azurerm_managed_redis.redis[0].hostname}:${azurerm_managed_redis.redis[0].default_database[0].port}/0?ssl_cert_reqs=required" : ""

  # Publishing-only settings, empty until the flag is on, so a non-publishing
  # env (prod today) sees no new app settings and its apply stays a no-op.
  # DOMAIN_NAME lives here rather than in the base: the connector uses it to
  # build absolute asset URLs and the Mastodon redirect. (Prod not setting it
  # is a separate, pre-existing issue — QR/survey links there fall back to the
  # localhost default — deliberately left alone rather than folded into this.)
  publishing_settings = var.enable_publishing ? {
    CELERY_BROKER_URL = local.broker_url
    DOMAIN_NAME       = "https://${local.public_host}"
  } : {}

  # Everything both the web app and the workers need. Kept in one place so the
  # roles can't drift: the worker publishes, so it needs the DB, the encryption
  # key, media storage, and the outbound host settings just like web does.
  base_app_settings = {
    DATABASE_URL = local.database_url
    SECRET_KEY   = var.django_secret_key
    FERNET_KEY   = var.fernet_key
    # settings.py does DEBUG = bool(os.environ.get("DEBUG", 0)) — any non-empty
    # string (incl. "0") is truthy, so an empty string is the only safe "off".
    DEBUG = ""

    DJANGO_ALLOWED_HOSTS = local.allowed_hosts
    CSRF_TRUSTED_ORIGINS = local.csrf_origins

    GOOGLE_CLIENT_ID          = var.google_client_id
    GOOGLE_CLIENT_SECRET      = var.google_client_secret
    GOOGLE_OAUTH_REDIRECT_URI = "https://${local.public_host}/availability/oauth/callback/"

    DJANGO_EMAIL_HOST          = "smtp.mailgun.org"
    DJANGO_EMAIL_PORT          = "587"
    DJANGO_EMAIL_HOST_USER     = var.mailgun_smtp_user
    DJANGO_EMAIL_HOST_PASSWORD = var.mailgun_smtp_password
    DJANGO_EMAIL_USE_TLS       = "true"
    DJANGO_DEFAULT_FROM_EMAIL  = var.default_from_email

    USE_SPACES              = "true"
    AWS_ACCESS_KEY_ID       = var.spaces_key
    AWS_SECRET_ACCESS_KEY   = var.spaces_secret
    AWS_STORAGE_BUCKET_NAME = var.spaces_bucket
    AWS_S3_ENDPOINT_URL     = var.spaces_endpoint
  }
}

resource "azurerm_resource_group" "rg" {
  name     = "${var.name_prefix}-rg"
  location = var.location
}

# --- PostgreSQL Flexible Server (Burstable B1ms) -----------------------------

resource "azurerm_postgresql_flexible_server" "pg" {
  name                          = local.pg_name
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  version                       = var.postgres_version
  administrator_login           = var.postgres_admin_user
  administrator_password        = var.postgres_admin_password
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  public_network_access_enabled = true

  lifecycle {
    # Azure may pick/relocate the availability zone; don't fight it on re-apply.
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "db" {
  name      = var.postgres_db_name
  server_id = azurerm_postgresql_flexible_server.pg.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# Lets other Azure services (incl. your App Service) reach the DB.
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.pg.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# Optional: open the DB to your laptop for the one-time migration restore.
resource "azurerm_postgresql_flexible_server_firewall_rule" "operator" {
  count            = var.operator_ip == "" ? 0 : 1
  name             = "operator-laptop"
  server_id        = azurerm_postgresql_flexible_server.pg.id
  start_ip_address = var.operator_ip
  end_ip_address   = var.operator_ip
}

# --- Redis: the Celery broker (publishing only) ------------------------------
# Azure Managed Redis. The classic "Azure Cache for Redis" (azurerm_redis_cache)
# is retired for new creates — Azure rejects it with a 400 pointing here.
# Balanced_B0 is the entry SKU, plenty for a queue holding at most a minute of
# work; only the broker lives here, delivery state is in Postgres.
#
# NoCluster so kombu/Celery see a plain standalone endpoint (Celery doesn't
# drive Redis Cluster as a broker). Access-key auth so the worker connects with
# a password in the URL; the alternative is Entra-only, which Celery can't use.
# HA off — staging doesn't need the standby replica, and it halves the cost.

resource "azurerm_managed_redis" "redis" {
  count                     = var.enable_publishing ? 1 : 0
  name                      = local.redis_name
  resource_group_name       = azurerm_resource_group.rg.name
  location                  = azurerm_resource_group.rg.location
  sku_name                  = "Balanced_B0"
  high_availability_enabled = false

  default_database {
    client_protocol                    = "Encrypted"
    clustering_policy                  = "NoCluster"
    access_keys_authentication_enabled = true
  }
}

# --- Compute: App Service plan + container apps ------------------------------

resource "azurerm_service_plan" "plan" {
  name                = "${var.name_prefix}-plan"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "B1"
}

resource "azurerm_linux_web_app" "web" {
  name                = local.app_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_service_plan.plan.location
  service_plan_id     = azurerm_service_plan.plan.id
  https_only          = true

  site_config {
    always_on = true

    application_stack {
      docker_image_name        = local.docker_image_name
      docker_registry_url      = "https://ghcr.io" # protocol is REQUIRED by the provider
      docker_registry_username = var.ghcr_user
      docker_registry_password = var.ghcr_pat
    }
  }

  app_settings = merge(local.base_app_settings, local.publishing_settings, {
    WEBSITES_PORT = "8000"
    # App Service kills the container if it doesn't answer the startup probe
    # within this many seconds (default 230). A large first-pull + migrate on
    # boot can exceed that, so raise it to the max. The durable fix is a smaller
    # image (python:3.13-slim) + moving collectstatic to build time.
    WEBSITES_CONTAINER_START_TIME_LIMIT = "1800"

    # Do NOT add DOCKER_REGISTRY_SERVER_* here. The provider manages registry
    # creds via application_stack; duplicating them causes a perpetual diff.
  })
}

# --- Celery worker + beat (publishing only) ----------------------------------
# Same image as web, distinguished by CONTAINER_ROLE (see entrypoint.sh). They
# serve no traffic; the healthping responder answers the startup probe so App
# Service doesn't crash-loop a port-less container. One beat only — two would
# double every scheduled tick.

resource "azurerm_linux_web_app" "worker" {
  count               = var.enable_publishing ? 1 : 0
  name                = local.worker_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_service_plan.plan.location
  service_plan_id     = azurerm_service_plan.plan.id
  https_only          = true

  site_config {
    always_on = true
    application_stack {
      docker_image_name        = local.docker_image_name
      docker_registry_url      = "https://ghcr.io"
      docker_registry_username = var.ghcr_user
      docker_registry_password = var.ghcr_pat
    }
  }

  app_settings = merge(local.base_app_settings, local.publishing_settings, {
    CONTAINER_ROLE                      = "worker"
    WEBSITES_PORT                       = "8000" # the healthping responder
    WEBSITES_CONTAINER_START_TIME_LIMIT = "1800"
  })
}

resource "azurerm_linux_web_app" "beat" {
  count               = var.enable_publishing ? 1 : 0
  name                = local.beat_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_service_plan.plan.location
  service_plan_id     = azurerm_service_plan.plan.id
  https_only          = true

  site_config {
    always_on = true
    application_stack {
      docker_image_name        = local.docker_image_name
      docker_registry_url      = "https://ghcr.io"
      docker_registry_username = var.ghcr_user
      docker_registry_password = var.ghcr_pat
    }
  }

  app_settings = merge(local.base_app_settings, local.publishing_settings, {
    CONTAINER_ROLE                      = "beat"
    WEBSITES_PORT                       = "8000"
    WEBSITES_CONTAINER_START_TIME_LIMIT = "1800"
  })
}
