variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "back-office"
}

variable "dashboard_domains" {
  description = "List of domains to serve the dashboard on (each needs its own S3 bucket + CloudFront)"
  type = list(object({
    domain    = string
    bucket    = string
    cf_id     = string  # Existing CloudFront distribution ID (leave empty to create new)
    s3_path   = string  # Path in bucket for backoffice.html (e.g., 'backoffice.html')
  }))
  default = []
}
