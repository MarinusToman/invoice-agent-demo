import base64
import io
import os
from datetime import datetime, timezone
from email.mime.text import MIMEText

from pypdf import PdfReader


# ─────────────────────────────────────────────
# READ-ONLY TOOLS (Phase 1 — no approval needed)
# ─────────────────────────────────────────────

def read_invoice_pdf(base64_data: str) -> dict:
    """Extract plain text from a base64-encoded PDF invoice."""
    pdf_bytes = base64.urlsafe_b64decode(base64_data + "==")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return {"text": text.strip()}


def check_duplicate(invoice_number: str, sheets_service, spreadsheet_id: str) -> dict:
    """Check if an invoice number already exists in the Invoices spreadsheet."""
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range="Invoices!B:B",   # Invoice # column
        ).execute()
        values = result.get("values", [])
        existing = {row[0].strip() for row in values if row}
        is_duplicate = invoice_number.strip() in existing
        return {"is_duplicate": is_duplicate}
    except Exception as e:
        return {"is_duplicate": False, "error": str(e)}


# ─────────────────────────────────────────────
# WRITE TOOLS (Phase 3 — only run after approval)
# ─────────────────────────────────────────────

def log_invoice(
    vendor_name: str,
    invoice_number: str,
    invoice_date: str,
    due_date: str,
    total_amount: float,
    currency: str,
    sheets_service,
    spreadsheet_id: str,
) -> dict:
    """Append a new invoice row to the Google Sheet."""
    row = [
        vendor_name,
        invoice_number,
        invoice_date,
        due_date,
        str(total_amount),
        currency,
        datetime.now(timezone.utc).isoformat(),
    ]
    sheets_service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range="Invoices!A:G",
        valueInputOption="RAW",
        body={"values": [row]},
    ).execute()
    return {"logged": True}


def send_email(to: str, subject: str, body: str, gmail_service) -> dict:
    """Send an email via the Gmail API."""
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    gmail_service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return {"sent": True, "to": to}


# ─────────────────────────────────────────────
# TOOL SCHEMAS (for Ollama tool-calling)
# Only read-only tools are passed to the agent in Phase 1
# ─────────────────────────────────────────────

READ_ONLY_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_invoice_pdf",
            "description": "Extract and return all text from the PDF invoice attached to this email. Always call this first.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_duplicate",
            "description": "Check whether an invoice number has already been logged in the spreadsheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_number": {
                        "type": "string",
                        "description": "The invoice number to look up.",
                    }
                },
                "required": ["invoice_number"],
            },
        },
    },
]
