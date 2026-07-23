# Deployment: staging environment

A full clone of prod in its own Azure resource group, plus the social-publishing
runtime (Redis broker + Celery worker + beat). Its purpose: run a **PR branch**
against **its own database** so publishing can be exercised end to end before the
change reaches prod.

Staging is the same Terraform as prod, driven by a distinct `name_prefix` and a
separate Terraform **workspace**, so an apply here can never touch prod.

## What it provisions

With `enable_publishing = true`, one `terraform apply` in the `staging` workspace
creates, all prefixed `secretcodes-staging-`:

| Resource | Role |
|---|---|
| `-rg` | resource group holding everything below |
| `-pg` | Postgres Flexible Server — **separate database from prod** |
| `-redis` | Azure Cache for Redis (Basic C0), the Celery broker |
| `-web` | the web app (App Service) |
| `-worker` | Celery worker (App Service, same image, `CONTAINER_ROLE=worker`) |
| `-beat` | Celery beat (App Service, `CONTAINER_ROLE=beat`) |
| `-plan` | the shared B1 App Service plan |

One image, three roles. `entrypoint.sh` switches on `CONTAINER_ROLE`; the worker
and beat run a tiny [`healthping`](../../secretcodes/healthping.py) responder so
App Service's startup probe passes on a container that otherwise binds no port.

## One-time setup

1. **Staging service principal.** The deploy workflow needs Contributor on the
   staging resource group. Create it *after* the group exists (step 4), or scope
   it at the subscription:

   ```bash
   az ad sp create-for-rbac --name secretcodes-staging-deploy --role contributor \
     --scopes "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/secretcodes-staging-rg" \
     --sdk-auth > creds.json
   gh secret set AZURE_CREDENTIALS_STAGING < creds.json && rm creds.json
   ```

   Kept separate from prod's `AZURE_CREDENTIALS` so a staging deploy can't reach
   prod.

2. **tfvars.** Copy the example and fill it in:

   ```bash
   cp infra/terraform/staging.tfvars.example infra/terraform/staging.tfvars
   ```

   Secrets go in `TF_VAR_*` env vars, not the file (see the comments in it).
   Use a **new** `postgres_admin_password`; reuse prod's `FERNET_KEY` only if you
   intend to copy encrypted rows across, otherwise a fresh key is fine.

## Provision

From `infra/terraform/`:

```bash
terraform workspace new staging      # first time only
terraform workspace select staging
terraform apply -var-file=staging.tfvars
```

!!! warning "Always check the workspace before applying"
    `terraform workspace show` should print `staging`. The default workspace is
    prod. The workspace is the only thing keeping the two states apart.

## Deploy a PR branch to staging

1. Push the branch you want to test.
2. Actions → **Deploy to staging** → **Run workflow** → pick the branch.

   It builds that branch as `ghcr.io/<owner>/secretcodes:staging` and points all
   three staging apps at it. Prod keeps running `:latest`, untouched.

3. Watch it come up:

   ```bash
   az webapp log tail -g secretcodes-staging-rg -n secretcodes-staging-web
   az webapp log tail -g secretcodes-staging-rg -n secretcodes-staging-worker
   az webapp log tail -g secretcodes-staging-rg -n secretcodes-staging-beat
   ```

   `web` migrates on boot; `worker`/`beat` may crash-loop for a few seconds until
   those migrations land (they need the `django_celery_beat` tables), then go
   green. That is expected on a first deploy.

## Verify publishing end to end

1. Open `https://secretcodes-staging-web.azurewebsites.net/content/publishing/accounts/`
   and connect a Mastodon account (use a test account).

   The Mastodon redirect URI is derived from the staging host, so register
   `https://secretcodes-staging-web.azurewebsites.net/content/publishing/connect/mastodon/callback/`
   if the instance pins redirect URIs.

2. Create a board → campaign → a **mastodon** post, set it to **scheduled** with
   a `scheduled_at` in the past.

3. Create the `Publication` (no UI for this until the M5 queue screen):

   ```bash
   az webapp ssh -g secretcodes-staging-rg -n secretcodes-staging-web
   python manage.py shell
   ```
   ```python
   from django.utils import timezone
   from content_planner.models import Post, PublishingAccount, Publication
   post = Post.objects.get(title="YOUR TITLE")
   acct = PublishingAccount.objects.get(platform="mastodon")
   Publication.objects.create(post=post, account=acct, scheduled_for=timezone.now())
   ```

4. Within a minute the `beat` log shows `Sending due task … dispatch_due_publications`,
   the `worker` log shows `publishing … to mastodon`, and the post lands on the
   timeline. `Publication.state` becomes `sent` with `remote_url` filled in.

   Images work on staging (unlike localhost): assets live in Spaces, which
   Mastodon can fetch.

## Tear down

Staging costs run while it exists. To stop paying between test sessions:

```bash
terraform workspace select staging
terraform destroy -var-file=staging.tfvars
```

The workspace and state remain, so a later `apply` rebuilds it. Leave the default
(prod) workspace alone.
