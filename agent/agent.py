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
2. Call check_duplicate using the EXACT invoice number found in the PDF (e.g. "INV-2026-0201")
3. Reason about the invoice using these exact checks:

   DUPLICATE CHECK: If check_duplicate returns is_duplicate=true, propose send_duplicate_warning instead of log_invoice.

   URGENCY CHECK: Count the number of calendar days from today ({TODAY}) to the due date.
   - If days_remaining <= {URGENT_DAYS}: the invoice IS urgent → propose send_urgent_reminder
   - If days_remaining > {URGENT_DAYS}: NOT urgent → do NOT propose send_urgent_reminder
   - Example: today={TODAY}, due=2026-05-23 → 3 days → URGENT
   - Example: today={TODAY}, due=2026-05-26 → 6 days → URGENT
   - Example: today={TODAY}, due=2026-06-15 → 26 days → NOT urgent
   - Example: today={TODAY}, due=2026-06-30 → 41 days → NOT urgent

   AMOUNT CHECK: Compare the invoice total to the threshold.
   - If total_amount > {AMOUNT_THRESHOLD}: HIGH VALUE → propose send_approval_request
   - If total_amount <= {AMOUNT_THRESHOLD}: do NOT propose send_approval_request
   - Example: $12,500 > $5,000 → propose send_approval_request
   - Example: $7,800 > $5,000 → propose send_approval_request
   - Example: $3,200 <= $5,000 → do NOT propose send_approval_request
   - Example: $1,200 <= $5,000 → do NOT propose send_approval_request

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

    retry_count = 0
    tools_called = set()
    pdf_invoice_number = None

    # Agentic loop — Phase 1 only (read-only tools)
    while True:
        response = ollama.chat(
            model=config.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
            messages=messages,
            tools=READ_ONLY_TOOL_SCHEMAS,
        )

        msg = response["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            analysis_text = msg.get("content", "")

            # Detect model describing a tool call in text instead of making it
            has_proposed_actions = "<proposed_actions>" in analysis_text
            if (
                not has_proposed_actions
                and retry_count < 4
                and ("read_invoice_pdf" in analysis_text or "check_duplicate" in analysis_text)
            ):
                retry_count += 1
                missing = "check_duplicate()" if "read_invoice_pdf" in tools_called else "read_invoice_pdf()"
                print(f"\n[Retrying — model described tool call in text instead of making it]")
                messages.append({
                    "role": "user",
                    "content": f"Do not write text. Make an actual tool call right now: {missing}. No explanation — only a tool call.",
                })
                continue

            print(f"\n[Agent analysis complete]\n{analysis_text}")
            proposed_actions = _parse_proposed_actions(analysis_text)

            # Guard: discard proposed actions if required tools were never actually called.
            # Prevents hallucinated invoice data from reaching Slack and being executed.
            if proposed_actions and not ("read_invoice_pdf" in tools_called and "check_duplicate" in tools_called):
                print("[Warning] Discarding proposed actions — required tool calls not made (hallucination guard)")
                proposed_actions = []

            # Guard: discard if proposed invoice number doesn't match what the PDF actually contained.
            if proposed_actions and pdf_invoice_number:
                proposed_number = next(
                    (a.get("args", {}).get("invoice_number") for a in proposed_actions
                     if a.get("args", {}).get("invoice_number")),
                    None,
                )
                if proposed_number and proposed_number != pdf_invoice_number:
                    print(f"[Warning] Discarding proposed actions — invoice number mismatch: PDF={pdf_invoice_number}, proposed={proposed_number}")
                    proposed_actions = []

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
                if "read_invoice_pdf" in tools_called:
                    result = {"error": "PDF already read — use the invoice data from the previous call."}
                else:
                    result = read_invoice_pdf(base64_data=email_data["attachment_base64"])
            elif name == "check_duplicate":
                result = check_duplicate(
                    invoice_number=args["invoice_number"],
                    sheets_service=services["sheets"],
                    spreadsheet_id=config["SPREADSHEET_ID"],
                )
            else:
                result = {"error": f"Unknown tool: {name}"}

            tools_called.add(name)
            retry_count = 0
            print(f"[Tool result]: {json.dumps(result)}")

            messages.append({
                "role": "tool",
                "content": json.dumps(result),
                "name": name,
            })

            if name == "read_invoice_pdf" and "error" not in result:
                m = re.search(r"\bINV-\d{4}-\d{4}\b", result.get("text", ""))
                if m:
                    pdf_invoice_number = m.group(0)
                    messages.append({
                        "role": "user",
                        "content": f"PDF read. The invoice number is {pdf_invoice_number}. Now call check_duplicate with invoice_number='{pdf_invoice_number}'.",
                    })
            elif name == "read_invoice_pdf" and "error" in result and pdf_invoice_number:
                messages.append({
                    "role": "user",
                    "content": f"You already read the PDF. The invoice number is {pdf_invoice_number}. Make an actual tool call: check_duplicate(invoice_number='{pdf_invoice_number}'). Do not describe it — call it now.",
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
