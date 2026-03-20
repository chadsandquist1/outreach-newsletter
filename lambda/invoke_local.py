#!/usr/bin/env python3
"""Local invocation script for the digest Lambda.

Usage:
    python invoke_local.py           # full run: calls Bedrock + sends email
    python invoke_local.py --dry-run # calls Bedrock, prints HTML, skips email
"""

import argparse
import os
import sys
from pathlib import Path

# Load .env before importing function (boto3 clients initialise at module level)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
else:
    print("Warning: no .env file found — ensure env vars are set in your shell", file=sys.stderr)

import function  # noqa: E402  (must come after env loading)


def main():
    parser = argparse.ArgumentParser(description="Invoke the digest Lambda locally")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Call Bedrock but skip sending the email; print HTML to stdout instead",
    )
    args = parser.parse_args()

    if args.dry_run:
        # Monkey-patch send_email so no SES call is made
        def _noop_send(html, date_str):
            print(f"\n--- DRY RUN: email would be sent to {os.environ.get('RECIPIENT_EMAIL')} ---")
            print(f"Subject: Your LinkedIn Post Ideas — Week of {date_str}\n")
            print(html)

        function.send_email = _noop_send
        print("Dry-run mode: Bedrock will be invoked but no email will be sent.\n")

    result = function.lambda_handler({}, None)
    import json

    print("\n--- Lambda result ---")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
