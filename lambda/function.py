"""Weekly LinkedIn outreach digest — Lambda orchestrator."""

import html
import json
import os
import uuid
from datetime import UTC, datetime

import boto3
from botocore.config import Config

_BEDROCK_TIMEOUT = int(os.environ.get("BEDROCK_READ_TIMEOUT", "180"))
bedrock_agent = boto3.client("bedrock-agent-runtime", config=Config(read_timeout=_BEDROCK_TIMEOUT))
ses = boto3.client("ses")

AGENT_ID = os.environ["BEDROCK_AGENT_ID"]
ALIAS_ID = os.environ["BEDROCK_AGENT_ALIAS_ID"]
RECIPIENT = os.environ["RECIPIENT_EMAIL"]
SENDER = os.environ["SENDER_EMAIL"]


def invoke_agent() -> str:
    """Invoke Bedrock Agent and collect streamed response."""
    today = datetime.now(UTC).strftime("%B %d, %Y")
    prompt = (
        f"Today is {today}. Search for the latest trending topics in retail strategy, "
        "merchandising, and consumer electronics. Then generate a weekly LinkedIn post "
        "digest with 3-10 post ideas — a mix of full draft posts and topic ideas with "
        "angles and talking points. Return ONLY valid JSON (no markdown fences) with this structure:\n"
        '{"digest_date": "YYYY-MM-DD", '
        '"intro": "2-3 sentence summary of this week\'s key themes and why these topics matter now", '
        '"post_ideas": [{'
        '"type": "draft or topic_idea", '
        '"title": "...", '
        '"content": "full post text for drafts; hook line followed by bullet talking points for topic ideas", '
        '"engagement_angle": "why this post will drive engagement", '
        '"suggested_hashtags": ["#tag1", "#tag2"], '
        '"format": "text_post, carousel, poll, or article", '
        '"source_context": "brief description of sources used", '
        '"source_links": [{"title": "source name or publication", "url": "https://full-url-if-available"}]'
        "}]}"
    )
    response = bedrock_agent.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=ALIAS_ID,
        sessionId=str(uuid.uuid4()),
        inputText=prompt,
    )
    chunks = []
    for event in response["completion"]:
        if "chunk" in event:
            chunks.append(event["chunk"]["bytes"].decode("utf-8"))
    return "".join(chunks)


def parse_digest(raw: str) -> dict:
    """Extract JSON from agent response, handling markdown fences."""
    cleaned = raw.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1]
    if "```" in cleaned:
        cleaned = cleaned.split("```", 1)[0]
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return {"raw_content": raw, "post_ideas": []}


def _esc(text: str) -> str:
    return html.escape(str(text))


def _trim(text: str, word_limit: int = 200) -> str:
    words = text.split()
    if len(words) <= word_limit:
        return text
    return " ".join(words[:word_limit]) + "…"


def build_html(digest: dict) -> str:
    """Render digest as a structured HTML email newsletter."""
    date = digest.get("digest_date", datetime.now(UTC).strftime("%Y-%m-%d"))
    intro = digest.get("intro", "")
    ideas = digest.get("post_ideas", [])

    if not ideas and "raw_content" in digest:
        return (
            '<html><body style="font-family:system-ui,sans-serif;max-width:700px;margin:auto;padding:20px">'
            f"<h1>LinkedIn Outreach Digest — {_esc(date)}</h1>"
            f'<div style="white-space:pre-wrap">{_esc(digest["raw_content"])}</div>'
            "</body></html>"
        )

    # Split by type, preserving original numbering for anchor links
    numbered = [(i + 1, idea) for i, idea in enumerate(ideas)]
    drafts = [(n, idea) for n, idea in numbered if idea.get("type") == "draft"]
    topics = [(n, idea) for n, idea in numbered if idea.get("type") != "draft"]

    # ── Table of Contents ────────────────────────────────────────────────────

    def toc_row(num, idea, is_draft):
        fmt = idea.get("format", "text_post").replace("_", " ").title()
        if is_draft:
            badge = '<span style="background:#dbeafe;color:#1d4ed8;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700">DRAFT</span>'
            link_color = "#1d4ed8"
        else:
            badge = '<span style="background:#ede9fe;color:#6d28d9;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700">TOPIC</span>'
            link_color = "#6d28d9"
        return (
            f'<tr style="border-bottom:1px solid #f3f4f6">'
            f'<td style="padding:8px 12px 8px 16px;width:70px">{badge}</td>'
            f'<td style="padding:8px 12px;font-size:13px">'
            f'<a href="#idea-{num}" style="color:{link_color};text-decoration:none;font-weight:500">'
            f"{_esc(idea.get('title', 'Untitled'))}</a></td>"
            f'<td style="padding:8px 16px 8px 12px;font-size:12px;color:#9ca3af;white-space:nowrap">{_esc(fmt)}</td>'
            f"</tr>"
        )

    toc_rows = "".join(toc_row(n, idea, True) for n, idea in drafts)
    toc_rows += "".join(toc_row(n, idea, False) for n, idea in topics)

    toc_html = (
        '<div style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;margin-top:16px">'
        '<div style="background:#f9fafb;padding:10px 16px;border-bottom:1px solid #e5e7eb">'
        '<span style="font-size:12px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:0.06em">'
        f"This Week — {len(ideas)} Ideas</span></div>"
        f'<table style="width:100%;border-collapse:collapse">{toc_rows}</table>'
        "</div>"
    )

    # ── Cards ────────────────────────────────────────────────────────────────

    def render_card(num, idea):
        is_draft = idea.get("type") == "draft"
        accent = "#2563eb" if is_draft else "#7c3aed"
        badge_bg = "#dbeafe" if is_draft else "#ede9fe"
        badge_fg = "#1d4ed8" if is_draft else "#6d28d9"
        badge_text = "DRAFT" if is_draft else "TOPIC IDEA"
        fmt = idea.get("format", "text_post").replace("_", " ").title()

        # Trim: 200 words for drafts, 160 for topic ideas (they're more structured)
        word_limit = 200 if is_draft else 160
        content_preview = _esc(_trim(idea.get("content", ""), word_limit)).replace("\n", "<br>")

        # Hashtag pills
        hashtags_html = " ".join(
            f'<span style="display:inline-block;background:#f3f4f6;color:#374151;'
            f'padding:2px 8px;border-radius:10px;font-size:11px;margin:2px 2px 2px 0">'
            f"{_esc(tag)}</span>"
            for tag in idea.get("suggested_hashtags", [])
        )

        # Reference links — only render entries that have a non-empty URL
        valid_links = [
            lnk for lnk in idea.get("source_links", []) if lnk.get("url", "").startswith("http")
        ]
        links_html = ""
        if valid_links:
            link_anchors = " &nbsp;·&nbsp; ".join(
                f'<a href="{_esc(lnk["url"])}" style="color:#2563eb;text-decoration:none;font-size:12px">'
                f"&#8599; {_esc(lnk.get('title', 'Source'))}</a>"
                for lnk in valid_links
            )
            links_html = (
                '<div style="margin-top:12px;padding-top:10px;border-top:1px solid #f3f4f6">'
                f'<span style="font-size:12px;font-weight:600;color:#6b7280">References: </span>{link_anchors}</div>'
            )

        return (
            f'<div id="idea-{num}" style="background:#fff;border:1px solid #e5e7eb;'
            f"border-left:4px solid {accent};border-radius:0 8px 8px 0;padding:20px 24px;margin-bottom:3px\">"
            # Badge row
            f'<div style="margin-bottom:12px">'
            f'<span style="background:{badge_bg};color:{badge_fg};padding:3px 10px;border-radius:20px;'
            f'font-size:11px;font-weight:700;text-transform:uppercase">{badge_text}</span>'
            f'<span style="background:#f3f4f6;color:#6b7280;padding:3px 8px;border-radius:20px;'
            f'font-size:11px;margin-left:6px">{_esc(fmt)}</span>'
            f'<span style="float:right;color:#d1d5db;font-size:11px">#{num}</span>'
            f"</div>"
            # Title
            f'<h3 style="margin:0 0 12px;color:#111827;font-size:16px;line-height:1.4;font-weight:600">'
            f"{_esc(idea.get('title', 'Untitled'))}</h3>"
            # Content preview
            f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:14px 16px;margin-bottom:14px">'
            f'<p style="margin:0;color:#374151;font-size:13px;line-height:1.75">{content_preview}</p>'
            f"</div>"
            # Metadata table
            f'<table style="width:100%;border-collapse:collapse;font-size:12px;color:#374151">'
            f"<tr>"
            f'<td style="padding:5px 12px 5px 0;width:105px;vertical-align:top;color:#6b7280;font-weight:600;white-space:nowrap">Why it works</td>'
            f'<td style="padding:5px 0;color:#374151;line-height:1.5">{_esc(idea.get("engagement_angle", ""))}</td>'
            f"</tr><tr>"
            f'<td style="padding:5px 12px 5px 0;vertical-align:top;color:#6b7280;font-weight:600;white-space:nowrap">Source context</td>'
            f'<td style="padding:5px 0;color:#374151;line-height:1.5">{_esc(idea.get("source_context", ""))}</td>'
            f"</tr><tr>"
            f'<td style="padding:5px 12px 5px 0;vertical-align:top;color:#6b7280;font-weight:600;white-space:nowrap">Hashtags</td>'
            f'<td style="padding:5px 0">{hashtags_html}</td>'
            f"</tr></table>"
            f"{links_html}"
            f"</div>"
        )

    draft_cards = "".join(render_card(n, idea) for n, idea in drafts)
    topic_cards = "".join(render_card(n, idea) for n, idea in topics)

    drafts_section = ""
    if draft_cards:
        drafts_section = (
            '<div style="background:#eff6ff;padding:12px 20px;border-left:4px solid #2563eb;'
            'border-radius:4px 0 0 4px;margin:24px 0 3px">'
            '<h2 style="margin:0;color:#1d4ed8;font-size:13px;font-weight:700;'
            'text-transform:uppercase;letter-spacing:0.07em">&#9998;&nbsp; Ready to Post — Full Drafts</h2>'
            f"</div>{draft_cards}"
        )

    topics_section = ""
    if topic_cards:
        topics_section = (
            '<div style="background:#f5f3ff;padding:12px 20px;border-left:4px solid #7c3aed;'
            'border-radius:4px 0 0 4px;margin:28px 0 3px">'
            '<h2 style="margin:0;color:#6d28d9;font-size:13px;font-weight:700;'
            'text-transform:uppercase;letter-spacing:0.07em">&#128161;&nbsp; Topic Ideas — Angles &amp; Talking Points</h2>'
            f"</div>{topic_cards}"
        )

    return (
        "<!DOCTYPE html><html>"
        '<body style="margin:0;padding:0;background:#f3f4f6;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif\">"
        '<div style="max-width:680px;margin:0 auto;padding:24px 16px">'
        # Header
        '<div style="background:#1e3a5f;border-radius:12px 12px 0 0;padding:28px 32px;text-align:center">'
        '<h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;letter-spacing:-0.3px">'
        "LinkedIn Outreach Digest</h1>"
        f'<p style="margin:6px 0 0;color:#93c5fd;font-size:13px">Week of {_esc(date)}</p>'
        "</div>"
        # Intro + TOC
        '<div style="background:#fff;padding:22px 32px 24px;border-bottom:1px solid #e5e7eb">'
        f'<p style="margin:0 0 6px;color:#374151;font-size:14px;line-height:1.7">{_esc(intro)}</p>'
        f'<p style="margin:0 0 0;color:#6b7280;font-size:12px">'
        f"{len(drafts)} ready-to-post draft{'s' if len(drafts) != 1 else ''} &nbsp;·&nbsp; "
        f"{len(topics)} topic idea{'s' if len(topics) != 1 else ''} to develop</p>"
        f"{toc_html}"
        "</div>"
        # Cards
        f'<div style="background:#f9fafb;padding:8px 32px 28px">'
        f"{drafts_section}{topics_section}"
        "</div>"
        # Footer
        '<div style="background:#fff;border-radius:0 0 12px 12px;padding:16px 32px;'
        'text-align:center;border-top:1px solid #e5e7eb">'
        '<p style="margin:0;color:#9ca3af;font-size:11px">'
        "Generated by your LinkedIn Outreach Digest &middot; Review and personalize before posting"
        "</p></div>"
        "</div></body></html>"
    )


def send_email(html_body: str, date_str: str):
    """Send the digest via SES."""
    ses.send_email(
        Source=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Message={
            "Subject": {"Data": f"Your LinkedIn Post Ideas — Week of {date_str}"},
            "Body": {"Html": {"Data": html_body}},
        },
    )


def lambda_handler(event, context):
    """Entrypoint: invoke agent → parse → format → send."""
    raw = invoke_agent()
    digest = parse_digest(raw)
    date_str = digest.get("digest_date", datetime.now(UTC).strftime("%Y-%m-%d"))
    html_body = build_html(digest)
    send_email(html_body, date_str)
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "Digest sent",
                "date": date_str,
                "post_count": len(digest.get("post_ideas", [])),
            }
        ),
    }
