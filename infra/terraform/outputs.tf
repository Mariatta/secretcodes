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

output "database_url" {
  description = "Restore target for the migration. Sensitive — contains the password. View with: terraform output -raw database_url"
  value       = local.database_url
  sensitive   = true
}