import argparse
from scan import run_scan
from suppress import run_suppress
from undo import run_undo
from list_suppressed import run_list_suppressed

def main():
    parser = argparse.ArgumentParser(prog="inbox-control")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan_p = sub.add_parser("scan", help="Scan Gmail with a query and rank senders")
    scan_p.add_argument("--query", required=True, help='Gmail search query, e.g. "category:promotions older_than:6m"')
    scan_p.add_argument("--limit", type=int, default=500, help="Max messages to sample (not total results).")
    scan_p.add_argument("--out", default="", help="Optional output JSON path")

    sup_p = sub.add_parser("suppress", help="Create suppression rule + optionally clean existing mail (safe by default)")
    sup_p.add_argument("--target", required=True, help="Domain (example.com) or email (name@example.com)")
    sup_p.add_argument("--query", default="", help='Optional extra Gmail query constraints (e.g. "category:promotions")')
    sup_p.add_argument("--label-prefix", default="InboxControl/Suppressed", help="Label prefix to use")
    sup_p.add_argument("--limit", type=int, default=500, help="Max messages to affect in this run")
    sup_p.add_argument("--include-replied", action="store_true", help="Include threads where you have SENT messages")
    sup_p.add_argument("--trash", action="store_true", help="Move affected messages to TRASH (instead of archive)")
    sup_p.add_argument("--apply", action="store_true", help="Actually perform changes (default is dry-run)")
    sup_p.add_argument("--yes", action="store_true", help="Skip interactive confirmation (only valid with --apply)")

    list_p = sub.add_parser("list-suppressed", help="List suppression labels and filters")
    list_p.add_argument("--label-prefix", default="InboxControl/Suppressed")

    undo_p = sub.add_parser("undo", help="Undo last suppression run for a target")
    undo_p.add_argument("--target", required=True)
    undo_p.add_argument("--restore-inbox", action="store_true")
    undo_p.add_argument("--apply", action="store_true")
    undo_p.add_argument("--yes", action="store_true")
    undo_p.add_argument("--delete-label-if-empty", action="store_true")

    args = parser.parse_args()

    if args.cmd == "scan":
        run_scan(query=args.query, limit=args.limit, out_path=args.out)
    elif args.cmd == "suppress":
        run_suppress(
            target=args.target,
            extra_query=args.query,
            label_prefix=args.label_prefix,
            limit=args.limit,
            include_replied=args.include_replied,
            trash=args.trash,
            apply=args.apply,
            assume_yes=args.yes,
        )
    elif args.cmd == "list-suppressed":
        run_list_suppressed(label_prefix=args.label_prefix)
    elif args.cmd == "undo":
        run_undo(
            target=args.target,
            apply=args.apply,
            restore_inbox=args.restore_inbox,
            assume_yes=args.yes,
            delete_label_if_empty=args.delete_label_if_empty,
        )


if __name__ == "__main__":
    main()