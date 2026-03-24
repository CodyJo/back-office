resource "aws_budgets_budget" "account_monthly" {
  name         = "${var.project_name}-account-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.account_monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.billing_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.billing_alert_email]
  }
}

resource "aws_budgets_budget" "cloudfront_monthly" {
  name         = "${var.project_name}-cloudfront-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.cloudfront_monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "Service"
    values = ["Amazon CloudFront"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.billing_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.billing_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.billing_alert_email]
  }
}

resource "aws_ce_anomaly_monitor" "cloudfront" {
  name         = "${var.project_name}-cloudfront"
  monitor_type = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "cloudfront" {
  name           = "${var.project_name}-cloudfront-anomalies"
  frequency      = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.cloudfront.arn]

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.cloudfront_anomaly_threshold_usd)]
    }
  }

  subscriber {
    type    = "EMAIL"
    address = var.billing_alert_email
  }
}

output "billing_alert_email" {
  description = "Email address receiving billing alerts"
  value       = var.billing_alert_email
}

output "cloudfront_anomaly_monitor_arn" {
  description = "Service-level cost anomaly monitor ARN used to catch CloudFront spend spikes"
  value       = aws_ce_anomaly_monitor.cloudfront.arn
}
