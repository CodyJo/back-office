# Postal Rollout Checklist

## Preflight

- Stand up the shared Postal host and confirm API access.
- Create one Postal server/key per product, or document the temporary shared-key exception.
- Publish Postal shared DNS records.
- Publish each product `mail.` sending-domain DNS records.

## Fuel First

- Set Fuel envs:
  - `EMAIL_PROVIDER=postal`
  - `EMAIL_POSTAL_BASE_URL`
  - `EMAIL_POSTAL_SERVER_KEY`
  - `EMAIL_FROM_ADDRESS=no-reply@mail.fuel.codyjo.com`
- Deploy Fuel.
- Verify:
  - registration verification email
  - resend verification email
  - forgot-password code
  - reset-password completion
- Confirm the Dashboard no longer shows meals and Settings exposes the saved calorie target alongside the recommendation.

## Remaining Product Rollout

- CertStudy
- Selah
- Tarot
- Cordivent
- Cody Jo Method if/when an application email path exists

For each:

- set product sender envs
- deploy
- send all transactional auth emails
- confirm correct From domain
- confirm Postal logs
- confirm inbox placement

## Rollback Checklist

- Set `EMAIL_PROVIDER=resend`
- redeploy the affected repo
- verify mail resumes via Resend
- keep Postal DNS and credentials intact for retry after the issue is resolved

## Post-Rollout

- add webhook ingestion
- add bounce/suppression handling
- add delivery event logging
- remove Resend secrets only after at least one clean production cycle per product
