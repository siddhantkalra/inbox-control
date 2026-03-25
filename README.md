# Inbox Control

A local-first Gmail inbox management engine. Scans your inbox, detects bulk and marketing senders, scores them by signal strength, and lets you suppress them with a single command — with full undo support.

---

## What It Does

- **Scan** — samples your inbox against any Gmail query and builds per-sender and per-domain profiles
- **Detect** — scores senders using signals like List-Unsubscribe headers, no-reply addresses, campaign mailer patterns (SendGrid, Mailchimp, Klaviyo, etc.), and reply history
- **Suppress** — creates a Gmail label and filter for a target domain or sender; optionally archives or trashes existing messages (dry-run by default)
- **Undo** — reverses the last suppression run for any target, restoring messages to inbox if needed
- **List** — shows all active suppression rules

All operations are dry-run by default. Changes only apply when you pass `--apply`.

---

## Stack

- **Language**: Python
- **Gmail access**: Google Gmail API (OAuth 2.0, read + modify scopes)
- **CLI**: `argparse`
- **Output**: `rich` tables in terminal

---

## Setup

```bash
# 1. Clone and install
git clone https://github.com/siddhantkalra/inbox-control.git
cd inbox-control
pip install -r engine/requirements.txt

# 2. Add Gmail OAuth credentials
# Go to console.cloud.google.com → create OAuth 2.0 client → download as credentials.json
cp credentials.json engine/credentials.json

# 3. Authenticate (opens browser once)
cd engine
python main.py scan --query "category:promotions" --limit 100
```

---

## Usage

```bash
cd engine

# Scan promotions and see top senders
python main.py scan --query "category:promotions older_than:6m" --limit 500

# Detect bulk senders (domain-level)
python main.py detect --query "category:promotions older_than:6m" --kind domain

# Suppress a domain (dry-run)
python main.py suppress --target example.com

# Suppress and apply (moves existing mail to archive)
python main.py suppress --target example.com --apply

# Undo last suppression for a target
python main.py undo --target example.com --restore-inbox

# List all active suppression rules
python main.py list-suppressed
```

---

## Project Structure

```
inbox-control/
├── engine/
│   ├── main.py           # CLI entry point
│   ├── scan.py           # Inbox scanner
│   ├── detect.py         # Bulk sender detection + scoring
│   ├── suppress.py       # Suppression rule engine
│   ├── undo.py           # Undo last suppression
│   ├── gmail_client.py   # Gmail API client (OAuth)
│   ├── state.py          # Suppression state persistence
│   └── config.py         # Settings
├── dashboard/            # Optional web dashboard
├── docs/
└── setup.sh
```
