# Secret Codes: Infrastructure

Operational documentation for the **secretcodes** platform: how it's built,
deployed, and moved between hosts.

## Guiding principle

Every piece of this stack is a generic primitive, not a vendor-flavored one:

- The app ships as a **container image** in a neutral registry.
- Config is **environment variables only**, the portability contract.
- The database is **plain PostgreSQL**, reached over a standard connection string.
- Static/media lives in **S3-compatible object storage** (DigitalOcean Spaces).

The payoff is that any single piece can move independently, and leaving a
provider costs one planned maintenance window, measured in minutes, not a
rewrite. Leaving as cleanly as arriving is the design goal.

## Map of these docs

- **[Architecture](architecture/overview.md):** what the platform is made of and
  how the parts connect.
- **[Deployment → Azure](deployment/azure.md):** the App Service + Postgres
  target and how the app is built and shipped.
- **[Deployment → Terraform](deployment/terraform.md):** the infrastructure as
  code that provisions the Azure side.
- **[Deployment → Migration](deployment/migration.md):** the Heroku to Azure
  cutover, and the reverse playbook for leaving Azure.
- **[Runbooks](runbooks/index.md):** operational procedures.
- **[Reference](reference/index.md):** reference material that grows with the
  platform.

!!! note "Docs vs product docs"
    This site documents *infrastructure and engineering*, tightly coupled to
    the code and updated in the same pull requests. Customer-facing product docs
    (the MCP/API reference) will get their own home once there's an audience
    that differs from the engineering reader.
