# Demo Video Script

## Before you hit record
- `docker compose up -d` running, bot shows online in Slack
- Google Sheet open (with previous test data visible — shows it actually works)
- Gmail open (send 1-2 fresh test invoices, mark them unread)
- Slack channel open

---

## On camera

**1. The problem** (20s)
"Businesses receive invoices. Someone manually enters data, checks for duplicates, chases approvals. I built an AI agent to do this — but safely."

**2. The architecture** (30s)
Show Docker Desktop: two containers. "AI runs entirely on this machine — invoices never leave. The agent is sandboxed, can't touch your files."

**3. Trigger** (10s)
Type `process invoices` in Slack. "I can also schedule this weekly — but let's trigger it now."

**4. Watch the analysis** (30s)
Show the terminal logs briefly. Agent reads the PDF, checks for duplicates, reasons about urgency and amount.

**5. The approval message** (45s — key moment)
"The agent hasn't done anything yet. It's asking permission." Read the proposed actions aloud. Point out the email recipient on the urgent reminder — "notice it got this wrong — it used the vendor's email instead of our finance team. That's exactly why we have this approval step." Click Skip on it. Approve the rest.

**6. Results** (20s)
Check the Google Sheet (new row). Check Gmail sent (one email, not two). "It only did what I approved."

**7. Close** (20s)
"Local AI, sandboxed container, nothing executes without a human click. The tutorial is in the description."
