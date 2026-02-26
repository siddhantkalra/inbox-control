from __future__ import annotations

from state import SuppressRun, append_run
import re
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from rich.console import Console
from rich.table import Table

from gmail_client import get_gmail_service_modify

console = Console()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.I)


@dataclass
class Plan:
    target: str
    mode: str  # "domain" or "email"
    label_name: str
    filter_criteria: str
    gmail_query: str
    message_ids: List[str]
    skipped_thread_ids: Set[str]


def _sanitize_label_part(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "-", s)
    return s[:60] if len(s) > 60 else s


def _detect_target_mode(target: str) -> Tuple[str, str]:
    t = target.strip().lower()
    if EMAIL_RE.match(t):
        return "email", t
    if DOMAIN_RE.match(t):
        return "domain", t
    raise ValueError("Target must be an email (name@domain.com) or domain (domain.com).")


def _ensure_label(service, label_name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", []) or []
    for lb in labels:
        if lb.get("name") == label_name:
            return lb["id"]

    body = {
        "name": label_name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
        "type": "user",
    }
    created = service.users().labels().create(userId="me", body=body).execute()
    return created["id"]


def _ensure_filter(service, query: str, add_label_id: str, archive: bool) -> str:
    """
    Create a Gmail filter:
    - criteria.query = query
    - action: addLabelIds + optionally remove INBOX
    """
    body = {
        "criteria": {"query": query},
        "action": {
            "addLabelIds": [add_label_id],
            "removeLabelIds": ["INBOX"] if archive else [],
        },
    }
    created = service.users().settings().filters().create(userId="me", body=body).execute()
    return created["id"]


def _list_message_ids(service, q: str, limit: int) -> List[Tuple[str, str]]:
    """
    Returns list of (message_id, thread_id)
    """
    out: List[Tuple[str, str]] = []
    page_token = None
    while len(out) < limit:
        resp = service.users().messages().list(
            userId="me",
            q=q,
            maxResults=min(500, limit - len(out)),
            pageToken=page_token,
        ).execute()
        msgs = resp.get("messages", []) or []
        for m in msgs:
            out.append((m["id"], m.get("threadId", "")))
            if len(out) >= limit:
                break
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def _thread_has_sent(service, thread_id: str) -> bool:
    thread = service.users().threads().get(userId="me", id=thread_id, format="metadata").execute()
    for m in thread.get("messages", []) or []:
        labels = m.get("labelIds", []) or []
        if "SENT" in labels:
            return True
    return False


def _build_plan(
    target: str,
    extra_query: str,
    label_prefix: str,
    limit: int,
    include_replied: bool,
    trash: bool,
) -> Plan:
    mode, normalized = _detect_target_mode(target)

    if mode == "email":
        crit = f"from:{normalized}"
    else:
        # Use from:*@domain form. It catches most cases; later we can add OR variants if needed.
        crit = f"from:*@{normalized}"

    # include user extra constraints (e.g. category:promotions)
    q_parts = [crit]
    if extra_query.strip():
        q_parts.append(f"({extra_query.strip()})")
    # avoid touching spam/trash unless user explicitly wants
    q_parts.append("-in:trash")
    q_parts.append("-in:spam")
    gmail_query = " ".join(q_parts)

    label_name = f"{label_prefix}/{_sanitize_label_part(normalized)}"

    svc = get_gmail_service_modify()
    pairs = _list_message_ids(svc, gmail_query, limit=limit)

    msg_ids: List[str] = []
    skipped_threads: Set[str] = set()

    if not include_replied:
        # protect threads where you replied
        seen_threads: Set[str] = set()
        for mid, tid in pairs:
            if not tid:
                msg_ids.append(mid)
                continue
            if tid in skipped_threads:
                continue
            if tid in seen_threads:
                msg_ids.append(mid)
                continue
            seen_threads.add(tid)
            if _thread_has_sent(svc, tid):
                skipped_threads.add(tid)
            else:
                msg_ids.append(mid)
    else:
        msg_ids = [mid for mid, _ in pairs]

    filter_query = gmail_query  # same query used for filter criteria

    return Plan(
        target=normalized,
        mode=mode,
        label_name=label_name,
        filter_criteria=filter_query,
        gmail_query=gmail_query,
        message_ids=msg_ids,
        skipped_thread_ids=skipped_threads,
    )


def _print_plan(plan: Plan, trash: bool):
    table = Table(title="Suppression Plan (dry-run preview)")
    table.add_column("Field")
    table.add_column("Value")

    table.add_row("Target", f"{plan.mode}: {plan.target}")
    table.add_row("Gmail query", plan.gmail_query)
    table.add_row("Label", plan.label_name)
    table.add_row("Filter criteria", plan.filter_criteria)
    table.add_row("Action for future mail", "Label + Archive (remove INBOX)" if not trash else "Label + Archive (remove INBOX); optional TRASH for existing")
    table.add_row("Existing messages matched", str(len(plan.message_ids)))
    table.add_row("Skipped threads (replied)", str(len(plan.skipped_thread_ids)))

    console.print(table)


def run_suppress(
    target: str,
    extra_query: str = "",
    label_prefix: str = "InboxControl/Suppressed",
    limit: int = 500,
    include_replied: bool = False,
    trash: bool = False,
    apply: bool = False,
    assume_yes: bool = False,
) -> None:
    svc = get_gmail_service_modify()

    plan = _build_plan(
        target=target,
        extra_query=extra_query,
        label_prefix=label_prefix,
        limit=limit,
        include_replied=include_replied,
        trash=trash,
    )

    _print_plan(plan, trash=trash)

    if not apply:
        console.print("[yellow]Dry-run only.[/yellow] Re-run with --apply to perform changes.")
        return

    if assume_yes is False:
        console.print("\nType YES to confirm (anything else cancels): ", end="")
        confirm = input().strip()
        if confirm != "YES":
            console.print("[red]Cancelled.[/red]")
            return

    # 1) ensure label exists
    label_id = _ensure_label(svc, plan.label_name)
    console.print(f"[green]Label ready:[/green] {plan.label_name} ({label_id})")

    # 2) create filter (future protection): label + archive
    filter_id = _ensure_filter(svc, plan.filter_criteria, add_label_id=label_id, archive=True)
    console.print(f"[green]Filter created:[/green] {filter_id}")

    # 3) clean existing messages: label + archive or trash
    if plan.message_ids:
        body = {
            "ids": plan.message_ids,
            "addLabelIds": [label_id],
            "removeLabelIds": ["INBOX"],
        }
        svc.users().messages().batchModify(userId="me", body=body).execute()
        console.print(f"[green]Archived + labeled existing messages:[/green] {len(plan.message_ids)}")

        if trash:
            # Move to trash (still reversible). Must call modify endpoint per-message.
            for mid in plan.message_ids:
                svc.users().messages().trash(userId="me", id=mid).execute()
            console.print(f"[green]Moved to trash:[/green] {len(plan.message_ids)}")

        try:
            run = SuppressRun(
                ts_utc=SuppressRun.now_ts(),
                target=plan.target,
                mode=plan.mode,
                label_name=plan.label_name,
                label_id=label_id,
                filter_id=filter_id,
                filter_query=plan.filter_criteria,
                message_ids=plan.message_ids,
            )
            append_run(run)
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] could not write run journal: {e}")
        console.print("[bold green]Done.[/bold green]")
