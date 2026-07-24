terraform {
  required_version = ">= 1.5"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # Remote state keeps the source of truth off your laptop. Commented out so the
  # first `tofu init` works locally with zero setup. When ready, create a
  # state container and uncomment. The backend is itself a portability choice:
  # azurerm below ties state to Azure; if you'd rather keep state vendor-neutral
  # you can use an S3-compatible backend pointed at DigitalOcean Spaces instead.
  #
  # backend "azurerm" {
  #   resource_group_name  = "tfstate-rg"
  #   storage_account_name = "secretcodestfstate"
  #   container_name       = "tfstate"
  #   key                  = "secretcodes.tfstate"
  # }
}

provider "azurerm" {
  features {}

  # azurerm v4 requires the subscription explicitly. Either set it here via the
  # variable, or (preferred — keeps it out of code) export ARM_SUBSCRIPTION_ID
  # in your shell and leave the variable null.
  subscription_id = var.subscription_id
}