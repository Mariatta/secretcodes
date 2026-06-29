# Reference

Placeholder for reference material that grows with the platform, especially as
secretcodes gains a surface other people consume.

## Likely sections

- **API reference:** once there's a public API. Consider enabling the
  `mkdocstrings` plugin (commented in `mkdocs.yml`) to generate this straight
  from Python docstrings, so it stays in-repo and can't drift from the code.
- **MCP server:** the tools exposed at `/mcp/`, their inputs/outputs, and the
  availability data model behind them.
- **Configuration reference:** every environment variable, what it does, and
  its default.

!!! note "When to split this out"
    Customer-facing product docs have a different audience and release cadence
    than engineering docs. When that divergence starts to hurt (doc-only PRs
    cluttering the app, a separate docs domain, external doc contributors), give
    product docs their own repo and deployment. Keep infra/engineering docs here.

## Versioning

When the API has versions worth documenting separately, add the `mike` plugin
for versioned docs (v1 / v2 / latest).
