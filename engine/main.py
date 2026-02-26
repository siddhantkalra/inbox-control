import argparse
from scan import run_scan

def main():
    parser = argparse.ArgumentParser(prog="inbox-control")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan_p = sub.add_parser("scan", help="Scan Gmail with a query and rank senders")
    scan_p.add_argument("--query", required=True, help='Gmail search query, e.g. "category:promotions older_than:6m"')
    scan_p.add_argument("--limit", type=int, default=500, help="Max messages to sample (not total results).")
    scan_p.add_argument("--out", default="", help="Optional output JSON path")

    args = parser.parse_args()

    if args.cmd == "scan":
        run_scan(query=args.query, limit=args.limit, out_path=args.out)

if __name__ == "__main__":
    main()
