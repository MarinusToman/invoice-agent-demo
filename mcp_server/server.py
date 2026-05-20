"""
Invoice Agent MCP Server

Exposes the agent's capabilities to Claude Desktop via the Model Context Protocol.
Read-only tools execute immediately; write tools require explicit user confirmation.

Start: python mcp_server/server.py
Configure: add the snippet from claude_desktop_config.json to Claude Desktop settings.
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone

# Add agent directory to path so we can import shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from auth import get_services
from tools import check_duplicate, log_invoice, read_invoice_pdf, send_email

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

app = Server("invoice-agent")
_services = None
_pending_actions: dict[str, list] = {}   # session_id → proposed_actions


def _get_services():
    global _services
    if _services is None:
        _services = get_services()
    return _services


def _config() -> dict:
    return {
        "SPREADSHEET_ID": os.environ["SPREADSHEET_ID"],
        "MANAGER_EMAIL": os.environ.get("MANAGER_EMAIL", ""),
        "FINANCE_EMAIL": os.environ.get("FINANCE_EMAIL", ""),
        "AMOUNT_THRESHOLD": float(os.environ.get("AMOUNT_THRESHOLD", 5000)),
        "URGENT_DAYS": int(os.environ.get("URGENT_DAYS", 7)),
    }


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_invoices_due_soon",
            description="Read-only: list invoices from the Google Sheet due within N days.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to look ahead", "default": 7}
                },
            },
        ),
        Tool(
            name="get_invoice_summary",
            description="Read-only: return total invoices logged, total value, count of urgent invoices.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="check_invoice_status",
            description="Read-only: check whether a specific invoice number has been processed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_number": {"type": "string", "description": "Invoice number to look up"}
                },
                "required": ["invoice_number"],
            },
        ),
        Tool(
            name="process_new_invoices",
            description=(
                "Poll Gmail for new invoice emails and run Phase 1 analysis. "
                "Returns a summary of findings and proposed actions. "
                "Does NOT execute any write operations — call confirm_actions() "
                "only after the user has explicitly approved the proposed actions."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="confirm_actions",
            description=(
                "Execute specific approved actions from a previous process_new_invoices call. "
                "ONLY call this after the user has explicitly confirmed they want these actions taken. "
                "Pass the action IDs from the proposed_actions list."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID from process_new_invoices"},
                    "action_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs of actions to execute",
                    },
                },
                "required": ["session_id", "action_ids"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    services = _get_services()
    config = _config()

    if name == "list_invoices_due_soon":
        days = arguments.get("days", 7)
        result = _list_invoices_due_soon(services, config, days)
        return [TextContent(type="text", text=result)]

    elif name == "get_invoice_summary":
        result = _get_invoice_summary(services, config)
        return [TextContent(type="text", text=result)]

    elif name == "check_invoice_status":
        invoice_number = arguments["invoice_number"]
        result = check_duplicate(invoice_number, services["sheets"], config["SPREADSHEET_ID"])
        if result["is_duplicate"]:
            return [TextContent(type="text", text=f"Invoice {invoice_number} HAS been processed and is logged in the spreadsheet.")]
        else:
            return [TextContent(type="text", text=f"Invoice {invoice_number} has NOT been logged yet.")]

    elif name == "process_new_invoices":
        result = await _process_new_invoices(services, config)
        return [TextContent(type="text", text=result)]

    elif name == "confirm_actions":
        session_id = arguments["session_id"]
        action_ids = arguments["action_ids"]
        result = _confirm_actions(session_id, action_ids, services, config)
        return [TextContent(type="text", text=result)]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ── Tool implementations ──────────────────────────────────────────────────────

def _list_invoices_due_soon(services, config, days: int) -> str:
    try:
        result = services["sheets"].spreadsheets().values().get(
            spreadsheetId=config["SPREADSHEET_ID"],
            range="Invoices!A:G",
        ).execute()
        rows = result.get("values", [])[1:]  # skip header
        today = date.today()
        due_soon = []
        for row in rows:
            if len(row) >= 4 and row[3]:
                try:
                    due = date.fromisoformat(row[3])
                    delta = (due - today).days
                    if 0 <= delta <= days:
                        due_soon.append(f"• {row[0]} — {row[1]} — {row[4]} {row[5]} — due {row[3]} ({delta} days)")
                except ValueError:
                    pass
        if not due_soon:
            return f"No invoices due within the next {days} days."
        return f"Invoices due within {days} days:\n" + "\n".join(due_soon)
    except Exception as e:
        return f"Error reading spreadsheet: {e}"


def _get_invoice_summary(services, config) -> str:
    try:
        result = services["sheets"].spreadsheets().values().get(
            spreadsheetId=config["SPREADSHEET_ID"],
            range="Invoices!A:G",
        ).execute()
        rows = result.get("values", [])[1:]
        if not rows:
            return "No invoices have been logged yet."
        total = len(rows)
        total_value = sum(float(r[4]) for r in rows if len(r) > 4 and r[4])
        today = date.today()
        urgent = sum(
            1 for r in rows
            if len(r) > 3 and r[3]
            and (date.fromisoformat(r[3]) - today).days <= config["URGENT_DAYS"]
        )
        return (
            f"Invoice Summary:\n"
            f"• Total logged: {total}\n"
            f"• Total value: ${total_value:,.2f}\n"
            f"• Urgent (due within {config['URGENT_DAYS']} days): {urgent}"
        )
    except Exception as e:
        return f"Error reading spreadsheet: {e}"


async def _process_new_invoices(services, config) -> str:
    """Phase 1 analysis only. Returns text summary + stores proposed_actions for confirm_actions()."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "main", os.path.join(os.path.dirname(__file__), "..", "agent", "main.py")
    )
    main_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main_mod)

    emails = main_mod.fetch_invoice_emails(services["gmail"])
    if not emails:
        return "No unread invoice emails with PDF attachments found."

    from agent import analyze_invoice
    session_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    summary_lines = [f"Found {len(emails)} invoice email(s). Session ID: `{session_id}`\n"]

    all_proposed = []
    for email_data in emails:
        result = analyze_invoice(email_data, services, config)
        proposed = result["proposed_actions"]
        all_proposed.extend(proposed)
        summary_lines.append(f"**Email:** {email_data['subject']} (from {email_data['sender']})")
        summary_lines.append(result["analysis_text"])
        summary_lines.append("")

    _pending_actions[session_id] = all_proposed

    if all_proposed:
        summary_lines.append("**Proposed actions:**")
        for a in all_proposed:
            summary_lines.append(f"• `{a['id']}` — {a['description']}")
        summary_lines.append(
            f"\nTo execute approved actions, call `confirm_actions` with session_id=`{session_id}` "
            "and the action_ids you want to run."
        )
    else:
        summary_lines.append("No actions proposed.")

    return "\n".join(summary_lines)


def _confirm_actions(session_id: str, action_ids: list, services, config) -> str:
    proposed = _pending_actions.get(session_id)
    if not proposed:
        return f"No pending actions found for session `{session_id}`. Run process_new_invoices first."

    action_map = {a["id"]: a for a in proposed}
    results = []

    for action_id in action_ids:
        action = action_map.get(action_id)
        if not action:
            results.append(f"• `{action_id}` — not found in pending actions")
            continue

        tool = action["tool"]
        args = action["args"]

        if tool == "log_invoice":
            log_invoice(**args, sheets_service=services["sheets"], spreadsheet_id=config["SPREADSHEET_ID"])
            results.append(f"• ✅ `{action_id}` — invoice logged to Google Sheets")
        elif tool == "send_email":
            send_email(**args, gmail_service=services["gmail"])
            results.append(f"• ✅ `{action_id}` — email sent to {args.get('to', '?')}")
        else:
            results.append(f"• ⚠️ `{action_id}` — unknown tool `{tool}`")

    del _pending_actions[session_id]
    return "Actions executed:\n" + "\n".join(results)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
