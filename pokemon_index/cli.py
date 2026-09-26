from __future__ import annotations

import argparse
import gzip
import json
import os
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import buyship_mercari, calibration, core, discovery_graph, listing_candidates, offer_comparison, pivota, tcgdex


def read_jsonl(path: str):
    source = Path(path)
    opener = gzip.open if source.suffix == ".gz" else Path.open
    with opener(source, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: {exc}") from exc


def serve(db_path: str, host: str, port: int, internal_catalog_api: bool = False) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            args = parse_qs(parsed.query)
            value = lambda name, default="": args.get(name, [default])[0]
            try:
                with core.connect(db_path) as db:
                    if parsed.path == "/health":
                        result = {"ok": True}
                    elif parsed.path == "/discover":
                        result = {"cards": core.discover(db, value("q"))}
                    elif parsed.path == "/discovery":
                        result = core.discover_intent(db, value("q"))
                    elif parsed.path == "/offers":
                        result = {"offers": core.offers(db, value("card_id"), value("destination") or None,
                                                        value("as_of") or None)}
                    elif parsed.path == "/units":
                        result = {"units": core.units_for_card(db, value("card_id"))}
                    elif parsed.path == "/recommend":
                        result = core.recommend(db, value("unit_id"), value("destination"), value("as_of") or None)
                    elif parsed.path == "/seller-overlap":
                        result = core.seller_overlap(db, value("source"), value("unit_ids").split(","),
                                                     value("as_of") or None)
                    elif parsed.path == "/index":
                        result = core.index_for_unit(db, value("unit_id"), value("date"))
                    elif internal_catalog_api and parsed.path == "/catalog-status":
                        result = core.catalog_status(db)
                    elif internal_catalog_api and parsed.path == "/catalog-search":
                        result = core.catalog_search_internal(
                            db, value("q"), set_code=value("set_code") or None,
                            variant=value("variant") or None,
                            dex_id=int(value("dex_id")) if value("dex_id") else None,
                            illustrator=value("illustrator") or None,
                            limit=int(value("limit", "20")), offset=int(value("offset", "0")),
                        )
                    elif internal_catalog_api and parsed.path == "/catalog-card":
                        result = core.catalog_card_internal(db, value("card_id"))
                    elif internal_catalog_api and parsed.path == "/listing-candidates":
                        result = listing_candidates.retrieve(db, value("title"))
                    elif internal_catalog_api and parsed.path == "/catalog-neighborhood":
                        result = discovery_graph.card_neighborhood(db, value("card_id"))
                    elif internal_catalog_api and parsed.path == "/cross-region-compare":
                        result = offer_comparison.compare_landed_asks(
                            db, value("ja_card_id"), value("en_card_id"),
                            value("destination"), value("as_of") or None)
                    else:
                        self.send_error(404)
                        return
                body = json.dumps(result, ensure_ascii=False, default=str).encode()
                self.send_response(200)
            except (ValueError, KeyError) as exc:
                body = json.dumps({"error": str(exc)}).encode()
                self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    print(f"Serving http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rights-aware Pokémon card commerce index")
    parser.add_argument("--db", default="index.sqlite3", help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    for command in ("register-source", "import-sets", "import-cards", "import-card-identity-exceptions", "import-card-references", "import-card-facets", "import-card-classifications", "import-concept-review-bundle", "import-relationships", "save-exploration", "import-observations", "import-quotes", "import-offer-media", "import-visual-reviews", "import-verified-sales", "calibrate"):
        item = sub.add_parser(command)
        item.add_argument("file", help="UTF-8 JSONL file, or JSON for a concept review bundle")
        if command == "calibrate":
            item.add_argument("--gate-config", help="JSON with sold price probe and daily quota measurements")
    for command in ("discover", "discovery", "units", "offers", "recommend", "seller-overlap", "index", "purge-expired"):
        item = sub.add_parser(command)
        if command in ("discover", "discovery"):
            item.add_argument("query")
        if command in ("offers", "recommend"):
            item.add_argument("card_id" if command == "offers" else "unit_id")
            item.add_argument("--destination")
            item.add_argument("--as-of", help="UTC timestamp for reproducible historical query")
        if command == "units":
            item.add_argument("card_id")
        if command == "seller-overlap":
            item.add_argument("source")
            item.add_argument("unit_ids", help="comma-separated priceable unit IDs")
            item.add_argument("--as-of", help="UTC timestamp for reproducible historical query")
        if command == "index":
            item.add_argument("unit_id")
            item.add_argument("date", help="UTC date YYYY-MM-DD")
    sub.add_parser("catalog-status", help="internal catalog coverage and display status")
    photo_candidates = sub.add_parser("adapt-mercari-photo-candidates")
    photo_candidates.add_argument("file")
    photo_candidates.add_argument("--endpoint", required=True,
                                  choices=("search", "item", "fetch_items"))
    photo_candidates.add_argument("--observed-at", required=True)
    photo_candidates.add_argument("--output", required=True)
    comparison = sub.add_parser("compare-cross-region", help="evidence-bound landed ask spread")
    comparison.add_argument("ja_card_id")
    comparison.add_argument("en_card_id")
    comparison.add_argument("destination")
    comparison.add_argument("--as-of")
    visual = sub.add_parser("visual-gate", help="current AI photo consensus for a listing")
    visual.add_argument("source")
    visual.add_argument("native_id")
    visual.add_argument("observed_at")
    visual.add_argument("card_id")
    catalog_search = sub.add_parser("catalog-search", help="internal metadata search; not exposed over HTTP")
    catalog_search.add_argument("query", nargs="?", default="")
    catalog_search.add_argument("--set-code")
    catalog_search.add_argument("--variant")
    catalog_search.add_argument("--dex-id", type=int)
    catalog_search.add_argument("--illustrator")
    catalog_search.add_argument("--limit", type=int, default=20)
    catalog_search.add_argument("--offset", type=int, default=0)
    catalog_card = sub.add_parser("catalog-card", help="internal card identity and known units")
    catalog_card.add_argument("card_id")
    listing_lookup = sub.add_parser("listing-candidates", help="internal photo-review candidates, never offer resolution")
    listing_lookup.add_argument("title")
    listing_lookup.add_argument("--limit", type=int, default=12)
    neighborhood = sub.add_parser("catalog-neighborhood", help="internal reviewed card relationships")
    neighborhood.add_argument("card_id")
    neighborhood.add_argument("--include-proposed", action="store_true")
    exploration = sub.add_parser("exploration", help="read one structured discovery session")
    exploration.add_argument("session_id")
    exploration.add_argument("--owner-key", required=True)
    candidates = sub.add_parser("exploration-candidates", help="internal candidates for a discovery session")
    candidates.add_argument("session_id")
    candidates.add_argument("--owner-key", required=True)
    candidates.add_argument("--limit", type=int, default=20)
    decision = sub.add_parser("exploration-decision", help="internal next step for a discovery session")
    decision.add_argument("session_id")
    decision.add_argument("--owner-key", required=True)
    server = sub.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    server.add_argument("--internal-catalog-api", action="store_true",
                        help="enable internal catalog HTTP routes; deploy only behind authentication")
    override = sub.add_parser("override-resolution")
    override.add_argument("source")
    override.add_argument("native_id")
    override.add_argument("unit_id")
    override.add_argument("--reviewer", required=True)
    override.add_argument("--reason", required=True)
    adapter = sub.add_parser("adapt-mercari", help="normalize an authorized gateway JSON response")
    adapter.add_argument("file")
    adapter.add_argument("--endpoint", required=True, choices=("search", "item", "fetch_items"))
    adapter.add_argument("--observed-at", required=True)
    adapter.add_argument("--poll-reason", default="discovery", choices=("discovery", "tracking", "panel"))
    adapter.add_argument("--output", required=True, help="new output JSONL file; never overwritten")
    probe = sub.add_parser("probe-mercari", help="bounded read-only gateway contract probe")
    probe.add_argument("--base-url", required=True)
    probe.add_argument("--historical-item-id", required=True)
    probe.add_argument("--category-id")
    probe.add_argument("--allow-legacy-auth", action="store_true")
    export = sub.add_parser("export-pivota", help="read-only Pivota candidate contract")
    export.add_argument("card_id")
    export.add_argument("--destination", required=True)
    export.add_argument("--as-of")
    catalog = sub.add_parser("adapt-tcgdex-set", help="normalize one reviewed Japanese set JSON")
    catalog.add_argument("file")
    catalog.add_argument("--rights-reference", required=True)
    catalog.add_argument("--display-approved", action="store_true")
    catalog.add_argument("--output", required=True, help="new output JSONL file; never overwritten")
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.db, args.host, args.port, args.internal_catalog_api)
        return
    if args.command == "adapt-tcgdex-set":
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
        cards = tcgdex.normalize_japanese_set(payload,
                                              rights_reference=args.rights_reference,
                                              display_approved=args.display_approved)
        with Path(args.output).open("x", encoding="utf-8") as handle:
            for card in cards:
                handle.write(json.dumps(card, ensure_ascii=False) + "\n")
        print(json.dumps({"cards": len(cards), "output": args.output,
                          "display_approved": args.display_approved}, ensure_ascii=False, indent=2))
        return
    with core.connect(args.db) as db:
        if args.command == "init":
            core.init_db(db)
            output = {"db": args.db, "initialized": True}
        elif args.command == "register-source":
            for row in read_jsonl(args.file):
                core.register_source(db, row)
            output = {"registered": True}
        elif args.command == "import-cards":
            output = {"cards": core.import_cards(db, read_jsonl(args.file))}
        elif args.command == "import-card-identity-exceptions":
            output = {"exceptions": core.apply_card_identity_exceptions(db, read_jsonl(args.file))}
        elif args.command == "import-sets":
            output = {"sets": core.import_sets(db, read_jsonl(args.file))}
        elif args.command == "import-card-references":
            output = {"references": core.import_card_references(db, read_jsonl(args.file))}
        elif args.command == "import-card-facets":
            output = {"facets": core.import_card_facets(db, read_jsonl(args.file))}
        elif args.command == "import-card-classifications":
            output = {"classifications": core.import_card_classifications(db, read_jsonl(args.file))}
        elif args.command == "import-concept-review-bundle":
            output = core.import_concept_review_bundle(
                db, json.loads(Path(args.file).read_text(encoding="utf-8")))
        elif args.command == "import-relationships":
            output = {"assertions": discovery_graph.assert_relationships(db, read_jsonl(args.file))}
        elif args.command == "save-exploration":
            rows = list(read_jsonl(args.file))
            if len(rows) != 1:
                raise ValueError("save-exploration expects exactly one JSONL row")
            output = discovery_graph.save_exploration(db, rows[0])
        elif args.command == "catalog-status":
            output = core.catalog_status(db)
        elif args.command == "catalog-search":
            output = core.catalog_search_internal(db, args.query, set_code=args.set_code,
                                                  variant=args.variant, dex_id=args.dex_id,
                                                  illustrator=args.illustrator, limit=args.limit,
                                                  offset=args.offset)
        elif args.command == "catalog-card":
            output = core.catalog_card_internal(db, args.card_id)
        elif args.command == "listing-candidates":
            output = listing_candidates.retrieve(db, args.title, args.limit)
        elif args.command == "catalog-neighborhood":
            output = discovery_graph.card_neighborhood(db, args.card_id, args.include_proposed)
        elif args.command == "exploration":
            output = discovery_graph.get_exploration(db, args.session_id, args.owner_key)
        elif args.command == "exploration-candidates":
            output = discovery_graph.exploration_candidates(db, args.session_id,
                                                             args.owner_key, args.limit)
        elif args.command == "exploration-decision":
            output = discovery_graph.exploration_decision(db, args.session_id, args.owner_key)
        elif args.command == "import-observations":
            output = core.import_observations(db, read_jsonl(args.file))
        elif args.command == "import-quotes":
            output = {"quotes": core.import_quotes(db, read_jsonl(args.file))}
        elif args.command == "import-offer-media":
            output = {"media": offer_comparison.import_media(db, read_jsonl(args.file))}
        elif args.command == "import-visual-reviews":
            output = {"reviews": offer_comparison.import_visual_reviews(db, read_jsonl(args.file))}
        elif args.command == "visual-gate":
            output = offer_comparison.visual_gate(db, args.source, args.native_id,
                                                  args.observed_at, args.card_id)
        elif args.command == "compare-cross-region":
            output = offer_comparison.compare_landed_asks(db, args.ja_card_id,
                                                           args.en_card_id, args.destination,
                                                           args.as_of)
        elif args.command == "import-verified-sales":
            output = {"sales": core.import_verified_sales(db, read_jsonl(args.file))}
        elif args.command == "calibrate":
            output = calibration.evaluate(db, read_jsonl(args.file))
            if args.gate_config:
                config = json.loads(Path(args.gate_config).read_text(encoding="utf-8"))
                output["gate1"] = calibration.gate1_decision(
                    output,
                    sold_detail_has_price=config.get("sold_detail_has_price"),
                    required_calls_per_day=config.get("required_calls_per_day"),
                    quota_calls_per_day=config.get("quota_calls_per_day"),
                    min_hot_sales=config.get("min_hot_sales"),
                    min_mid_sales=config.get("min_mid_sales"),
                )
        elif args.command == "override-resolution":
            core.override_resolution(db, args.source, args.native_id, args.unit_id, args.reviewer, args.reason)
            output = {"overridden": True}
        elif args.command == "adapt-mercari":
            core._policy(db, "mercari_bns")
            payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
            rows = buyship_mercari.normalize_response(payload, args.observed_at,
                                                      endpoint=args.endpoint,
                                                      poll_reason=args.poll_reason)
            raw_items = buyship_mercari.response_items(payload, args.endpoint)
            with Path(args.output).open("x", encoding="utf-8") as handle:
                for row, raw_item in zip(rows, raw_items):
                    core.archive_raw_item(db, row, raw_item, args.endpoint)
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            output = {"observations": len(rows), "output": args.output,
                      "source": "mercari_bns"}
        elif args.command == "adapt-mercari-photo-candidates":
            policy = core._policy(db, "mercari_bns")
            if not policy["media_ai_allowed"]:
                raise ValueError("Mercari media AI use has not been authorized")
            payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
            raw_items = buyship_mercari.response_items(payload, args.endpoint)
            with Path(args.output).open("x", encoding="utf-8") as handle:
                for item in raw_items:
                    handle.write(json.dumps(buyship_mercari.photo_candidates(
                        item, args.observed_at), ensure_ascii=False) + "\n")
            output = {"photo_candidates": len(raw_items), "output": args.output}
        elif args.command == "probe-mercari":
            core._policy(db, "mercari_bns")
            client = buyship_mercari.GatewayClient(
                args.base_url, os.getenv("BNS_MERCARI_HMAC_SECRET", ""),
                allow_legacy_auth=args.allow_legacy_auth,
            )
            output = {"warning": "old demo auth contract; production signing requires Buy&Ship review",
                      "checks": [asdict(result) for result in buyship_mercari.gate0_probe(
                          client, historical_item_id=args.historical_item_id,
                          category_id=args.category_id)]}
        elif args.command == "export-pivota":
            output = pivota.export_card(db, args.card_id, args.destination, args.as_of)
        elif args.command == "discover":
            output = {"cards": core.discover(db, args.query)}
        elif args.command == "discovery":
            output = core.discover_intent(db, args.query)
        elif args.command == "units":
            output = {"units": core.units_for_card(db, args.card_id)}
        elif args.command == "offers":
            output = {"offers": core.offers(db, args.card_id, args.destination, args.as_of)}
        elif args.command == "recommend":
            if not args.destination:
                parser.error("recommend requires --destination")
            output = core.recommend(db, args.unit_id, args.destination, args.as_of)
        elif args.command == "seller-overlap":
            output = core.seller_overlap(db, args.source, args.unit_ids.split(","), args.as_of)
        elif args.command == "index":
            output = core.index_for_unit(db, args.unit_id, args.date)
        else:
            output = core.purge_expired(db)
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
