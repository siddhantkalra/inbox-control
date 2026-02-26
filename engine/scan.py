from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from email.utils import parseaddr

from rich.console import Console
from rich.table import Table

from gmail_client import get_gmail_service

console = Console()

@dataclass
class SenderAgg:
    sender: str
    domain: str
    count: int = 0
    last_ts: int = 0
    has_list_unsub: int = 0

    @property
    def last_seen_iso(self) -> str:
        if not self.last_ts:
            return ""
        dt = datetime.fromtimestamp(self.last_ts / 1000, tz=timezone.utc)
        return dt.isoformat()

    @property
    def list_unsub_rate(self) -> float:
        return (self.has_list_unsub / self.count) if self.count else 0.0


def _get_header(headers: list[dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _sender_domain(from_value: str) -> tuple[str, str]:
    _, addr = parseaddr(from_value)
    addr = addr.lower().strip()
    domain = addr.split("@")[-1] if "@" in addr else ""
    return addr, domain


def run_scan(query: str, limit: int = 500, out_path: str = "") -> None:
    svc = get_gmail_service()

    resp = svc.users().messages().list(userId="me", q=query, maxResults=min(limit, 500)).execute()
    msgs = resp.get("messages", []) or []
    if not msgs:
        console.print("[yellow]No messages found for query.[/yellow]")
        return

    aggs: dict[str, SenderAgg] = {}
    for m in msgs:
        msg = svc.users().messages().get(
            userId="me",
            id=m["id"],
            format="metadata",
            metadataHeaders=["From", "List-Unsubscribe"],
        ).execute()

        payload = msg.get("payload", {}) or {}
        headers = payload.get("headers", []) or []
        from_h = _get_header(headers, "From")
        addr, dom = _sender_domain(from_h)

        if not addr:
            continue

        key = dom or addr
        if key not in aggs:
            aggs[key] = SenderAgg(sender=addr, domain=dom)

        aggs[key].count += 1
        internal_date = int(msg.get("internalDate", "0"))
        aggs[key].last_ts = max(aggs[key].last_ts, internal_date)

        list_unsub = _get_header(headers, "List-Unsubscribe")
        if list_unsub:
            aggs[key].has_list_unsub += 1

    ranked = sorted(aggs.values(), key=lambda x: (x.count, x.last_ts), reverse=True)

    table = Table(title=f"Scan results (sampled {len(msgs)} msgs) — query: {query}")
    table.add_column("Rank", justify="right")
    table.add_column("Domain")
    table.add_column("Sender (example)")
    table.add_column("Count", justify="right")
    table.add_column("List-Unsub %", justify="right")
    table.add_column("Last Seen (UTC)")

    for i, s in enumerate(ranked[:30], start=1):
        table.add_row(
            str(i),
            s.domain or "-",
            s.sender,
            str(s.count),
            f"{s.list_unsub_rate*100:.0f}%",
            s.last_seen_iso,
        )

    console.print(table)

    if out_path:
        out = [asdict(x) | {"last_seen_iso": x.last_seen_iso, "list_unsub_rate": x.list_unsub_rate} for x in ranked]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        console.print(f"[green]Wrote JSON:[/green] {out_path}")
