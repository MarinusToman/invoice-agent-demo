import json
import os
import re
from datetime import date, datetime, timezone

import ollama

from tools import (
    READ_ONLY_TOOL_SCHEMAS,
    check_duplicate,
    read_invoice_pdf,
)

SYSTEM_PROMPT = """You are an invoice analysis agent. Your job is to analyze invoice emails and propose actions.

You work in TWO phases:

PHASE 1 — Analysis (you execute tool calls now):
1. Call read_invoice_pdf to extract data from the PDF attachment
2. Call check_duplicate to verify this invoice hasn't been logged before
3. Reason about the invoice:
   - Is it a duplicate?
   - Is the due date within {URGENT_DAYS} days of today ({TODAY})?
   - Does the total amount exceed ${AMOUNT_THRESHOLD}?

PHASE 2 — Propose actions (end your response with this block):
After your analysis, output a <proposed_actions> XML block listing what you recommend.
You must NOT call log_invoice or send_email yourself — only propose them.

Available action types:
- log_invoice: Always propose this unless it's a duplicate
- send_urgent_reminder: Propose if due within {URGENT_DAYS} days
- send_approval_request: Propose if amount exceeds ${AMOUNT_THRESHOLD}
- send_duplicate_warning: Propose this (instead of log_invoice) if it IS a duplicate

Format your proposed_actions block exactly like this:
<proposed_actions>
[
  {{
    "id": "log_invoice",
    "description": "Log invoice INV-XXXX to Google Sheets",
    "tool": "log_invoice",
    "args": {{"vendor_name": "...", "invoice_number": "...", "invoice_date": "...", "due_date": "...", "total_amount": 0.0, "currency": "..."}}
  }},
  {{
    "id": "send_urgent_reminder",
    "description": "Send URGENT payment reminder to finance team (due in X days)",
    "tool": "send_email",
    "args": {{"to": "{FINANCE_EMAIL}", "subject": "URGENT: Invoice from ... due in X days", "body": "..."}}
  }}
]
</proposed_actions>

Be thorough in your reasoning — the human reading your analysis needs to understand WHY you're proposing each action.
Keep email bodies professional and concise (3-5 sentences max).
"""


def analyze_invoice(email_data: dict, services: dict, config: dict) -> dict:
    """
    Phase 1: Run the agentic loop with read-only tools.
    Returns the agent's analysis text and a list of proposed_actions.
    """
    today = date.today().isoformat()
    system_content = SYSTEM_PROMPT.format(
        URGENT_DAYS=config["URGENT_DAYS"],
        AMOUNT_THRESHOLD=config["AMOUNT_THRESHOLD"],
        TODAY=today,
        FINANCE_EMAIL=config["FINANCE_EMAIL"],
    )

    messages = [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": (
                f"Please analyze this invoice email.\n\n"
                f"From: {email_data['sender']}\n"
                f"Subject: {email_data['subject']}\n\n"
                f"This email has a PDF attachment. Call read_invoice_pdf() to extract its contents, "
                f"then call check_duplicate() with the invoice number you find."
            ),
        },
    ]

    print(f"\n{'='*60}")
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC] Starting agent analysis")

    # Agentic loop — Phase 1 only (read-only tools)
    while True:
        response = ollama.chat(
            model=config.get("OLLAMA_MODEL", "llama3.1"),
            messages=messages,
            tools=READ_ONLY_TOOL_SCHEMAS,
        )

        msg = response["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            # No more tool calls — agent has finished its analysis
            analysis_text = msg.get("content", "")
            print(f"\n[Agent analysis complete]\n{analysis_text}")
            proposed_actions = _parse_proposed_actions(analysis_text)
            return {
                "analysis_text": analysis_text,
                "proposed_actions": proposed_actions,
            }

        # Execute read-only tool calls
        for tool_call in tool_calls:
            name = tool_call["function"]["name"]
            args = tool_call["function"]["arguments"]

            print(f"\n[Tool call]: {name}({json.dumps(args, indent=None)})")

            if name == "read_invoice_pdf":
                result = read_invoice_pdf(base64_data=email_data["attachment_base64"])
            elif name == "check_duplicate":
                result = check_duplicate(
                    invoice_number=args["invoice_number"],
                    sheets_service=services["sheets"],
                    spreadsheet_id=config["SPREADSHEET_ID"],
                )
            else:
                result = {"error": f"Unknown tool: {name}"}

            print(f"[Tool result]: {json.dumps(result)}")

            messages.append({
                "role": "tool",
                "content": json.dumps(result),
                "name": name,
            })


def _parse_proposed_actions(text: str) -> list:
    """Extract the <proposed_actions> JSON array from the agent's response text."""
    match = re.search(r"<proposed_actions>\s*(\[.*?\])\s*</proposed_actions>", text, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        print("[Warning] Could not parse proposed_actions JSON")
        return []
