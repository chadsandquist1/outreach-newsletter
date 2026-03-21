variable "aws_region" {
  default = "us-east-1"
}

variable "project_name" {
  default = "linkedin-outreach-digest"
}

variable "recipient_email" {
  description = "Email address to receive the weekly digest"
  type        = string
}

variable "sender_email" {
  description = "Verified SES sender email"
  type        = string
}

variable "schedule_expression" {
  description = "EventBridge schedule (default: Sundays at 6pm CT)"
  default     = "cron(0 23 ? * SUN *)" # 23:00 UTC = 6:00 PM CT
}

variable "bedrock_model_id" {
  description = "Bedrock foundation model for the agent"
  default     = "us.anthropic.claude-sonnet-4-6"
}

variable "bedrock_read_timeout" {
  description = "Read timeout in seconds for Bedrock agent invocation"
  default     = "180"
}

variable "tags" {
  default = {
    Project   = "linkedin-outreach-digest"
    ManagedBy = "terraform"
  }
}
