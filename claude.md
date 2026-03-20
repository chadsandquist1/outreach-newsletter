# outreach-newsletter

Weekly LinkedIn post digest delivered by email. A Bedrock agent researches trending topics in retail, merchandising, and consumer electronics, then generates 3–10 post ideas (mix of full drafts and topic outlines) and emails them via SES every Sunday at 6pm CT.

---

## Deployment

**Merging to `main` triggers a full deploy automatically via GitHub Actions.**

### What happens on push to main

1. **`lambda-build`** — installs Python deps (`pip install -r requirements.txt -t package/`), zips deps + `function.py` into `lambda/lambda.zip`, uploads as a workflow artifact.
2. **`terraform-apply`** — downloads the artifact, runs `terraform init` + `terraform plan -out=tfplan` + `terraform apply -auto-approve`. Reads credentials from GitHub secrets.

### What happens on a pull request

1. **`lambda-build`** — same as above.
2. **`terraform-plan`** — runs plan only, posts the plan output as a PR comment. No resources are created.

### GitHub secrets required

| Secret | Description |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM deployment credentials |
| `AWS_SECRET_ACCESS_KEY` | IAM deployment credentials |
| `TF_VARS_SENSITIVE` | Sensitive tfvars lines appended to `dev.tfvars` at runtime (valid HCL: `key = "value"`) |
| `ANTHROPIC_API_KEY` | For the Claude code-review workflow |

### Terraform state

Stored in S3: `s3://outreach-newsletter-terraform-state/dev/terraform.tfstate` (us-east-1). Bucket was pre-created manually before first `terraform init`.

### Known limitation — Lambda zip strategy

`terraform/lambda.tf` uses an `archive_file` data source to build the Lambda zip at plan time. The CI-built zip (which runs `pip install`) is downloaded but currently unused by Terraform. With an empty `requirements.txt` this is fine. **Once Python dependencies are added**, switch the Lambda resource to use `filename = "../lambda/lambda.zip"` (the CI artifact) instead of `data.archive_file.lambda.output_path`.

---

## Manual step after first deploy

Enable the **Web Search** built-in action group on the Bedrock agent — the Terraform AWS provider doesn't support `AMAZON.WebSearch` in its enum yet:

1. AWS Console → Bedrock → Agents → `linkedin-outreach-digest`
2. Action groups → Add → Built-in: **Web Search** → Save
3. Prepare the agent

---

## SES sandbox

SES starts in sandbox mode. Sender and recipient are both `chadsandquist@gmail.com` (verified), so the digest works out of the box. To add other recipients, request SES production access in the AWS console.
