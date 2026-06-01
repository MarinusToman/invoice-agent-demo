"""
Invoice Agent — entry point.

Runs two parallel activities:
  1. Weekly Gmail poll (background thread, configurable day/time via .env)
  2. Slack Socket Mode listener (main thread — handles on-demand triggers + button clicks)

Usage:
  python main.py          # start both (production mode)
  python main.py --once   # run Gmail poll immediately once, then exit (demo/test mode)
"""

import argparse
import base64
import os
import threading
import time
from datetime import datetime, timezone

import schedule
from dotenv import load_dotenv

load_dotenv()

from agent import analyze_invoice
from auth import get_services
from slack_approval import (
    post_approval_request,
    post_completion_summary,
    post_status_message,
    register_on_demand_callback,
    start_socket_mode,
    wait_for_all_decisions,
)
from tools import log_invoice, send_email


def load_config() -> dict:
    required = ["SPREADSHEET_ID", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL_ID"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in the values."
        )
    return {
        "SPREADSHEET_ID": os.environ["SPREADSHEET_ID"],
        "MANAGER_EMAIL": os.environ.get("MANAGER_EMAIL", ""),
        "FINANCE_EMAIL": os.environ.get("FINANCE_EMAIL", ""),
        "AMOUNT_THRESHOLD": float(os.environ.get("AMOUNT_THRESHOLD", 5000)),
        "URGENT_DAYS": int(os.environ.get("URGENT_DAYS", 7)),
        "POLL_WEEKDAY": int(os.environ.get("POLL_WEEKDAY", 0)),
        "POLL_HOUR": int(os.environ.get("POLL_HOUR", 9)),
        "OLLAMA_MODEL": os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
    }


def fetch_invoice_emails(gmail_service) -> list:
    """Return unread emails that have a PDF attachment."""
    results = gmail_service.users().messages().list(
        userId="me",
        q="has:attachment filename:pdf is:unread",
        maxResults=10,
    ).execute()

    emails = []
    for msg_ref in results.get("messages", []):
        msg = gmail_service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        sender = headers.get("From", "Unknown")
        subject = headers.get("Subject", "(no subject)")

        for part in msg["payload"].get("parts", []):
            if part.get("mimeType") == "application/pdf":
                attachment = gmail_service.users().messages().attachments().get(
                    userId="me",
                    messageId=msg_ref["id"],
                    id=part["body"]["attachmentId"],
                ).execute()

                emails.append({
                    "message_id": msg_ref["id"],
                    "sender": sender,
                    "subject": subject,
                    "attachment_base64": attachment["data"],
                })
                break  # one PDF per email is enough

    return emails


def execute_approved_actions(approved_ids: list, proposed_actions: list, services: dict, config: dict):
    """Run only the actions the human approved in Slack."""
    action_map = {a["id"]: a for a in proposed_actions}

    for action_id in approved_ids:
        action = action_map.get(action_id)
        if not action:
            continue

        tool = action["tool"]
        args = action["args"]
        print(f"\n[Executing]: {action['description']}")

        if tool == "log_invoice":
            result = log_invoice(
                **args,
                sheets_service=services["sheets"],
                spreadsheet_id=config["SPREADSHEET_ID"],
            )
        elif tool == "send_email":
            result = send_email(
                **args,
                gmail_service=services["gmail"],
            )
        else:
            result = {"error": f"Unknown tool: {tool}"}

        print(f"[Result]: {result}")


def poll_and_process(services: dict, config: dict):
    """Core pipeline: find invoice emails → analyze → ask Slack → execute approved actions."""
    print(f"\n{'='*60}")
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC] Checking Gmail for invoices...")

    emails = fetch_invoice_emails(services["gmail"])

    if not emails:
        print("No unread invoice emails found.")
        post_status_message("No new invoice emails found. Nothing to process.")
        return

    print(f"Found {len(emails)} invoice email(s).")

    for email_data in emails:
        print(f"\nProcessing: {email_data['subject']} (from {email_data['sender']})")

        # Phase 1 — automated analysis (read-only)
        result = analyze_invoice(email_data, services, config)
        proposed_actions = result["proposed_actions"]

        if not proposed_actions:
            print("[Agent returned no proposed actions — skipping this email]")
            # Still mark as read so we don't reprocess
            _mark_read(services["gmail"], email_data["message_id"])
            continue

        # Extract structured analysis for Slack display
        invoice_analysis = {
            "analysis": _extract_analysis_fields(result["analysis_text"]),
        }

        # Post to Slack and wait for human decisions
        print(f"\n[Posting to Slack for approval — {len(proposed_actions)} action(s) proposed]")
        ts = post_approval_request(invoice_analysis, proposed_actions)
        approved_ids = wait_for_all_decisions(ts, proposed_actions)

        # Phase 3 — execute approved actions
        print(f"\n[Approved: {approved_ids}]")
        execute_approved_actions(approved_ids, proposed_actions, services, config)

        # Post summary to Slack
        post_completion_summary(approved_ids, proposed_actions)

        # Mark email as read so it won't be picked up again
        _mark_read(services["gmail"], email_data["message_id"])
        print(f"\n[Email marked as read]")

    print(f"\n{'='*60}")
    print("Invoice processing complete.")


def _mark_read(gmail_service, message_id: str):
    try:
        gmail_service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
    except Exception as e:
        print(f"[Warning] Could not mark email as read: {e}")


def _extract_analysis_fields(analysis_text: str) -> dict:
    """Best-effort extraction of key invoice fields from the agent's analysis text."""
    import re, json

    # The agent may include a structured JSON block — try to find it
    match = re.search(r'\{[^{}]*"vendor_name"[^{}]*\}', analysis_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Fallback: return empty dict — Slack message will show placeholders
    return {}


def _schedule_loop(services: dict, config: dict):
    """Run the weekly schedule in a background thread."""
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day = days[config["POLL_WEEKDAY"]]
    hour = config["POLL_HOUR"]

    getattr(schedule.every(), day).at(f"{hour:02d}:00").do(
        poll_and_process, services=services, config=config
    )

    print(f"[Scheduler] Will check Gmail every {day.capitalize()} at {hour:02d}:00")

    while True:
        schedule.run_pending()
        time.sleep(60)


def main():
    parser = argparse.ArgumentParser(description="Invoice Agent")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run Gmail poll once immediately (demo/test mode), then exit",
    )
    args = parser.parse_args()

    config = load_config()
    services = get_services()

    if args.once:
        poll_and_process(services, config)
        return

    # Register the on-demand Slack trigger
    def on_demand():
        poll_and_process(services, config)

    register_on_demand_callback(on_demand)

    # Weekly schedule runs in a background thread
    schedule_thread = threading.Thread(
        target=_schedule_loop,
        args=(services, config),
        daemon=True,
    )
    schedule_thread.start()

    print("[Agent] Running. Listening for Slack messages and weekly schedule.")
    print("[Agent] Type 'process invoices' in your Slack channel to trigger on-demand.")

    # Slack Socket Mode blocks here — handles button clicks + on-demand messages
    start_socket_mode()


if __name__ == "__main__":
    main()
