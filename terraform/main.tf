terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }

  backend "s3" {
    # Pre-create this bucket before running terraform init
    bucket = "outreach-newsletter-terraform-state"
    key    = "dev/terraform.tfstate"
    region = "us-east-1"
  }
}
