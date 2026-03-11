# Back Office Workflow Architecture

Back Office is the control plane for Cody Jo Method's product operations. It does four jobs:

1. Defines which repos exist and how they should be audited.
2. Runs department-specific audit agents across those repos.
3. Aggregates results into static dashboards and delivery metadata.
4. Publishes those dashboards to the protected admin surfaces and public handoff pages.

## System Topology

```mermaid
flowchart TD
    A[config/targets.yaml] --> B[local_audit_workflow.py]
    A --> C[scaffold-github-workflows.py]
    B --> D[agents/*.sh]
    D --> E[run-agent.sh]
    E --> F[results/<repo>/*-findings.json]
    F --> G[aggregate-results.py]
    F --> H[generate-delivery-data.py]
    G --> I[dashboard/*.html + *-data.json]
    H --> I
    I --> J[sync-dashboard.sh]
    J --> K[admin.* dashboards]
    J --> L[www.codyjo.com/back-office handoff]
    C --> M[target repo .github/workflows/*]
```

## What Each Layer Owns

### `config/targets.yaml`

This is the source of truth for local audit targets.

Each target can define:

- repo name
- absolute path
- language/runtime
- default departments
- lint, test, build, preview, deploy, and nightly command metadata
- product context for prompts and dashboard grouping

### `scripts/local_audit_workflow.py`

This is the reproducible local orchestration layer.

It supports four real commands:

- `list-targets`
- `refresh`
- `run-target`
- `run-all`

Operationally it does this:

```mermaid
flowchart TD
    A[run-target / run-all] --> B[Acquire .local-audit-run.lock]
    B --> C[Resolve targets + departments]
    C --> D[Run job-status.sh init]
    D --> E[Run department agent scripts]
    E --> F[Run job-status.sh finalize]
    F --> G[aggregate-results.py]
    F --> H[generate-delivery-data.py]
    G --> I[dashboard/data.json + dept payloads]
    H --> I
    I --> J[results/local-audit-log.*]
```

### `agents/*.sh`

Each department is explicit and separate.

Current local departments:

- `qa`
- `seo`
- `ada`
- `compliance`
- `monetization`
- `product`

This separation matters because Back Office is built around accountable lanes, not a single vague super-prompt.

### `scripts/aggregate-results.py`

This transforms raw findings into dashboard-ready payloads.

Outputs include:

- `dashboard/data.json`
- `dashboard/qa-data.json`
- `dashboard/seo-data.json`
- `dashboard/ada-data.json`
- `dashboard/compliance-data.json`
- `dashboard/monetization-data.json`
- `dashboard/product-data.json`
- `dashboard/automation-data.json`
- `dashboard/local-audit-log.json`

### `scripts/generate-delivery-data.py`

This inspects target repos and records delivery posture.

It is what powers reporting on:

- CI workflow coverage
- preview workflow coverage
- production deploy coverage
- nightly automation coverage
- delivery readiness

### `scripts/sync-dashboard.sh`

This is the Back Office publisher.

It uploads static dashboard assets to configured targets and invalidates CloudFront.

Current security posture:

- `admin.*` targets are the intended published dashboards
- non-admin public targets are skipped unless they explicitly set `allow_public_read: true`

## GitHub Workflow Model

Back Office itself has four workflow classes:

```mermaid
flowchart TD
    PR[Pull Request] --> CI[ci.yml]
    PR --> Preview[preview.yml]
    Main[Push to main] --> Deploy[deploy.yml]
    Schedule[Cron or manual] --> Nightly[nightly-backoffice.yml]
```

Those workflows mean:

- `ci.yml` validates non-main pushes and PRs.
- `preview.yml` produces dashboard artifacts for review.
- `deploy.yml` validates first, then publishes dashboards.
- `nightly-backoffice.yml` refreshes delivery metadata and publishes nightly artifacts.

## Target Repo Workflow Model

Back Office scaffolds four workflow types into product repos:

- CI
- preview
- CD
- nightly

These are generated from `templates/github-actions/` and then committed in the target repo.

Back Office does not own production by hiding it. It owns the starting standard and the reporting surface.

## Documentation Surfaces

GitHub-facing docs live here:

- [`README.md`](../README.md)
- [`docs/WORKFLOW-ARCHITECTURE.md`](./WORKFLOW-ARCHITECTURE.md)
- [`docs/CLI-REFERENCE.md`](./CLI-REFERENCE.md)
- [`docs/CICD-REFERENCE.md`](./CICD-REFERENCE.md)
- [`docs/LIVE-URLS.md`](./LIVE-URLS.md)

Published docs surfaces live in the dashboard:

- `dashboard/documentation.html`
- `dashboard/documentation-github.html`
- `dashboard/documentation-cicd.html`
- `dashboard/documentation-cli.html`
