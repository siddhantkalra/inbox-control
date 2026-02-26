from __future__ import annotations

from rich.console import Console
from rich.table import Table

from gmail_client import get_gmail_service_modify
from state import latest_run_for_target

console = Console()


def run_undo(target: str, apply: bool = False, restore_inbox: bool = False, assume_yes: bool = False, delete_label_if_empty: bool = False) -> None:
    svc = get_gmail_service_modify()
    run = latest_run_for_target(target)

    if not run:
        console.print("[red]No local suppression run found for that target.[/red]")
        console.print("Undo only works for suppressions performed after journaling is enabled.")
        return

    filters = svc.users().settings().filters().list(userId="me").execute().get("filter", []) or []
    filter_exists = any(f.get("id") == run.filter_id for f in filters)

    table = Table(title="Undo Plan (dry-run preview)")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Target", f"{run.mode}: {run.target}")
    table.add_row("Last run (UTC)", run.ts_utc)
    table.add_row("Filter id", run.filter_id)
    table.add_row("Filter exists", "yes" if filter_exists else "no")
    table.add_row("Label", f"{run.label_name} ({run.label_id})")
    table.add_row("Restore INBOX?", "yes" if restore_inbox else "no")
    table.add_row("Messages to update", str(len(run.message_ids)))
    table.add_row("Delete label if empty?", "yes" if delete_label_if_empty else "no")
    console.print(table)

    if not apply:
        console.print("[yellow]Dry-run only.[/yellow] Re-run with --apply to perform undo.")
        return

    if not assume_yes:
        console.print("\nType YES to confirm undo (anything else cancels): ", end="")
        if input().strip() != "YES":
            console.print("[red]Cancelled.[/red]")
            return

    if filter_exists:
        svc.users().settings().filters().delete(userId="me", id=run.filter_id).execute()
        console.print(f"[green]Deleted filter:[/green] {run.filter_id}")
    else:
        console.print("[yellow]Filter already missing; skipping delete.[/yellow]")

    if run.message_ids:
        body = {
            "ids": run.message_ids,
            "removeLabelIds": [run.label_id],
            "addLabelIds": ["INBOX"] if restore_inbox else [],
        }
        svc.users().messages().batchModify(userId="me", body=body).execute()
        console.print(f"[green]Updated messages:[/green] {len(run.message_ids)}")

     if delete_label_if_empty:
        lbl = svc.users().labels().get(userId="me", id=run.label_id).execute()
        mt = int(lbl.get("messagesTotal", 0))
        tt = int(lbl.get("threadsTotal", 0))
        if mt == 0 and tt == 0:
            svc.users().labels().delete(userId="me", id=run.label_id).execute()
            console.print(f"[green]Deleted empty label:[/green] {run.label_name}")
        else:
            console.print(f"[yellow]Label not empty; kept it (messagesTotal={mt}, threadsTotal={tt}).[/yellow]")

    console.print("[bold green]Undo complete.[/bold green]")