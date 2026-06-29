# Runbooks

Operational procedures: the things done *to* a running system, written down
so they're calm and repeatable instead of improvised under pressure.

## Available

- **[Heroku → Azure migration](../deployment/migration.md):** initial move and
  the reverse-direction exit.

## To write (stubs)

Create a page per procedure as the need arises. Good candidates:

- **Restore from backup:** point-in-time restore on Flexible Server; how to
  verify the restored copy before promoting it.
- **Rotate secrets:** `SECRET_KEY`, DB password, Spaces keys, GHCR PAT; the
  order of operations so nothing drops.
- **Scale up / down:** change the App Service plan or Postgres SKU; what
  reschedules, what causes a restart.
- **Promote a hotfix:** fast-path a single commit through the pipeline.
- **Incident response:** where logs live, how to read them, how to roll back a
  bad deploy (redeploy the previous image tag).

!!! tip
    Each runbook should be copy-pasteable end to end and start with a one-line
    "when to use this." Clarity written down now pays off under stress later.
