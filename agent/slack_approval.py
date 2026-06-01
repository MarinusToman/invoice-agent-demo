import os
import re
import threading
from datetime import datetime, timezone

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Shared state ──────────────────────────────────────────────────────────────
# Maps Slack message timestamp → {action_id: "approved" | "skipped" | "pending"}
_approval_state: dict[str, dict[str, str]] = {}
_approval_lock = threading.Lock()

# Callback registered by main.py so Slack trigger can invoke the poll
_on_demand_callback = None

# ── App setup ─────────────────────────────────────────────────────────────────
app = App(token=os.environ["SLACK_BOT_TOKEN"])


def register_on_demand_callback(fn):
    """Register the function to call when user types 'process invoices' in Slack."""
    global _on_demand_callback
    _on_demand_callback = fn


# ── Approval message builder ──────────────────────────────────────────────────

def _build_approval_blocks(invoice_analysis: dict, proposed_actions: list) -> list:
    analysis = invoice_analysis.get("analysis", {})
    vendor = analysis.get("vendor_name", "Unknown Vendor")
    amount = analysis.get("total_amount", 0)
    currency = analysis.get("currency", "USD")
    due_date = analysis.get("due_date", "Unknown")
    invoice_number = analysis.get("invoice_number", "Unknown")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📄 New Invoice Requires Your Review"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Vendor:*\n{vendor}"},
                {"type": "mrkdwn", "text": f"*Invoice #:*\n{invoice_number}"},
                {"type": "mrkdwn", "text": f"*Amount:*\n{currency} {amount:,.2f}"},
                {"type": "mrkdwn", "text": f"*Due Date:*\n{due_date}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Agent recommends the following actions. Approve or skip each one:*",
            },
        },
    ]

    for action in proposed_actions:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"• {action['description']}"},
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve"},
                        "style": "primary",
                        "action_id": f"approve_{action['id']}",
                        "value": action["id"],
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Skip"},
                        "action_id": f"skip_{action['id']}",
                        "value": action["id"],
                    },
                ],
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "🔒 _Nothing will execute until you approve. The AI runs locally — your data never left this machine._",
                }
            ],
        }
    )
    return blocks


def post_approval_request(invoice_analysis: dict, proposed_actions: list) -> str:
    """
    Post an approval message to Slack. Returns the message timestamp (ts)
    which is used to track which approvals belong to this invoice.
    """
    vendor = invoice_analysis.get("analysis", {}).get("vendor_name", "Unknown")
    blocks = _build_approval_blocks(invoice_analysis, proposed_actions)

    result = app.client.chat_postMessage(
        channel=os.environ["SLACK_CHANNEL_ID"],
        blocks=blocks,
        text=f"New invoice from {vendor} needs your review",
    )

    ts = result["ts"]
    with _approval_lock:
        _approval_state[ts] = {action["id"]: "pending" for action in proposed_actions}

    return ts


def wait_for_all_decisions(ts: str, proposed_actions: list, timeout_seconds: int = 3600) -> list:
    """
    Block until every proposed action has been approved or skipped (or timeout).
    Returns the list of approved action IDs.
    """
    import time

    deadline = time.time() + timeout_seconds
    action_ids = {action["id"] for action in proposed_actions}

    while time.time() < deadline:
        with _approval_lock:
            decisions = _approval_state.get(ts, {})
            pending = [aid for aid in action_ids if decisions.get(aid) == "pending"]
            if not pending:
                approved = [aid for aid in action_ids if decisions.get(aid) == "approved"]
                return approved
        time.sleep(2)

    # Timeout — treat all remaining pending as skipped
    print("[Warning] Approval timed out after 1 hour. Skipping remaining actions.")
    with _approval_lock:
        decisions = _approval_state.get(ts, {})
    return [aid for aid, status in decisions.items() if status == "approved"]


def _update_button(body, action_id: str, approved: bool):
    """Replace the action's buttons with a static confirmation label."""
    label = "✅ Approved" if approved else "❌ Skipped"
    blocks = body["message"]["blocks"]

    for block in blocks:
        if block.get("type") == "actions":
            ids = {el.get("action_id") for el in block.get("elements", [])}
            if f"approve_{action_id}" in ids or f"skip_{action_id}" in ids:
                block["elements"] = [{
                    "type": "button",
                    "text": {"type": "plain_text", "text": label},
                    "action_id": f"done_{action_id}",
                }]

    app.client.chat_update(
        channel=body["container"]["channel_id"],
        ts=body["message"]["ts"],
        blocks=blocks,
        text=body["message"].get("text", ""),
    )


# ── Action handlers ───────────────────────────────────────────────────────────

@app.action(re.compile(r"^approve_"))
def handle_approve(ack, body, action):
    ack()
    action_id = action["action_id"].replace("approve_", "")
    ts = body["message"]["ts"]
    with _approval_lock:
        if ts in _approval_state:
            _approval_state[ts][action_id] = "approved"
    _update_button(body, action_id, approved=True)


@app.action(re.compile(r"^skip_"))
def handle_skip(ack, body, action):
    ack()
    action_id = action["action_id"].replace("skip_", "")
    ts = body["message"]["ts"]
    with _approval_lock:
        if ts in _approval_state:
            _approval_state[ts][action_id] = "skipped"
    _update_button(body, action_id, approved=False)


@app.action(re.compile(r"^done_"))
def handle_done(ack, body, action):
    ack()  # Already decided — ignore re-clicks


# ── On-demand trigger ─────────────────────────────────────────────────────────

def _trigger_on_demand(client):
    client.chat_postMessage(
        channel=os.environ["SLACK_CHANNEL_ID"],
        text="📬 Starting invoice check now — I'll post results here shortly.",
    )
    if _on_demand_callback:
        threading.Thread(target=_on_demand_callback, daemon=True).start()


@app.message("process invoices")
def on_demand(message, say, client):
    _trigger_on_demand(client)


@app.shortcut("process_invoices")
def handle_shortcut(ack, client):
    ack()
    _trigger_on_demand(client)


# ── Status messages ───────────────────────────────────────────────────────────

def post_status_message(text: str):
    """Post a plain text status update to the channel."""
    app.client.chat_postMessage(
        channel=os.environ["SLACK_CHANNEL_ID"],
        text=text,
    )


# ── Confirmation message ──────────────────────────────────────────────────────

def post_completion_summary(approved_ids: list, all_actions: list):
    """Post a final summary to Slack after all approved actions have run."""
    executed = [a["description"] for a in all_actions if a["id"] in approved_ids]
    skipped = [a["description"] for a in all_actions if a["id"] not in approved_ids]

    lines = ["*✅ Invoice processing complete*\n"]
    if executed:
        lines.append("*Executed:*")
        lines.extend(f"  • {d}" for d in executed)
    if skipped:
        lines.append("\n*Skipped:*")
        lines.extend(f"  • {d}" for d in skipped)

    app.client.chat_postMessage(
        channel=os.environ["SLACK_CHANNEL_ID"],
        text="\n".join(lines),
    )


# ── Socket Mode entry point ───────────────────────────────────────────────────

def start_socket_mode():
    """Start the Slack Socket Mode handler (blocking). Call from the main thread."""
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
