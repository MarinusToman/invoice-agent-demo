# Demo Recording Script
## AI Invoice Agent — Live Walkthrough (~4 minutes)

---

## Before You Hit Record

**Setup checklist:**
- [ ] `docker compose up -d` running — both containers healthy (check Docker Desktop)
- [ ] Agent connected to Slack — bot shows as online in your channel
- [ ] Slack open on screen — channel visible, no unread messages
- [ ] Google Sheet open — empty, only the header row showing
- [ ] Gmail open — test inbox with 2-3 emails visible (real or staged)
- [ ] `sample_invoice.pdf` already on your device (printed from `sample_invoice.html`)
- [ ] Phone or second device ready to send the test email mid-demo
- [ ] Terminal window open and ready to run: `python agent/main.py --once`

**Screen layout:**
Use a split-screen or have tabs ready to switch between: Terminal | Slack | Google Sheet

**Test run first:**
Do a full dry run off-camera before recording to confirm everything works.

---

## Scene 1 — The Problem (30 seconds)

*Show your Gmail inbox. Optionally have 3-4 visible emails with subject lines like "Invoice #...", "Bill from...", etc.*

**Say:**
> "Every business receives invoices — from suppliers, contractors, software vendors. Most businesses still process them manually: someone opens each one, types the data into a spreadsheet, checks if it's already been paid, figures out if it's urgent, then chases the right person to approve it.
>
> That's 5 to 10 minutes per invoice. If you get 50 a month, that's hours of work every month — for something a computer can now do instantly. Today I'm going to show you an AI agent that handles all of this — and I'll show you exactly how it keeps you in control."

---

## Scene 2 — The Architecture (30 seconds)

*Show Docker Desktop with both containers running: `ollama` and `invoice-agent`.*

**Say:**
> "First, I want to show you something important. Everything in this demo runs on this computer — right here. This container" — *point to Ollama* — "is running an AI model locally. Your invoice data never gets sent to OpenAI, Anthropic, or any cloud service. It stays on your machine.
>
> This second container is the agent itself — isolated from the rest of your computer, running as a restricted user. It can only talk to Ollama and to your Google account."

---

## Scene 3 — Show the Agent Code (30 seconds)

*Open `agent/agent.py` in your editor. Scroll to the SYSTEM_PROMPT.*

**Say:**
> "Here's how the agent works. I've given it a set of instructions — called a system prompt. It tells the agent: read the PDF, check for duplicates, reason about urgency and value, then *propose* actions. It can't log anything or send any email by itself — it can only recommend. The human approves."
>
> *Scroll down to show the READ_ONLY_TOOL_SCHEMAS.*
>
> "In Phase 1, the agent only has access to two tools: read a PDF, and check the spreadsheet. Both are read-only. Writing and sending — that's Phase 3, and only if you say so."

---

## Scene 4 — Trigger It Live (20 seconds)

*Switch to Gmail. Have your phone ready.*

**Say:**
> "I'm going to send an invoice to my inbox right now from my phone."

*Send the email with `invoice.pdf` attached. Show it arriving in Gmail.*

> "There it is. Now I'll run the agent."

*Switch to terminal. Run:*
```
python agent/main.py --once
```

---

## Scene 5 — Watch Phase 1 (30 seconds)

*Terminal output appears. Read key lines aloud as they print.*

**Say:**
> "Watch what the agent is doing. It's found the email... now it's calling `read_invoice_pdf`... it's extracted the data from the PDF." *(Pause as tool result appears.)*
>
> "Vendor: Acme Office Supplies. Amount: $8,500. Due in 2 days. Now it's calling `check_duplicate`..." *(Pause.)* "Not a duplicate.
>
> And now it's reasoning — $8,500 is above our $5,000 threshold, and it's due in 2 days, which is within our 7-day urgent window. So it's going to recommend three actions."

---

## Scene 6 — The Approval Message (KEY MOMENT — 45 seconds)

*Switch to Slack. The approval message has appeared.*

**Say:**
> "Look at this. The agent has posted its recommendations to Slack — but it hasn't *done* anything yet. Nothing has been logged, no emails have been sent.
>
> It's asking me: do I want to log this invoice to Google Sheets? Do I want to send an urgent payment reminder to the finance team? Do I want to send an approval request to the manager? I can say yes to all three, or skip any of them."

*Click Approve on all three. Buttons update to show ✅ Approved.*

> "I'm approving all three. Now it's going to execute."

---

## Scene 7 — Show the Results (25 seconds)

*Switch to Google Sheet.*

**Say:**
> "New row — vendor name, invoice number, dates, amount, currency — all extracted automatically." *(Zoom in on the row.)*

*Switch to Gmail Sent folder.*

> "And two emails have been sent: an urgent payment reminder and an approval request to the manager. Automatically, accurately, within 30 seconds of the email arriving."

---

## Scene 8 — MCP Bonus (optional — 30 seconds)

*Open Claude Desktop.*

**Say:**
> "And for anyone who wants to go a step further — I've connected this agent to Claude Desktop using something called MCP, the Model Context Protocol. Now I can ask questions directly."

*Type: "Are there any invoices due this week?"*

> "Claude is calling the agent's tools, reading the spreadsheet, and giving me the answer in plain English — without me having to open the sheet at all."

---

## Scene 9 — Close (30 seconds)

**Say:**
> "That is a real AI agent — not a script that blindly follows rules, but a system that *reasons* about the invoice, *decides* what to do, and *asks your permission* before doing anything.
>
> Everything here is free to run. No API fees, no subscriptions. The AI runs on your own computer. The full tutorial — showing exactly how to build this yourself, step by step — is in the description.
>
> It took about two hours to set up. It will save that time back every single month."

---

## Filming Tips

- **Zoom in** on the Slack approval buttons — that's the most important moment
- **Read the terminal output aloud** — the reasoning is what makes it agentic
- **Pause** after each tool call result so viewers can read it
- **Don't rush Scene 6** — the human approval is the key differentiator from simple automation
- If the agent takes longer than expected: "The AI is running locally on this machine — no cloud API call, no network latency, just a 4.7GB model working on your CPU."
