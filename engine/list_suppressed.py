from __future__ import annotations

from rich.console import Console
from rich.table import Table

from gmail_client import get_gmail_service_modify

console = Console()


def run_list_suppressed(label_prefix: str = "InboxControl/Suppressed") -> None:
    svc = get_gmail_service_modify()

    labels = svc.users().labels().list(userId="me").execute().get("labels", []) or []
    filters = svc.users().settings().filters().list(userId="me").execute().get("filter", []) or []

    pref = label_prefix.rstrip("/") + "/"
    lbls = sorted([l for l in labels if (l.get("name") or "").startswith(pref)], key=lambda x: x.get("name", ""))

    t1 = Table(title="InboxControl Labels")
    t1.add_column("Label")
    t1.add_column("Id")
    for l in lbls:
        t1.add_row(l.get("name", ""), l.get("id", ""))
    console.print(t1)

    t2 = Table(title="Gmail Filters (first 50)")
    t2.add_column("Filter Id")
    t2.add_column("Query", overflow="fold")
    shown = 0
    for f in filters:
        q = ((f.get("criteria") or {}).get("query") or "").strip()
        if not q:
            continue
        if "from:" in q:
            t2.add_row(f.get("id", ""), q)
            shown += 1
            if shown >= 50:
                break
    console.print(t2)