output "app_url" {
  description = "Public URL of the web app."
  value       = "https://${azurerm_linux_web_app.web.default_hostname}"
}

output "app_name" {
  value = azurerm_linux_web_app.web.name
}

output "resource_group" {
  value = azurerm_resource_group.rg.name
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.pg.fqdn
}

output "worker_app_name" {
  description = "Celery worker App Service name, when publishing is enabled."
  value       = var.enable_publishing ? azurerm_linux_web_app.worker[0].name : null
}

output "beat_app_name" {
  description = "Celery beat App Service name, when publishing is enabled."
  value       = var.enable_publishing ? azurerm_linux_web_app.beat[0].name : null
}

output "database_url" {
  description = "Restore target for the migration. Sensitive — contains the password. View with: terraform output -raw database_url"
  value       = local.database_url
  sensitive   = true
}