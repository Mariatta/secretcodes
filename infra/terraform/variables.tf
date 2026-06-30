variable "subscription_id" {
  description = "Azure subscription ID. Leave null and export ARM_SUBSCRIPTION_ID instead."
  type        = string
  default     = null
}

variable "location" {
  description = "Azure region (closest to Vancouver)."
  type        = string
  default     = "canadacentral"
}

variable "name_prefix" {
  description = "Prefix for resource names. Note: web app and PG server names must be globally unique."
  type        = string
  default     = "secretcodes"
}

variable "custom_domain" {
  description = "Custom apex domain bound to the web app, e.g. secretcodes.dev. Added to DJANGO_ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS and used for the OAuth redirect URI. Empty = azurewebsites.net only."
  type        = string
  default     = ""
}

# --- PostgreSQL --------------------------------------------------------------

variable "postgres_version" {
  description = "PostgreSQL MAJOR version. MUST match your Heroku source version."
  type        = string
  default     = "16"
}

variable "postgres_admin_user" {
  type    = string
  default = "scadmin"
}

variable "postgres_admin_password" {
  description = "Postgres admin password. Pass via TF_VAR_postgres_admin_password."
  type        = string
  sensitive   = true
}

variable "postgres_db_name" {
  type    = string
  default = "secretcodes"
}

# --- Container image ---------------------------------------------------------

variable "image" {
  description = "Full image reference incl. tag, e.g. ghcr.io/<user>/secretcodes:latest"
  type        = string
}

variable "ghcr_user" {
  description = "GitHub username that owns the GHCR image."
  type        = string
}

variable "ghcr_pat" {
  description = "GitHub PAT with read:packages. Pass via TF_VAR_ghcr_pat."
  type        = string
  sensitive   = true
}

# --- Django ------------------------------------------------------------------

variable "django_secret_key" {
  description = "Pass via TF_VAR_django_secret_key."
  type        = string
  sensitive   = true
}

variable "fernet_key" {
  description = "Fernet key for encrypting secrets at rest. REQUIRED in production (DEBUG=0) — the app refuses to boot without it. Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'. Pass via TF_VAR_fernet_key."
  type        = string
  sensitive   = true
}

# --- Google OAuth (availability calendar sync) -------------------------------

variable "google_client_id" {
  description = "Google OAuth 2.0 client ID. Reuse the Heroku value: heroku config:get GOOGLE_CLIENT_ID."
  type        = string
}

variable "google_client_secret" {
  description = "Google OAuth 2.0 client secret. Pass via TF_VAR_google_client_secret (reuse Heroku's)."
  type        = string
  sensitive   = true
}

# --- DigitalOcean Spaces (media stays here) ----------------------------------

variable "spaces_key" {
  type      = string
  sensitive = true
}

variable "spaces_secret" {
  type      = string
  sensitive = true
}

variable "spaces_bucket" {
  type = string
}

variable "spaces_endpoint" {
  description = "e.g. https://nyc3.digitaloceanspaces.com"
  type        = string
}

# --- Migration convenience ---------------------------------------------------

variable "operator_ip" {
  description = "Your public IP, to open the DB firewall for the one-time restore. Empty = skip."
  type        = string
  default     = ""
}