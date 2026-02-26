from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Dict, List, Tuple

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

    # conversational safety signals
    threads: int = 0
    thread_msg_total: int = 0
    threads_with_sent: int = 0  # proxy: you replied
    sent_msg_total: int = 0

    # scoring output
    bulk_score: int = 0
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)

    @property
    def last_seen_iso(self) -> str:
        if not self.last_ts:
            return ""
        dt = datetime.fromtimestamp(self.last_ts / 1000, tz=timezone.utc)
        return dt.isoformat()

    @property
    def list_unsub_rate(self) -> float:
        return (self.has_list_unsub / self.count) if self.count else 0.0

    @property
    def replied_thread_rate(self) -> float:
        return (self.threads_with_sent / self.threads) if self.threads else 0.0

    @property
    def avg_thread_depth(self) -> float:
        return (self.thread_msg_total / self.threads) if self.threads else 0.0


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


def _bulk_score(agg: SenderAgg) -> Tuple[int, float, List[str]]:
    """
    Heuristic scoring (0-100) + confidence + reasons.
    High score => likely bulk/marketing stream.
    Strong negative => conversational => protect.
    """
    score = 0
    reasons: List[str] = []

    # Strong bulk protocol signal
    if agg.list_unsub_rate >= 0.8 and agg.count >= 3:
        score += 40
        reasons.append("List-Unsubscribe present (high rate)")
    elif agg.has_list_unsub > 0:
        score += 20
        reasons.append("List-Unsubscribe present (some)")

    # Volume signal (within current scan scope)
    if agg.count >= 50:
        score += 25
        reasons.append("High volume (>=50 in sample)")
    elif agg.count >= 20:
        score += 15
        reasons.append("Moderate volume (>=20 in sample)")
    elif agg.count >= 10:
        score += 8
        reasons.append("Low/moderate volume (>=10 in sample)")

    # Conversation negative signals (protect humans)
    if agg.threads_with_sent >= 1:
        score -= 60
        reasons.append("You replied in at least one thread (SENT detected)")
    if agg.avg_thread_depth >= 3:
        score -= 25
        reasons.append("Higher thread depth (conversation-like)")

    score = max(0, min(100, score))

    # Confidence: agreement of strong signals
    conf = 0.50
    if agg.list_unsub_rate >= 0.8 and agg.count >= 10:
        conf += 0.25
    if agg.count >= 20:
        conf += 0.10
    if agg.threads_with_sent >= 1:
        conf += 0.10  # confident it's "not bulk"
    conf = max(0.0, min(0.99, conf))

    return score, conf, reasons


def run_scan(query: str, limit: int = 500, out_path: str = "") -> None:
    svc = get_gmail_service()

    resp = svc.users().messages().list(userId="me", q=query, maxResults=min(limit, 500)).execute()
    msgs = resp.get("messages", []) or []
    if not msgs:
        console.print("[yellow]No messages found for query.[/yellow]")
        return

    # Pass 1: message metadata + thread ids
    aggs: Dict[str, SenderAgg] = {}
    thread_to_senderkey: Dict[str, str] = {}

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

        thread_id = msg.get("threadId")
        if thread_id:
            thread_to_senderkey[thread_id] = key

    # Pass 2: thread metadata to detect SENT + depth
    for thread_id, key in thread_to_senderkey.items():
        thread = svc.users().threads().get(
            userId="me",
            id=thread_id,
            format="metadata",
        ).execute()

        messages = thread.get("messages", []) or []
        aggs[key].threads += 1
        aggs[key].thread_msg_total += len(messages)

        sent_in_thread = 0
        for tm in messages:
            labels = tm.get("labelIds", []) or []
            if "SENT" in labels:
                sent_in_thread += 1

        if sent_in_thread > 0:
            aggs[key].threads_with_sent += 1
            aggs[key].sent_msg_total += sent_in_thread

    # scoring
    for agg in aggs.values():
        agg.bulk_score, agg.confidence, agg.reasons = _bulk_score(agg)

    ranked = sorted(
        aggs.values(),
        key=lambda x: (x.bulk_score, x.count, x.last_ts),
        reverse=True,
    )

    table = Table(title=f"Scan results (sampled {len(msgs)} msgs) — query: {query}")
    table.add_column("Rank", justify="right")
    table.add_column("Domain")
    table.add_column("Count", justify="right")
    table.add_column("ListUnsub%", justify="right")
    table.add_column("Threads", justify="right")
    table.add_column("Replied%", justify="right")
    table.add_column("BulkScore", justify="right")
    table.add_column("Conf", justify="right")
    table.add_column("Last Seen (UTC)")

    for i, s in enumerate(ranked[:30], start=1):
        table.add_row(
            str(i),
            s.domain or "-",
            str(s.count),
            f"{s.list_unsub_rate*100:.0f}%",
            str(s.threads),
            f"{s.replied_thread_rate*100:.0f}%",
            str(s.bulk_score),
            f"{s.confidence:.2f}",
            s.last_seen_iso,
        )

    console.print(table)

    if out_path:
        out = []
        for x in ranked:
            d = asdict(x)
            d["last_seen_iso"] = x.last_seen_iso
            d["list_unsub_rate"] = x.list_unsub_rate
            d["replied_thread_rate"] = x.replied_thread_rate
            d["avg_thread_depth"] = x.avg_thread_depth
            out.append(d)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        console.print(f"[green]Wrote JSON:[/green] {out_path}")
