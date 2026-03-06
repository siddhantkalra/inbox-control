from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Set, Tuple

from rich.console import Console
from rich.table import Table

from gmail_client import get_gmail_service_readonly

console = Console()

NO_REPLY_RE = re.compile(r"\b(no-?reply|donotreply|do-not-reply|noreply)\b", re.I)
BULK_HDR_HINT_RE = re.compile(r"(campaign|marketing|mailer|sendgrid|mailchimp|klaviyo|braze|customer\.io|hubspot|pardot|marketo)", re.I)

# ---- Data model ----

@dataclass
class Candidate:
    key: str  # domain or sender
    kind: str  # "domain" or "sender"
    count: int
    threads: int
    last_seen_utc: str

    # signals
    list_unsub_rate: float
    precedence_bulk_rate: float
    auto_submitted_rate: float
    no_reply_rate: float
    bulk_header_hint_rate: float
    replied_rate: float

    bulk_score: int
    confidence: float
    suggested_action: str  # "suppress" or "review"
    signals: List[str]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hdr(headers: List[Dict[str, str]], name: str) -> str:
    name_l = name.lower()
    for h in headers:
        if (h.get("name") or "").lower() == name_l:
            return h.get("value") or ""
    return ""


def _from_domain(from_header: str) -> str:
    # pull email from header then domain
    # examples: "Name <x@y.com>" or "x@y.com"
    m = re.search(r"<([^>]+)>", from_header)
    email = (m.group(1) if m else from_header).strip()
    # strip quotes, spaces
    email = email.replace('"', "").strip()
    if "@" in email:
        return email.split("@", 1)[1].lower()
    return ""


def _from_addr(from_header: str) -> str:
    m = re.search(r"<([^>]+)>", from_header)
    email = (m.group(1) if m else from_header).strip()
    return email.replace('"', "").strip().lower()


def _safe_pct(n: int, d: int) -> float:
    return (n / d) if d else 0.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _thread_has_sent(service, thread_id: str) -> bool:
    thread = service.users().threads().get(userId="me", id=thread_id, format="metadata").execute()
    for m in thread.get("messages", []) or []:
        labels = m.get("labelIds", []) or []
        if "SENT" in labels:
            return True
    return False


def _score(signals: Dict[str, float], replied_rate: float) -> Tuple[int, float, List[str], str]:
    """
    Returns (bulk_score 0-100, confidence 0-1, signal_strings, suggested_action)
    """
    reasons: List[str] = []

    w_list_unsub = 0.35
    w_precedence = 0.20
    w_auto_sub = 0.15
    w_no_reply = 0.10
    w_hdr_hint = 0.20

    raw = (
        w_list_unsub * signals["list_unsub_rate"]
        + w_precedence * signals["precedence_bulk_rate"]
        + w_auto_sub * signals["auto_submitted_rate"]
        + w_no_reply * signals["no_reply_rate"]
        + w_hdr_hint * signals["bulk_header_hint_rate"]
    )

    raw_adj = raw * (1.0 - min(0.85, replied_rate))
    bulk_score = int(round(_clamp01(raw_adj) * 100))

    conf = _clamp01((bulk_score / 100) * (1.0 - min(0.70, replied_rate)))

    if signals["list_unsub_rate"] >= 0.6:
        reasons.append(f"List-Unsubscribe present ({signals['list_unsub_rate']*100:.0f}%)")
    if signals["precedence_bulk_rate"] >= 0.4:
        reasons.append(f"Precedence bulk/list ({signals['precedence_bulk_rate']*100:.0f}%)")
    if signals["auto_submitted_rate"] >= 0.4:
        reasons.append(f"Auto-Submitted ({signals['auto_submitted_rate']*100:.0f}%)")
    if signals["no_reply_rate"] >= 0.5:
        reasons.append(f"No-reply sender ({signals['no_reply_rate']*100:.0f}%)")
    if signals["bulk_header_hint_rate"] >= 0.4:
        reasons.append(f"Campaign/mail provider headers ({signals['bulk_header_hint_rate']*100:.0f}%)")
    if replied_rate > 0:
        reasons.append(f"You replied in related threads ({replied_rate*100:.0f}%)")

    if bulk_score >= 55 and conf >= 0.50 and replied_rate == 0:
        action = "suppress"
    elif bulk_score >= 30:
        action = "review"
    else:
        action = "ignore"

    return bulk_score, conf, reasons, action


def run_detect(query: str, limit: int = 500, kind: str = "domain", out_path: str = "") -> None:
    svc = get_gmail_service_readonly()

    # gather message ids
    ids: List[str] = []
    req = svc.users().messages().list(userId="me", q=query, maxResults=min(limit, 500)).execute()
    ids.extend([m["id"] for m in req.get("messages", [])])
    while len(ids) < limit and req.get("nextPageToken"):
        req = svc.users().messages().list(
            userId="me",
            q=query,
            pageToken=req["nextPageToken"],
            maxResults=min(500, limit - len(ids)),
        ).execute()
        ids.extend([m["id"] for m in req.get("messages", [])])

    if not ids:
        console.print("[yellow]No messages found for query.[/yellow]")
        return

    # aggregate per key
    agg: Dict[str, Dict[str, Any]] = {}
    thread_owner: Dict[str, str] = {}

    def ensure(k: str) -> Dict[str, Any]:
        if k not in agg:
            agg[k] = {
                "count": 0,
                "threads": set(),
                "last_seen": "",
                "list_unsub": 0,
                "precedence_bulk": 0,
                "auto_submitted": 0,
                "no_reply": 0,
                "hdr_hint": 0,
                "replied_threads": 0,
            }
        return agg[k]

    # fetch minimal message metadata
    for mid in ids:
        msg = svc.users().messages().get(
            userId="me",
            id=mid,
            format="metadata",
            metadataHeaders=["From", "List-Unsubscribe", "Precedence", "Auto-Submitted", "X-Mailer", "X-Campaign", "X-SES-Outgoing", "X-Mailgun-Sending-Ip"],
        ).execute()

        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []
        from_h = _hdr(headers, "From")
        domain = _from_domain(from_h)
        sender = _from_addr(from_h)

        key = domain if kind == "domain" else sender
        if not key:
            continue

        a = ensure(key)
        a["count"] += 1
        thread_id = msg.get("threadId")
        if thread_id:
            a["threads"].add(thread_id)
            thread_owner.setdefault(thread_id, key)

        internal_date = msg.get("internalDate")
        if internal_date:
            ts = datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).isoformat()
            if ts > (a["last_seen"] or ""):
                a["last_seen"] = ts

        lu = _hdr(headers, "List-Unsubscribe")
        if lu:
            a["list_unsub"] += 1

        prec = _hdr(headers, "Precedence").lower()
        if prec in ("bulk", "list", "junk"):
            a["precedence_bulk"] += 1

        auto = _hdr(headers, "Auto-Submitted").lower()
        if auto and auto != "no":
            a["auto_submitted"] += 1

        if NO_REPLY_RE.search(sender):
            a["no_reply"] += 1

        # header hints
        x_mailer = _hdr(headers, "X-Mailer")
        x_camp = _hdr(headers, "X-Campaign")
        if BULK_HDR_HINT_RE.search(x_mailer) or BULK_HDR_HINT_RE.search(x_camp):
            a["hdr_hint"] += 1

    checked_threads: Set[str] = set()
    for thread_id, key in thread_owner.items():
        if thread_id in checked_threads:
            continue
        checked_threads.add(thread_id)
        if _thread_has_sent(svc, thread_id):
            agg[key]["replied_threads"] += 1

    candidates: List[Candidate] = []
    for k, a in agg.items():
        cnt = a["count"]
        threads = len(a["threads"])
        signals = {
            "list_unsub_rate": _safe_pct(a["list_unsub"], cnt),
            "precedence_bulk_rate": _safe_pct(a["precedence_bulk"], cnt),
            "auto_submitted_rate": _safe_pct(a["auto_submitted"], cnt),
            "no_reply_rate": _safe_pct(a["no_reply"], cnt),
            "bulk_header_hint_rate": _safe_pct(a["hdr_hint"], cnt),
        }
        replied_rate = _safe_pct(a["replied_threads"], threads)

        bulk_score, conf, reasons, action = _score(signals, replied_rate)

        candidates.append(
            Candidate(
                key=k,
                kind=kind,
                count=cnt,
                threads=threads,
                last_seen_utc=a["last_seen"] or _now_utc_iso(),
                list_unsub_rate=signals["list_unsub_rate"],
                precedence_bulk_rate=signals["precedence_bulk_rate"],
                auto_submitted_rate=signals["auto_submitted_rate"],
                no_reply_rate=signals["no_reply_rate"],
                bulk_header_hint_rate=signals["bulk_header_hint_rate"],
                replied_rate=replied_rate,
                bulk_score=bulk_score,
                confidence=conf,
                suggested_action=action,
                signals=reasons,
            )
        )

    candidates.sort(key=lambda c: (c.suggested_action != "suppress", -c.bulk_score, -c.count, c.key))

    t = Table(title=f"Detect results (sampled {len(ids)} msgs) — query: {query}")
    t.add_column("Rank", justify="right")
    t.add_column("Key")
    t.add_column("Count", justify="right")
    t.add_column("Replied%", justify="right")
    t.add_column("BulkScore", justify="right")
    t.add_column("Conf", justify="right")
    t.add_column("Action")
    t.add_column("Why", overflow="fold")

    for i, c in enumerate(candidates[:50], start=1):
        why = "; ".join(c.signals[:4])
        t.add_row(
            str(i),
            c.key,
            str(c.count),
            f"{c.replied_rate*100:.0f}%",
            str(c.bulk_score),
            f"{c.confidence:.2f}",
            c.suggested_action,
            why,
        )

    console.print(t)

    if out_path:
        out = {"query": query, "kind": kind, "limit": limit, "sampled": len(ids), "candidates": [asdict(c) for c in candidates]}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        console.print(f"[green]Wrote:[/green] {out_path}")