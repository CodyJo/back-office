# ---------------------------------------------------------
# CodeBuild CI/CD (replaces GitHub Actions)
# ---------------------------------------------------------

module "codebuild" {
  source = "git::https://github.com/CodyJo/codyjo.com.git//terraform/modules/codebuild?ref=codebuild-module-v1"

  project_name       = "back-office"
  github_repo        = "CodyJo/back-office"
  deploy_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Deploy"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::admin-thenewbeautifulme-site",
          "arn:aws:s3:::admin-thenewbeautifulme-site/*",
        ]
      },
      {
        Sid    = "CloudFront"
        Effect = "Allow"
        Action = [
          "cloudfront:CreateInvalidation",
        ]
        Resource = "arn:aws:cloudfront::*:distribution/E372ZR95FXKVT5"
      },
    ]
  })
}
