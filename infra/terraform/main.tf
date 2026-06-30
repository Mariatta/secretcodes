locals {
  app_name = "${var.name_prefix}-web"
  pg_name  = "${var.name_prefix}-pg"

  # sslmode=require is mandatory on Azure Postgres — and harmless everywhere else.
  # urlencode the password: modern dj-database-url rejects a DATABASE_URL whose
  # parts aren't percent-encoded, so a password containing +, /, =, etc. (e.g.
  # from `openssl rand -base64`) would otherwise make the app fail to boot.
  database_url = "postgres://${var.postgres_admin_user}:${urlencode(var.postgres_admin_password)}@${azurerm_postgresql_flexible_server.pg.fqdn}:5432/${var.postgres_db_name}?sslmode=require"

  # application_stack wants the image path + tag WITHOUT the registry host;
  # the host goes in docker_registry_url. Strip "ghcr.io/" from the full ref.
  docker_image_name = replace(var.image, "ghcr.io/", "")
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

# --- Compute: App Service plan + container web app ---------------------------

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

  app_settings = {
    WEBSITES_PORT = "8000"
    # App Service kills the container if it doesn't answer the startup probe
    # within this many seconds (default 230). A large first-pull + migrate on
    # boot can exceed that, so raise it to the max. The durable fix is a smaller
    # image (python:3.13-slim) + moving collectstatic to build time.
    WEBSITES_CONTAINER_START_TIME_LIMIT = "1800"

    DATABASE_URL = local.database_url
    SECRET_KEY   = var.django_secret_key
    FERNET_KEY   = var.fernet_key
    # settings.py does DEBUG = bool(os.environ.get("DEBUG", 0)) — any non-empty
    # string (incl. "0") is truthy, so an empty string is the only safe "off".
    # DEBUG must stay off in prod, which is exactly why FERNET_KEY is required.
    DEBUG = ""
    # The app reads DJANGO_ALLOWED_HOSTS (settings.py), not ALLOWED_HOSTS.
    DJANGO_ALLOWED_HOSTS = "${local.app_name}.azurewebsites.net"
    # Scheme+host trusted for CSRF (Django 4.0+). App Service terminates TLS, so
    # the browser's https:// Origin must be listed here or logins fail CSRF.
    CSRF_TRUSTED_ORIGINS = "https://${local.app_name}.azurewebsites.net"

    # Google OAuth for availability calendar sync. Reuse the Heroku client; the
    # redirect URI must point at this host and be registered in Google Console.
    GOOGLE_CLIENT_ID          = var.google_client_id
    GOOGLE_CLIENT_SECRET      = var.google_client_secret
    GOOGLE_OAUTH_REDIRECT_URI = "https://${local.app_name}.azurewebsites.net/availability/oauth/callback/"

    # settings.py only wires up the S3/Spaces storage (and the AWS_* settings the
    # QR generator reads) when USE_SPACES == "true". Without it, QR creation 500s.
    USE_SPACES              = "true"
    AWS_ACCESS_KEY_ID       = var.spaces_key
    AWS_SECRET_ACCESS_KEY   = var.spaces_secret
    AWS_STORAGE_BUCKET_NAME = var.spaces_bucket
    AWS_S3_ENDPOINT_URL     = var.spaces_endpoint

    # Do NOT add DOCKER_REGISTRY_SERVER_* here. The provider manages registry
    # creds via application_stack; duplicating them causes a perpetual diff.
  }
}