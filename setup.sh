#!/usr/bin/env bash

mkdir -p engine dashboard docs/adr scripts

touch README.md \
CHANGELOG.md \
CONTRIBUTING.md \
.gitignore \
engine/README.md \
engine/.env.example \
dashboard/README.md \
dashboard/.env.example \
docs/PROJECT_LOG.md \
docs/DECISIONS.md \
docs/adr/0001-architecture-split.md \
docs/adr/0002-safety-guardrails.md \
scripts/dev.md

cat > README.md << 'EOF'
# Inbox Control

Local-first Gmail inbox control engine.

Core functions:
- Scan inbox and build sender profiles
- Score and rank bulk/marketing streams
- Allow per-sender approval for suppression and cleanup
- Enforce future suppression rules
EOF

cat > .gitignore << 'EOF'
__pycache__/
*.pyc
.env
venv/
node_modules/
.next/
.DS_Store
*.db
token.json
credentials.json
EOF

cat > docs/PROJECT_LOG.md << 'EOF'
# Project Log

## Day 0 — Project initialization
Repo scaffold created.
EOF

cat > docs/DECISIONS.md << 'EOF'
# Architecture Decisions

Engine: Python
Dashboard: Next.js
Database: SQLite
Architecture: local-first
EOF

git add .
git commit -m "chore: initialize inbox-control project scaffold"