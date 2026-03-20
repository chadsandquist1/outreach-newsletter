provider "aws" {
  region = var.aws_region
  default_tags { tags = var.tags }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
}

# ─── SES ────────────────────────────────────────────────────────────────────────

resource "aws_ses_email_identity" "sender" {
  email = var.sender_email
}

resource "aws_ses_email_identity" "recipient" {
  email = var.recipient_email
}

# ─── Bedrock Agent ──────────────────────────────────────────────────────────────

resource "aws_iam_role" "bedrock_agent" {
  name = "${var.project_name}-bedrock-agent"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "bedrock_agent" {
  name = "bedrock-agent-policy"
  role = aws_iam_role.bedrock_agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = "arn:aws:bedrock:${local.region}::foundation-model/${var.bedrock_model_id}"
      }
    ]
  })
}

resource "aws_bedrockagent_agent" "digest" {
  agent_name              = var.project_name
  agent_resource_role_arn = aws_iam_role.bedrock_agent.arn
  foundation_model        = var.bedrock_model_id
  idle_session_ttl_in_seconds = 600

  instruction = <<-EOT
    You are a LinkedIn content strategist specializing in retail strategy, merchandising,
    and consumer electronics. Your job is to research trending topics and generate a weekly
    digest of 3-10 LinkedIn post ideas.

    For each idea, provide EITHER:
    1. A FULL DRAFT POST (ready to edit and publish) — aim for 3-5 of these
    2. A TOPIC IDEA with angle, key talking points, and suggested hook — aim for 2-5 of these

    Guidelines for high-quality LinkedIn outreach posts:
    - Focus on CONTEXT over generic personalization. Reference specific industry events,
      comments, or trends rather than generic "congrats on your role" messages.
    - Identify LinkedIn influencers in retail/merchandising/consumer electronics and reference
      discussions happening in their comment sections.
    - Reference upcoming or recent LinkedIn Events in the retail/CPG/CE space.
    - Posts should be conversational, insight-driven, and position the author as a
      thoughtful voice in the space.
    - Include engagement hooks: questions, contrarian takes, data points, or "hot takes."
    - Vary formats: short text posts, carousel ideas, poll concepts, story-driven posts.

    Search the web for:
    - Recent retail strategy and merchandising news
    - Consumer electronics trends and product launches
    - LinkedIn influencer discussions in these spaces
    - Upcoming industry events (NRF, CES, Shoptalk, etc.)
    - Emerging topics in omnichannel, DTC, retail media networks

    Structure your output as JSON with this schema:
    {
      "digest_date": "YYYY-MM-DD",
      "post_ideas": [
        {
          "type": "draft" | "topic_idea",
          "title": "short descriptive title",
          "content": "full draft text OR topic description with talking points",
          "source_context": "what inspired this — article, trend, event",
          "engagement_angle": "why this will resonate / get replies",
          "suggested_hashtags": ["#tag1", "#tag2"],
          "format": "text_post" | "carousel" | "poll" | "story" | "article"
        }
      ]
    }
  EOT
}

# Web search action group: AMAZON.WebSearch is not yet supported in the
# Terraform AWS provider enum. Enable it manually in the Bedrock console
# after the agent is created: Agent → Action groups → Add → Built-in: Web search.

resource "aws_bedrockagent_agent_alias" "live" {
  agent_id         = aws_bedrockagent_agent.digest.id
  agent_alias_name = "live"
  description      = "Production alias"
}

# ─── Lambda ─────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "lambda-policy"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeAgent"]
        Resource = "arn:aws:bedrock:${local.region}:${local.account_id}:agent-alias/${aws_bedrockagent_agent.digest.id}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["ses:SendEmail", "ses:SendRawEmail"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "ses:FromAddress" = var.sender_email
          }
        }
      }
    ]
  })
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/../lambda/dist/function.zip"
}

resource "aws_lambda_function" "digest" {
  function_name    = var.project_name
  role             = aws_iam_role.lambda.arn
  handler          = "function.lambda_handler"
  runtime          = "python3.12"
  timeout          = 300
  memory_size      = 256
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  environment {
    variables = {
      RECIPIENT_EMAIL       = var.recipient_email
      SENDER_EMAIL          = var.sender_email
      BEDROCK_AGENT_ID      = aws_bedrockagent_agent.digest.id
      BEDROCK_AGENT_ALIAS_ID = aws_bedrockagent_agent_alias.live.agent_alias_id
    }
  }
}

# ─── EventBridge Scheduler ──────────────────────────────────────────────────────

resource "aws_iam_role" "scheduler" {
  name = "${var.project_name}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "invoke-lambda"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.digest.arn
    }]
  })
}

resource "aws_scheduler_schedule" "weekly_digest" {
  name       = "${var.project_name}-weekly"
  group_name = "default"

  flexible_time_window { mode = "OFF" }

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "America/Chicago"

  target {
    arn      = aws_lambda_function.digest.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}

# ─── Outputs ────────────────────────────────────────────────────────────────────

output "lambda_function_name" { value = aws_lambda_function.digest.function_name }
output "agent_id" { value = aws_bedrockagent_agent.digest.id }
output "schedule" { value = aws_scheduler_schedule.weekly_digest.schedule_expression }
