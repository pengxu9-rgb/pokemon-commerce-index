"""Offline marketplace capture replay and read-only per-card tracking reports."""
from __future__ import annotations

import argparse
from contextlib import closing, ExitStack
import json
from pathlib import Path
import socket
from unittest.mock import patch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="explicit local operator database")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create a new empty operator database; no source permissions are granted")
    commands.add_parser("prepare", help="add tracking tables to an existing local operator database")
    replay = commands.add_parser("replay", help="import a local authorized capture atomically")
    replay.add_argument("capture", type=Path)
    report = commands.add_parser("report", help="read-only current asks, quality claims and listing history")
    report.add_argument("card_id")
    report.add_argument("--source", action="append")
    report.add_argument("--history-days", type=int, default=7)
    commands.add_parser("purge", help="apply existing source retention to local observations and claim evidence")
    args = parser.parse_args(argv)
    def denied(*_args, **_kwargs):
        raise AssertionError("market tracker is offline; network access is disabled")
    with ExitStack() as offline:
        for obj, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                          (socket.socket, "sendto"), (socket, "create_connection"), (socket, "getaddrinfo")):
            offline.enter_context(patch.object(obj, name, denied))
        from pokemon_index import core, marketplace_ingest
        if args.command == "report":
            from pokemon_index.market_tracking import build_report
            result = build_report(args.db, args.card_id, history_days=args.history_days, sources=args.source)
        elif args.command == "init":
            # Exclusive creation prevents accidentally initializing an existing database.
            with args.db.open("xb"):
                pass
            with closing(core.connect(args.db)) as db:
                core.init_db(db)
                marketplace_ingest.initialize(db)
            result = {"status": "initialized", "source_permissions_granted": False, "network_calls": 0}
        else:
            if not args.db.is_file():
                raise FileNotFoundError("existing local operator database required")
            with closing(core.connect(args.db)) as db:
                if args.command == "prepare":
                    marketplace_ingest.initialize(db)
                    result = {"status": "prepared", "source_permissions_granted": False, "network_calls": 0}
                elif args.command == "replay":
                    result = marketplace_ingest.import_capture(db, marketplace_ingest.load_capture(args.capture))
                else:
                    result = marketplace_ingest.purge(db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
