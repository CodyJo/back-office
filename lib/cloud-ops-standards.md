# Cloud Ops Standards Reference

Serverless AWS infrastructure checklist for Well-Architected Review. Scoped to: Lambda, DynamoDB, S3, CloudFront, IAM, Terraform, CodeBuild, Route53, ACM.

Enterprise patterns excluded: Transit Gateway, multi-account, Control Tower, Organizations, Service Catalog.

## Cost Optimization (30%)

| Check | What to look for in Terraform | Severity |
|-------|-------------------------------|----------|
| Lambda architecture | `architectures` missing or set to `["x86_64"]` — arm64 is ~20% cheaper | Medium |
| Lambda memory | `memory_size` at default 128MB or set much higher than needed | Medium |
| DynamoDB billing mode | `billing_mode = "PROVISIONED"` for low/variable-traffic tables — on-demand (`PAY_PER_REQUEST`) is cheaper below ~25% utilization | High |
| S3 lifecycle policy | No `lifecycle_rule` on buckets — old objects accumulate cost | Medium |
| CloudFront price class | `price_class = "PriceClass_All"` when `PriceClass_100` (US/EU only) suffices | Low |
| Unused resources | Resources defined in Terraform but never referenced or no longer needed | High |
| Missing cost tags | No `tags` block or missing `Project`/`Environment`/`CostCenter` tags | Low |
| NAT Gateway | NAT Gateway for Lambda VPC when not required | Critical |
| CloudWatch log retention | `retention_in_days` not set (defaults to never expire — unbounded cost) | Medium |
| Provisioned concurrency | `provisioned_concurrent_executions` set when traffic doesn't justify it | Medium |

## Security (25%)

| Check | What to look for in Terraform | Severity |
|-------|-------------------------------|----------|
| IAM wildcard actions | `actions = ["*"]` or `actions = ["s3:*"]` in IAM policy statements | Critical |
| IAM wildcard resources | `resources = ["*"]` when a specific ARN would work | High |
| S3 public access | Missing `aws_s3_bucket_public_access_block` or `block_public_acls = false` | Critical |
| S3 encryption | Missing `aws_s3_bucket_server_side_encryption_configuration` | High |
| DynamoDB encryption | Missing `server_side_encryption` block (defaults to AWS-owned key, not KMS) | Medium |
| Lambda env var encryption | Sensitive values in `environment.variables` without KMS encryption | High |
| Missing KMS rotation | `enable_key_rotation = false` or missing on KMS keys | Medium |
| Security group egress | `egress` rule with `cidr_blocks = ["0.0.0.0/0"]` when restrictable | Medium |
| Secrets in Terraform | Hardcoded passwords, API keys, or tokens in `.tf` files | Critical |
| IAM role sharing | Multiple Lambda functions sharing one overprivileged role | High |

## Reliability (20%)

| Check | What to look for in Terraform | Severity |
|-------|-------------------------------|----------|
| Lambda DLQ | Missing `dead_letter_config` on async Lambda functions | High |
| Lambda retry config | Missing `maximum_retry_attempts` on event source mappings | Medium |
| DynamoDB PITR | `point_in_time_recovery` not enabled | High |
| S3 versioning | `versioning` not enabled on data buckets | Medium |
| CloudFront error pages | Missing `custom_error_response` blocks | Low |
| Lambda timeout | `timeout` at default 3s for functions that may take longer | Medium |
| DynamoDB backup | No `aws_dynamodb_table_replica` or backup plan | Medium |
| API Gateway throttling | Missing `throttle_settings` on API Gateway stages | Medium |
| Single-region | All resources in one region with no DR consideration | Info |
| Missing error handling | Lambda event source mappings without `on_failure` destination | High |

## Performance Efficiency (10%)

| Check | What to look for in Terraform | Severity |
|-------|-------------------------------|----------|
| Lambda memory tuning | `memory_size = 128` (default) — likely undertuned for most workloads | Medium |
| CloudFront cache policy | Missing `cache_policy_id` or using `CachingDisabled` for static assets | High |
| CloudFront compression | Missing `compress = true` in cache behavior | Medium |
| DynamoDB GSI | Table with diverse query patterns but no Global Secondary Indexes | Medium |
| Lambda arm64 | Using x86_64 when arm64 (graviton) is ~20% faster and cheaper | Low |
| CloudFront TTL | `default_ttl = 0` or very short TTL for cacheable content | Medium |
| API Gateway caching | No `cache_cluster_enabled` on frequently-hit GET endpoints | Low |
| Lambda layers | Large deployment packages that could use layers for shared deps | Info |

## Operational Excellence (10%)

| Check | What to look for in Terraform | Severity |
|-------|-------------------------------|----------|
| Missing CloudWatch alarms | No `aws_cloudwatch_metric_alarm` for Lambda errors/throttles | High |
| Log retention | `retention_in_days` not set on CloudWatch log groups | Medium |
| Missing resource tags | Resources without `tags` block or inconsistent tagging | Medium |
| Terraform state locking | No DynamoDB table for state locking in backend config | High |
| Terraform modules | Copy-pasted resource blocks that could be modules | Low |
| Missing outputs | No `output` blocks for cross-stack references | Low |
| CI/CD gaps | Missing CodeBuild project for a deployed service | Medium |
| No Terraform fmt | `.tf` files not consistently formatted | Info |
| Missing variable descriptions | `variable` blocks without `description` field | Low |
| Missing backend config | No `backend` block in Terraform configuration | High |

## Sustainability (5%)

| Check | What to look for in Terraform | Severity |
|-------|-------------------------------|----------|
| Right-sizing | Over-provisioned resources (Lambda memory, DynamoDB capacity) | Medium |
| Provisioned to on-demand | `PROVISIONED` billing that could be `PAY_PER_REQUEST` | Medium |
| x86 to arm64 | Lambda using x86_64 where arm64 is viable | Low |
| Unused log groups | CloudWatch log groups with no retention and no active function | Low |

## Scoring

Each pillar starts at 100, deductions by severity:
- Critical: -15
- High: -8
- Medium: -3
- Low: -1
- Info: no deduction
- Floor: 0

Composite: `cloud_ops_score = round(cost*0.30 + security*0.25 + reliability*0.20 + perf*0.10 + ops*0.10 + sustain*0.05)`

Score interpretation:
- **90-100**: Excellent infrastructure health
- **70-89**: Good, minor improvements needed
- **50-69**: Fair, significant issues to address
- **Below 50**: Poor, critical infrastructure problems
