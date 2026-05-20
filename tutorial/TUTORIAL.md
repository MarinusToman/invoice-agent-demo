# Tutorial: Build Your Own AI Invoice Agent

> **This is the exact setup shown in the demo video.**
> Follow these steps and you will have the same working workflow running on your own machine.

---

## What You're Building

An AI agent that:

1. Checks your Gmail inbox once a week (or on-demand) for emails with invoice attachments
2. Reads each PDF invoice using a local AI model running on your own computer
3. Reasons about it — is it a duplicate? is it urgent? is it a large amount?
4. Sends you an approval message in Slack with its recommendations
5. Only executes actions (logging to Google Sheets, sending reminders) after you click Approve

```
Gmail  →  AI Agent (local)  →  Slack approval  →  Google Sheets
                ↑
          Ollama (on your machine)
          Your invoices never leave your computer
```

**The AI does the thinking — you stay in control.**

---

## Why This Is Safe

| Concern                                   | How it's addressed                                   |
| ----------------------------------------- | ---------------------------------------------------- |
| My invoice data going to a cloud AI       | ❌ Never happens — AI runs locally via Ollama        |
| Agent accessing my computer's files       | ❌ Agent runs in an isolated Docker container        |
| Agent sending emails without my knowledge | ❌ Every action requires your Slack approval         |
| Costs from AI API usage                   | ❌ No AI API — Ollama is free and local              |
| Google API costs                          | ✅ Both Gmail and Sheets APIs are free at this scale |
| My credentials being exposed              | ✅ Stored in a git-ignored file, never in code       |

---

## What You Need

- **Docker Desktop** (free) — [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
- **A dedicated Gmail account** — strongly recommended: create a new Gmail account just for testing so you don't risk your real inbox
- **Google account** with access to Google Sheets (same Google account as above is fine)
- **Slack workspace** — free tier is sufficient; use an existing workspace or create one at [slack.com](https://slack.com)
- **Python 3.10+** — only needed for the optional MCP section and the one-time Google auth setup
- **16GB RAM recommended** (8GB minimum) — the qwen3:8b model needs about 5-6GB

**Cost: $0.** All services used here are free at normal business volumes.

---

## Section 1 — Create Your Slack Bot (15 minutes)

> ⚠️ **Important — read before starting:**
> Do NOT do any of this inside the Slack app you use for chatting.
> You need to open a **web browser** (Chrome, Edge, or Firefox) and visit a completely separate developer website.

The agent communicates with you through Slack. You need to create a Slack bot on Slack's developer portal.

**Step 1 — Open the Slack developer portal:**

- Open your web browser (not the Slack app)
- Click in the address bar at the very top of the browser window
- Type exactly: **api.slack.com/apps** and press Enter
- If you see a sign-in page, sign in with the same account you use for your Slack workspace

You should now see a page that says **"Your Apps"** with a dark purple/teal header bar at the top that reads "Slack API". If you see the regular Slack chat interface, you're in the wrong place — make sure you're in a browser tab, not the Slack desktop app.

**Step 2 — Create the app:**

- Click the green **"Create New App"** button (top-right area of the page)
- A small popup window appears with two options. Click **"From scratch"**
- A form appears with two fields:
  - **App Name**: type **Invoice Agent**
  - **Pick a workspace to develop your app in**: click the dropdown and select your workspace
- Click **"Create App"**

You'll be taken to the app's settings page. You'll see a left-side menu with many options — you'll use this to configure the bot step by step.

**Step 3 — Enable Socket Mode** (this is how the bot receives messages securely, without needing a public web address):

- In the left sidebar, under the **"Settings"** section, click **"Socket Mode"**
- You'll see a toggle labelled **"Enable Socket Mode"**. Click it to turn it ON (it turns green)
- A popup appears saying you need an app-level token.
  - In the **"Token Name"** field, type: **socket-token**
  - If there is no scope already polpulated, click the **"Add Scope"** button — a dropdown appears. Select **`connections:write`**
  - Click **"Generate"**
- A token appears on screen starting with `xapp-1-...`. **Copy the entire token and paste it into a Notepad document** — open Notepad (Windows key → type "Notepad"), paste, and save the file. You will NOT be able to see this token again.
- Click **"Done"**
- Click **"Save Changes"** at the bottom of the page

**Step 4 — Enable Event Subscriptions** (this allows the bot to receive messages you type in the channel):
- In the left sidebar, under **"Features"**, click **"Event Subscriptions"**
- Click the toggle labelled **"Enable Events"** to turn it ON (turns green)
- Scroll down to the section called **"Subscribe to Bot Events"**
- Click **"Add Bot User Event"** and add both of these:
  - **`message.channels`** — receives messages in public channels
  - **`message.groups`** — receives messages in private channels
- Click **"Save Changes"** at the bottom of the page
  > If Slack shows a yellow banner saying the app needs to be reinstalled, you'll do that in Step 6 — it's normal.

**Step 5 — Add bot permissions:**

- In the left sidebar, under **"Features"**, click **"OAuth & Permissions"**
- Scroll down the page until you see a section called **"Scopes"**, and inside it, **"Bot Token Scopes"**
- Click **"Add an OAuth Scope"** and add each of these five permissions, one at a time:
  - `chat:write` — allows the bot to post messages
  - `channels:history` — allows the bot to read channel messages
  - `channels:read` — allows the bot to see your channels
  - `reactions:write` — allows the bot to add emoji reactions
  - `im:write` — allows the bot to send direct messages
- After adding all five, you should see them listed under Bot Token Scopes

**Step 6 — Install the bot to your workspace:**

- Scroll back up to the top of the **"OAuth & Permissions"** page
- Click the **"Install to Workspace"** button
- A page appears showing you what permissions you're granting. Click **"Allow"**
- You'll be returned to the OAuth & Permissions page. At the top you'll now see a **"Bot User OAuth Token"** starting with `xoxb-`. **Copy this and paste it into your Notepad document** alongside your other token.

**Step 7 — Add the bot to your Slack channel:**

- Open the Slack app (or your Slack browser tab)
- In the left sidebar, go to the channel where you want the bot to post. If you don't have one yet, create a new channel: click the **+** next to "Channels" in the left sidebar, name it `invoice-agent`, and click "Create"
- In the message box at the bottom of the channel, type:
  `/invite @Invoice Agent`
  and press Enter. The bot will join the channel.

**Step 8 — Find your Channel ID:**

- In the Slack app, right-click the channel name in the left sidebar
- Click **"View channel details"**
- A panel opens on the right. Scroll down to the very bottom — you'll see **"Channel ID"** followed by a code starting with `C` (e.g. `C01234ABCDE`). **Copy this and add it to your Notepad document.**

You now have three values saved in Notepad:

- **SLACK_BOT_TOKEN** = `xoxb-...`
- **SLACK_APP_TOKEN** = `xapp-1-...`
- **SLACK_CHANNEL_ID** = `C...`

---

## Section 2 — Set Up Google Credentials (15 minutes)

> ⚠️ **Important — read before starting:**
> The next steps happen on a website called the **Google Cloud Console**. This is NOT your regular Gmail, Google Drive, or Google Docs. It's a completely separate developer website that looks very different. You'll open it in your browser.

You need to authorize the agent to read your Gmail and write to one Google Sheet.

**Step 1 — Open Google Cloud Console:**

- Open your web browser
- In the address bar, type: **console.cloud.google.com** and press Enter
- Sign in with your **test Gmail account** when prompted
- When the page loads, you'll see a top bar with "Google Cloud" on it. This is the right place.

**Step 2 — Create a project:**

- Near the top of the page, click on the project dropdown. It might say **"Select a project"** or show a project name if you've used this before.
- In the popup that appears, click **"New Project"** in the top-right corner
- In the **"Project name"** field, type: **Invoice Agent**
- Click **"Create"**
- Wait about 15 seconds. A notification bell at the top will show when it's ready. Click **"Select Project"** in the notification, or click the project dropdown again and click **Invoice Agent** to make it your active project.
- Confirm the project name appears in the dropdown at the top before continuing.

**Step 3 — Enable the Gmail API:**

- At the very top of the page, there is a search bar. Click it and type: **Gmail API**
- In the dropdown results, click **"Gmail API"** (it shows the Gmail envelope icon)
- On the next page, click the blue **"Enable"** button
- Wait for the page to update — you'll see "Gmail API" with an "API enabled" message

**Step 4 — Enable the Google Sheets API:**

- Click the search bar at the top again. Type: **Google Sheets API**
- Click **"Google Sheets API"** in the results
- Click the blue **"Enable"** button and wait for the page to update

**Step 5 — Set up the OAuth Consent Screen** (required before you can create credentials):

- In the left sidebar, click **"APIs & Services"** then **"OAuth consent screen"**
- Click **"Get started"** at the bottom of the screen
- A form appears. Fill in these fields:
  - **App name**: Invoice Agent
  - **User support email**: click the dropdown and select your test Gmail address
  - **Audience**: External
  - **Developer contact information**: type your test Gmail address
- Agree to the user data policy and click **"Continue"**
- Click **"Create"**

**Step 6 — Add yourself as a test user:**

> This step is required. The app is in "Testing" mode, so only accounts you explicitly add here can sign in.

- In the **left sidebar**, click **"Audience"**
- Scroll down the page until you see a section called **"Test users"**
- Click **"+ Add Users"**
- Type your test Gmail address in the box and click **"Add"**
- Click **"Save"**

**Step 7 — Create OAuth credentials:**

- On the right, click **"Create OAuth Client"**
- Under **"Application type"**, click the dropdown and select **"Desktop app"**
- Under **"Name"**, type: **Invoice Agent**
- Click **"Create"**
- A popup appears saying "OAuth client created". Click the **"Download JSON"** button
- Your browser will download a file with a long name ending in `.json`. Note where it was saved — usually your **Downloads** folder.
- Click **"OK"** to close the popup

**Step 8 — Move the file to the project:**

- Press **Windows key + E** to open File Explorer
- Navigate to your **Downloads** folder (click "Downloads" in the left sidebar)
- Find the file that starts with `client_secret_` and ends with `.json`
- Right-click it → **Rename** → delete the existing name and type exactly: **client_secret.json** → press Enter
- Windows may show a warning about changing the file extension. Click **"Yes"**
- Now navigate to your project folder → open the **`credentials`** folder inside it
- Go back to Downloads, right-click `client_secret.json` → **Copy**
- Go back to the `credentials` folder, right-click in the empty space → **Paste**

> **Note:** Both APIs are completely free. Google provides far more free quota than 50 invoices per month will ever use.

---

## Section 3 — Create Your Google Sheet (2 minutes)

**Step 1.** Go to [sheets.google.com](https://sheets.google.com) and create a new spreadsheet.

**Step 2.** Name the spreadsheet "Invoice Tracker" (or anything you like).

**Step 3.** Name the first tab/sheet exactly **"Invoices"** (case-sensitive).

**Step 4.** Add these headers in row 1:

| A           | B         | C            | D        | E      | F        | G            |
| ----------- | --------- | ------------ | -------- | ------ | -------- | ------------ |
| Vendor Name | Invoice # | Invoice Date | Due Date | Amount | Currency | Processed At |

**Step 5.** Copy the spreadsheet ID from the URL bar. The URL looks like:
`https://docs.google.com/spreadsheets/d/`**`1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms`**`/edit`

The bold part is your Spreadsheet ID.

---

## Section 4 — Download and Configure the Project (5 minutes)

**Step 1 — Download the project:**

- Open your web browser and go to this project's GitHub page
- Click the green **"Code"** button near the top-right
- Click **"Download ZIP"**
- When the download finishes, open **File Explorer** (Windows key + E) and go to your Downloads folder
- Right-click the file named `invoice-agent-demo-main.zip` (or similar) → **"Extract All..."**
- In the window that appears, click **"Browse"** and choose somewhere easy to find, like your Desktop. Then click **"Extract"**
- A folder called `invoice-agent-demo-main` will appear on your Desktop — this is your project folder. You can rename it to `invoice-agent-demo` if you like (right-click → Rename)

**Step 2 — Create your config file:**

- Open the project folder in File Explorer
- You need to find a file called `.env.example`

  > If you can't see it: click the **"View"** tab at the top of File Explorer → check the box labelled **"Hidden items"**. Files starting with a dot (`.`) are hidden by default on Windows.

- Right-click `.env.example` → **"Copy"**
- Right-click on an empty space in the same folder → **"Paste"**
- A copy appears, named `.env.example - Copy` (or similar)
- Right-click the copy → **"Rename"** → type exactly `.env` → press Enter
- If Windows asks "Are you sure you want to change the file extension?" → click **"Yes"**

**Step 3 — Fill in your settings:**

- Right-click the `.env` file → **"Open with"** → **"Notepad"**
  - If Notepad isn't in the list, click **"Choose another app"** → scroll down and click **"Notepad"**
- The file will open showing several lines. Find each of the lines below and replace the placeholder text after the `=` sign with your real values (no spaces around the `=`):

  ```
  SPREADSHEET_ID=     ← paste your Google Sheet ID from Section 3
  SLACK_BOT_TOKEN=    ← paste your xoxb-... token from Section 1
  SLACK_APP_TOKEN=    ← paste your xapp-... token from Section 1
  SLACK_CHANNEL_ID=   ← paste your C... channel ID from Section 1
  MANAGER_EMAIL=      ← the email address that should receive approval requests
  FINANCE_EMAIL=      ← the email address that should receive payment reminders
  ```

- Leave all other lines exactly as they are
- Click **File** → **"Save"** → close Notepad

---

## Section 5 — Start the Stack (10 minutes)

**How to open a Command Prompt (you'll need this for Sections 5 and 6):**

> A "Command Prompt" (also called a "terminal") is a black window where you type commands. It sounds intimidating but you're just going to type a few short lines.
>
> 1. Press the **Windows key** on your keyboard
> 2. Type: **cmd**
> 3. Click **"Command Prompt"** in the results — a black window opens
>
> Before running any commands, you need to navigate to your project folder. Type the command below and press Enter, replacing `YourName` with your Windows username and adjusting the path to wherever you extracted the project:
>
> ```
> cd C:\Users\YourName\Desktop\invoice-agent-demo
> ```
>
> If the folder path contains spaces, wrap it in quotes:
>
> ```
> cd "C:\Users\Your Name\Desktop\invoice-agent-demo"
> ```
>
> You'll know it worked when the black window shows the project folder path before the cursor.

**Step 1 — Make sure Docker Desktop is running.**
Open Docker Desktop from the Start menu. Wait until the whale icon in the taskbar shows a green light (this means Docker is ready). If it shows an error, try restarting Docker Desktop.

**Step 2 — Start the stack:**
In your Command Prompt, type this command and press Enter:

```
docker compose up -d
```

This starts three things automatically:
1. **Ollama** — the local AI engine
2. **Model download** — downloads the `qwen3:8b` AI model (~4.7 GB, one-time only)
3. **Invoice Agent** — starts after the model is ready

The first time you run this, the model download takes **5–15 minutes** depending on your internet speed. You can watch the progress by running:

```
docker compose logs -f model-init
```

Press **Ctrl+C** to stop watching the logs (the download continues in the background). The model is saved in a Docker volume and reused every time after — subsequent startups take only a few seconds.

> **Lower RAM option:** If your computer has less than 8 GB of RAM, use the smaller `llama3.2` model (~2 GB) instead. Open your `.env` file in Notepad and add: `OLLAMA_MODEL=llama3.2`. Then open `docker-compose.yml` in Notepad and change `qwen3:8b` to `llama3.2` in the `model-init` section. Run `docker compose up -d --build` to apply.
> Note: the smaller model may occasionally miss tool calls — if the agent seems unresponsive, switch back to `qwen3:8b`.

---

## Section 6 — Authorize Google Access (One-Time Setup)

**Step 1 — Install the required libraries:**
In your Command Prompt (make sure you're still in the project folder), type:

```
pip install -r agent/requirements.txt
```

This installs the Python libraries the agent needs. You'll see a lot of text scroll by — wait until it finishes and returns to the command prompt.

> If you see `'pip' is not recognized as a command`, you need to install Python first. Go to **python.org/downloads**, download the latest version, run the installer, and check the box that says **"Add Python to PATH"** during installation. Then re-open Command Prompt and try again.

**Step 2 — Run the Google authorization:**

```
python agent/auth.py
```

Your browser will automatically open a Google sign-in page. Sign in with your **test Gmail account**.

**Step 3 — Handle the Google warning:**
After signing in, Google may show a screen that says **"Google hasn't verified this app"** or **"This app isn't verified"**. This is expected — it appears because you just created this app yourself and it hasn't gone through Google's review process (which is for public apps, not private tools like this).

To continue:

- Click **"Continue"**
- A screen shows the permissions the agent is requesting. Select all and click **"Continue"**

A message will appear in your browser saying the authorization was successful. You can close that browser tab.

The authorization token is saved to `credentials/token.json` inside your project folder. **This file stays on your computer and is never uploaded anywhere.**

---

## Section 7 — Test It Live (This Is the Demo)

**Prepare the test invoice:**

1. Open `sample_invoice/sample_invoice.html` in your browser
2. File → Print (or Ctrl/Cmd+P) → Save as PDF
3. Name the file `invoice.pdf`

**Send the test invoice:**

- Send an email to your test Gmail account with `invoice.pdf` as an attachment
- Subject can be anything (e.g. "Invoice from Acme")

**Trigger the agent:**

You have two ways to trigger the agent:

**Option A — Slack shortcut (easiest):**
Click the **`/` icon** (a box with a forward slash) in the Slack message compose box → find **"Process Invoices"** in the list → click it.

> If you don't see "Process Invoices" listed, you need to add the shortcut to your app first. In your browser, go to **api.slack.com/apps** → click **Invoice Agent** → left sidebar → **Interactivity & Shortcuts** → scroll to **Shortcuts** → **Create New Shortcut** → **Global** → set the name to `Process Invoices`, the callback ID to exactly `process_invoices`, and a description → **Save Changes**. Then reinstall the app using the **Install App** page in the left sidebar.

**Option B — Type a message:**
In your Slack channel, type this and press Enter:

```
process invoices
```

The agent is already running inside Docker (started in Section 5) — either option tells it to check Gmail immediately.

**Watch what happens:**

- The bot replies in Slack: "Starting invoice check now..."
- Within ~30 seconds, a message appears in your Slack channel with the invoice summary and action buttons
- The **approval buttons look like this:**

```
📄 New Invoice Requires Your Review
──────────────────────────────────────
Vendor: Acme Office Supplies Ltd.    Invoice #: INV-2024-0042
Amount: USD 8,500.00                  Due Date: 2024-11-22

Agent recommends the following actions. Approve or skip each one:

• Log invoice INV-2024-0042 to Google Sheets        [✅ Approve]  [❌ Skip]
• Send URGENT payment reminder to finance team       [✅ Approve]  [❌ Skip]
• Send approval request to manager                  [✅ Approve]  [❌ Skip]

🔒 Nothing will execute until you approve. The AI runs locally — your data never left this machine.
```

- Click **Approve** on each action you want to take
- The agent executes only your approved actions and posts a confirmation summary
- Check your Google Sheet — a new row should appear
- Check your sent emails — reminders should have been sent

---

## Section 8 — Run on the Weekly Schedule (Production Mode)

The default schedule runs every **Monday at 9:00 AM**. To start in production mode:

```bash
# Rebuild the container with your .env settings, then start
docker compose up -d --build
```

The agent will run every Monday at 9 AM, post to Slack if invoices are found, and wait for your approval.

**To change the schedule**, edit `.env`:

```
POLL_WEEKDAY=2    # Wednesday
POLL_HOUR=8       # 8:00 AM
```

Then `docker compose up -d --build` to apply.

**To stop the agent:**

```bash
docker compose down
```

---

## Section 9 — MCP for Claude Desktop (Bonus — 5 minutes)

This lets you ask questions about your invoices directly in Claude Desktop.

**Step 1.** Install dependencies (if you haven't already):

```bash
pip install -r agent/requirements.txt
```

**Step 2.** Find your Claude Desktop config file:

- **Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

**Step 3.** Open the config file and add the `invoice-agent` entry from `mcp_server/claude_desktop_config.json`. Update the paths to match your actual directory:

```json
{
  "mcpServers": {
    "invoice-agent": {
      "command": "python",
      "args": ["/Users/yourname/invoice-agent-demo/mcp_server/server.py"],
      "env": {
        "PYTHONPATH": "/Users/yourname/invoice-agent-demo/agent"
      }
    }
  }
}
```

**Step 4.** Restart Claude Desktop.

**Step 5.** In a new Claude Desktop conversation, try:

- "Are there any invoices due this week?"
- "Give me an invoice summary"
- "Process new invoices" → Claude will show you proposed actions → you confirm before anything executes

---

## Section 10 — Security Checklist

Before using this in any real business setting, verify all of these:

- [ ] `.env` is in `.gitignore` — confirmed
- [ ] `credentials/token.json` is in `.gitignore` — confirmed
- [ ] You used a dedicated Gmail account (not your main inbox)
- [ ] The Google OAuth scopes are minimal (Gmail read + send, one Sheets file)
- [ ] Ollama is bound to `127.0.0.1` only (confirmed in `docker-compose.yml`)
- [ ] The agent container runs as a non-root user (confirmed in `agent/Dockerfile`)
- [ ] The credentials volume is mounted read-only (confirmed in `docker-compose.yml`)
- [ ] You run `docker compose down` when the agent is not needed
- [ ] If you shared this machine during a demo, delete `credentials/token.json` and re-authorize afterward

---

## Section 11 — Troubleshooting

**"ollama: command not found" inside the container**
The container may not have started yet. Run `docker compose ps` to check. If Ollama isn't running: `docker compose up -d`.

**"The model 'qwen3:8b' is not found"**
The model download may still be in progress or failed. Check with: `docker compose logs model-init`. If it failed, run `docker compose up -d` again — it will retry the download.

**Agent proposes no actions / tool calls don't appear**
qwen3:8b has strong tool-calling support but occasionally a prompt fails. Try triggering again with `process invoices` in Slack. If it consistently fails, switch to a larger model: set `OLLAMA_MODEL=llama3.1:70b` in `.env` and update `docker-compose.yml` to pull that model instead (requires more RAM).

**Slack bot not responding**
Check that the bot is invited to the channel: `/invite @Invoice Agent`. Verify `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env`. Check `docker compose logs invoice-agent` for errors.

**Google OAuth error / "access denied" / Error 403**
Your Google account hasn't been added as a test user. Go to **console.cloud.google.com** → select your **Invoice Agent** project → left sidebar → **"Audience"** → scroll to **"Test users"** → **"+ Add Users"** → add your test Gmail address → Save. Then run `python agent/auth.py` again.

**"Spreadsheet not found"**
Double-check `SPREADSHEET_ID` in `.env`. Verify the sheet tab is named exactly `Invoices` (capital I, no spaces).

**PDF text comes back empty**
Some PDFs are image-only scans — `pypdf` can only extract text from text-based PDFs. For the demo, always use `sample_invoice.html` printed to PDF from a browser (this creates a text-based PDF).

**MCP tools not showing in Claude Desktop**
Restart Claude Desktop after editing the config file. Check that the absolute paths in `claude_desktop_config.json` are correct for your machine. Run `python mcp_server/server.py` manually in a terminal to check for import errors.
