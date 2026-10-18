from __future__ import annotations

import time
_IMPORT_STARTED = time.monotonic()

import argparse
import gzip
import json
import os
import sqlite3
import sys
import uuid
from dataclasses import asdict
from contextlib import closing, contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import buyship_mercari, buyship_partner, buyer_questions, calibration, catalog_question_resolver, catalog_question_resolver_v2, core, discovery_graph, ebay_browse, listing_candidates, multi_record_scans, number_aliases, number_conflicts, number_graph, offer_comparison, pivota, question_routing, question_routing_v2, question_routing_v3, question_routing_v4, question_routing_v5, question_routing_v6, question_routing_v7, tcgdex
from . import collector_discovery, collector_inventory, supported_catalog,collector_evidence,collector_journey,card_comparison,collector_runtime

_IMPORT_SECONDS = time.monotonic() - _IMPORT_STARTED


def source_scan_filter(value):
    if value not in {'true','false'}:raise ValueError('with_source_scans must be true or false')
    return value=='true'


def request_json(raw):
    """Bound container depth before decoding, independently of Python's parser."""
    text=raw.decode('utf-8');depth=0;quoted=False;escaped=False
    for char in text:
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '[{':
            depth+=1
            if depth>128:raise ValueError('JSON nesting exceeds supported depth')
        elif char in ']}':depth-=1
    try:return json.loads(text)
    except RecursionError as exc:raise ValueError('JSON nesting exceeds supported depth') from exc


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


def create_server(db_path: str, host: str, port: int, internal_catalog_api: bool = False, *,
                  catalog_workers=1, catalog_queue_size=4, catalog_queue_wait=0.25, catalog_deadline=8.0,
                  require_catalog_read_model=False):
    prepare_started = time.monotonic()
    bootstrap_timings = {'module_import': _IMPORT_SECONDS}
    if require_catalog_read_model and not internal_catalog_api:
        raise ValueError('packaged read model requires the internal catalog API')
    snapshot=collector_runtime.snapshot_identity(db_path) if internal_catalog_api else None
    def check_snapshot():
        if snapshot is None:return
        try:current=collector_runtime.snapshot_identity(db_path)
        except OSError as exc:raise collector_runtime.CatalogSnapshotChanged() from exc
        if current!=snapshot:raise collector_runtime.CatalogSnapshotChanged()
    admission=collector_runtime.CatalogAdmission(workers=catalog_workers,queue_size=catalog_queue_size,
        queue_wait=catalog_queue_wait,deadline=catalog_deadline)
    @contextmanager
    def catalog_db(handler):
        queued=time.monotonic();entered=None
        try:
            # Upload, parsing and admission do not buy a fresh eight seconds.
            with admission.acquire(expires=handler.received+catalog_deadline) as expires:
                entered=time.monotonic();handler.timings['queue']=entered-queued
                check_snapshot()
                # A progress callback cannot interrupt SQLite busy waits or the
                # connection setup queries; keep their lock wait short as well.
                if packaged is not None:
                    with read_model.owned_http_request(expires=expires) as db:
                        yield db
                        check_snapshot()
                else:
                    with closing(core.connect(db_path,readonly=True,timeout=0.1)) as db:
                        with collector_runtime.sqlite_deadline(db,expires):
                            with read_model.request(db,strict_readonly=True) if read_model is not None else nullcontext():
                                yield db
                                check_snapshot()
        finally:
            handler.timings['compute' if entered is not None else 'queue']=time.monotonic()-(entered or queued)
    journey_revision=None;read_model=None;packaged=None
    if internal_catalog_api:
        from . import catalog_read_model_artifact
        with closing(core.connect(db_path,readonly=True)) as db:
            with collector_runtime.sqlite_deadline(db,time.monotonic()+catalog_deadline):
                packaged=catalog_read_model_artifact.load_packaged(db,
                    required=require_catalog_read_model, bootstrap_timings=bootstrap_timings)
            if packaged is not None:
                read_model,journey_revision,_artifact_evidence=packaged
            else:
                journey_revision=collector_journey.catalog_revision(db)
                check_snapshot()
                with collector_runtime.sqlite_deadline(db,time.monotonic()+catalog_deadline):
                    try:read_model=collector_runtime.CatalogReadModel(db)
                    except collector_runtime.CatalogReadModelUnsupported:pass
        check_snapshot()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.received=time.monotonic();self.timings={}
            self.request_id=uuid.uuid4().hex
            super().setup()
            # Also bound inactive request headers, before do_POST/do_GET run.
            self.connection.settimeout(10)

        def log_request(self,code='-',size='-'):
            # Request paths/queries and arbitrary HTTP errors are not telemetry.
            # send_json emits only the bounded, generated fields below.
            pass

        def log_message(self,format,*args):
            pass

        def read_body(self,length):
            expires=self.received+catalog_deadline
            chunks=[];remaining=length
            while remaining:
                budget=expires-time.monotonic()
                if budget<=0:raise collector_runtime.CatalogDeadline()
                self.connection.settimeout(budget)
                try:chunk=self.rfile.read1(min(remaining,65536))
                except TimeoutError as exc:raise collector_runtime.CatalogDeadline() from exc
                if not chunk:raise ValueError('incomplete JSON request body')
                chunks.append(chunk);remaining-=len(chunk)
            if time.monotonic()>=expires:raise collector_runtime.CatalogDeadline()
            return b''.join(chunks)

        def send_json(self,status,body,*,runtime_error=None):
            # Admission is already released: slow/disconnected readers cannot
            # retain the catalog compute slot.
            started=time.monotonic();delivery='complete'
            try:
                self.connection.settimeout(10)
                self.send_response(status)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(body)))
                self.send_header('X-Collector-Request-ID',self.request_id)
                self.send_header('Server-Timing',', '.join(f'{key};dur={value*1000:.3f}'
                    for key,value in self.timings.items()))
                if runtime_error:
                    self.send_header('X-Collector-Error',runtime_error)
                    if status==503:self.send_header('Retry-After','1')
                self.end_headers();self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError,TimeoutError):
                delivery='disconnected_or_write_timeout'
            finally:
                # Cloud logs can correlate an individual response with the
                # caller without recording tokens, bodies, sessions or queries.
                route=urlparse(self.path).path
                safe_route=route if route in {'/collector-journey','/collector-inventory','/card-comparison','/health'} else 'other'
                print(json.dumps(dict(event='collector_http',request_id=self.request_id,route=safe_route,
                    status=status,error=runtime_error,delivery=delivery,response_bytes=len(body),
                    elapsed_ms=round((time.monotonic()-self.received)*1000,3),
                    delivery_ms=round((time.monotonic()-started)*1000,3),
                    timings_ms={key:round(value*1000,3) for key,value in self.timings.items()})),file=sys.stderr,flush=True)

        def runtime_failure(self,exc):
            if isinstance(exc,collector_runtime.CatalogBusy):
                code,status='catalog_busy',503
            elif isinstance(exc,collector_runtime.CatalogSnapshotChanged):
                code,status='catalog_snapshot_changed',503
            elif isinstance(exc,collector_runtime.CatalogDeadline):
                code,status='catalog_work_budget_exceeded',504
            else:
                code,status='catalog_temporarily_unavailable',503
            self.send_json(status,json.dumps({'error':code}).encode(),runtime_error=code)

        def do_POST(self):
            # Start when headers are parsed, not when an idle pooled socket is
            # accepted. The separate header inactivity timeout is not a compute
            # budget and must not age a future request before it exists.
            self.received=time.monotonic()
            route=urlparse(self.path).path
            if not internal_catalog_api or route not in {'/collector-inventory','/collector-journey','/card-comparison'}:
                self.send_error(404);return
            try:
                length=self.headers.get('Content-Length','')
                if not length.isdecimal() or not 1<=int(length)<=262144:
                    raise ValueError('Content-Length must be 1–262144 bytes')
                if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':
                    raise ValueError('Content-Type must be application/json')
                if self.headers.get('Transfer-Encoding'):raise ValueError('Transfer-Encoding is unsupported')
                raw=self.read_body(int(length))
                payload=request_json(raw)
                self.timings['receive']=time.monotonic()-self.received
                with catalog_db(self) as db:
                    result=(card_comparison.compare(db,payload) if route=='/card-comparison' else
                            collector_inventory.compare(db,payload) if route=='/collector-inventory' else
                            collector_journey.replay(db,payload,revision=journey_revision))
                    body=json.dumps(result,ensure_ascii=False).encode()
                status=200
            except (ValueError,KeyError,TimeoutError) as exc:
                body=json.dumps({'error':str(exc)}).encode();status=400
            except (collector_runtime.CatalogBusy,collector_runtime.CatalogDeadline,collector_runtime.CatalogSnapshotChanged,sqlite3.OperationalError) as exc:
                self.runtime_failure(exc);return
            self.send_json(status,body)

        def do_GET(self):
            self.received=time.monotonic()
            parsed = urlparse(self.path)
            args = parse_qs(parsed.query)
            value = lambda name, default="": args.get(name, [default])[0]
            if parsed.path=="/health":
                self.send_json(200,b'{"ok": true}');return
            routes={'/discover','/discovery','/offers','/units','/recommend','/seller-overlap','/index'}
            if internal_catalog_api:
                routes.update({'/catalog-status','/supported-status','/collector-evidence-status',
                    '/catalog-evidence','/collector-discovery','/catalog-search','/catalog-card',
                    '/listing-candidates','/catalog-neighborhood','/buyer-question-plan',
                    '/number-explanation','/cross-region-compare'})
            if parsed.path not in routes:
                self.send_error(404);return
            self.connection.settimeout(10)
            try:
                self.timings['receive']=time.monotonic()-self.received
                with catalog_db(self) as db:
                    if parsed.path == "/discover":
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
                        result = core.index_for_unit(db, value("unit_id"), value("date"),
                                                     value("as_of") or None)
                    elif internal_catalog_api and parsed.path == "/catalog-status":
                        result = core.catalog_status(db)
                    elif internal_catalog_api and parsed.path == "/supported-status":
                        result = supported_catalog.status(db)
                    elif internal_catalog_api and parsed.path == '/collector-evidence-status':
                        result=collector_evidence.status(db)
                    elif internal_catalog_api and parsed.path == '/catalog-evidence':
                        result=collector_evidence.card_context(db,value('card_id'))
                    elif internal_catalog_api and parsed.path == "/collector-discovery":
                        result = collector_discovery.execute(db,value("q"),
                                   limit=int(value("limit","50")),offset=int(value("offset","0")),
                                   with_source_scans=source_scan_filter(value('with_source_scans','false')))
                    elif internal_catalog_api and parsed.path == "/catalog-search":
                        result = core.catalog_search_internal(
                            db, value("q"), set_code=value("set_code") or None,
                            variant=value("variant") or None,
                            language=value("language") or None,
                            dex_id=int(value("dex_id")) if value("dex_id") else None,
                            illustrator=value("illustrator") or None,
                            limit=int(value("limit", "20")), offset=int(value("offset", "0")),
                            with_source_scans=source_scan_filter(value('with_source_scans','false')),
                        )
                    elif internal_catalog_api and parsed.path == "/catalog-card":
                        result = core.catalog_card_internal(db, value("card_id"))
                    elif internal_catalog_api and parsed.path == "/listing-candidates":
                        result = listing_candidates.retrieve(db, value("title"))
                    elif internal_catalog_api and parsed.path == "/catalog-neighborhood":
                        result = discovery_graph.card_neighborhood(db, value("card_id"))
                    elif internal_catalog_api and parsed.path == "/buyer-question-plan":
                        result = buyer_questions.plan_card_question(
                            db, value("question_type"), value("card_id") or None,
                            value("target_language") or None)
                    elif internal_catalog_api and parsed.path == "/number-explanation":
                        result = number_graph.explain_number_pair(
                            db, value("left_card_id"), value("right_card_id"))
                    elif internal_catalog_api and parsed.path == "/cross-region-compare":
                        result = offer_comparison.compare_landed_asks(
                            db, value("ja_card_id"), value("en_card_id"),
                            value("destination"), value("as_of") or None)
                    else:
                        self.send_error(404)
                        return
                    body = json.dumps(result, ensure_ascii=False, default=str).encode()
                status=200
            except (ValueError, KeyError) as exc:
                body = json.dumps({"error": str(exc)}).encode()
                status=400
            except (collector_runtime.CatalogBusy,collector_runtime.CatalogDeadline,collector_runtime.CatalogSnapshotChanged,sqlite3.OperationalError) as exc:
                self.runtime_failure(exc);return
            self.send_json(status,body)

    class Server(ThreadingHTTPServer):
        # The default backlog of five obscures a 16-client application burst as
        # TCP connection timeouts before admission can return an explicit 503.
        request_queue_size=64
    server=Server((host,port),Handler)
    server.catalog_bootstrap='packaged' if packaged is not None else 'native'
    bootstrap_timings['server_prepare_total'] = time.monotonic() - prepare_started
    server.catalog_bootstrap_timings = bootstrap_timings
    return server


def serve(db_path: str, host: str, port: int, internal_catalog_api: bool = False, *,
          require_catalog_read_model=False) -> None:
    with create_server(db_path,host,port,internal_catalog_api,
                       require_catalog_read_model=require_catalog_read_model) as server:
        if internal_catalog_api:
            print(json.dumps({'event':'collector_bootstrap','bootstrap':server.catalog_bootstrap,
                'timings_seconds':server.catalog_bootstrap_timings},sort_keys=True),flush=True)
        print(f"Serving http://{host}:{server.server_address[1]}")
        server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rights-aware Pokémon card commerce index")
    parser.add_argument("--db", default="index.sqlite3", help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    for command in ("register-source", "import-sets", "import-cards", "import-card-identity-exceptions", "import-card-number-conflicts", "import-card-number-aliases", "import-card-number-alias-visuals", "import-card-number-alias-visual-recoveries", "import-card-number-alias-scan-candidates", "import-card-multi-record-scans", "import-card-number-secondary-candidates", "import-card-references", "import-card-facets", "import-card-classifications", "import-concept-review-bundle", "import-relationships", "save-exploration", "import-observations", "import-quotes", "import-offer-media", "import-visual-reviews", "import-verified-sales", "calibrate"):
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
            item.add_argument("--as-of", help="knowledge cutoff for reproducible historical query")
    sub.add_parser("catalog-status", help="internal catalog coverage and display status")
    photo_candidates = sub.add_parser("adapt-mercari-photo-candidates")
    photo_candidates.add_argument("file")
    photo_candidates.add_argument("--endpoint", required=True,
                                  choices=("search", "item", "fetch_items"))
    photo_candidates.add_argument("--observed-at", required=True)
    photo_candidates.add_argument("--output", required=True)
    ebay_adapter = sub.add_parser("adapt-ebay-browse", help="offline fixed-price search response adapter")
    ebay_adapter.add_argument("file")
    ebay_adapter.add_argument("--observed-at", required=True)
    ebay_adapter.add_argument("--output", required=True)
    ebay_probe = sub.add_parser("probe-ebay-browse", help="one shape-only Browse API access probe")
    ebay_probe.add_argument("--environment", choices=("sandbox", "production"), default="sandbox")
    ebay_probe.add_argument("--query", default="Pokemon card Pikachu")
    ebay_probe.add_argument("--production-approved", action="store_true")
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
    visual_approval = sub.add_parser("approve-visual-resolution",
                                     help="bind a current raw-card ask to independent photo evidence")
    visual_approval.add_argument("source")
    visual_approval.add_argument("native_id")
    visual_approval.add_argument("observed_at")
    visual_approval.add_argument("card_id")
    catalog_search = sub.add_parser("catalog-search", help="internal metadata search; not exposed over HTTP")
    catalog_search.add_argument("query", nargs="?", default="")
    catalog_search.add_argument("--set-code")
    catalog_search.add_argument("--variant")
    catalog_search.add_argument("--language")
    catalog_search.add_argument("--printing-type", choices=("prism_star",))
    catalog_search.add_argument("--dex-id", type=int)
    catalog_search.add_argument("--illustrator")
    catalog_search.add_argument("--with-source-scans",action='store_true')
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
    buyer_plan = sub.add_parser("buyer-question-plan", help="internal evidence gates for a card question")
    buyer_plan.add_argument("question_type", choices=sorted(buyer_questions.QUESTION_TYPES))
    buyer_plan.add_argument("--card-id")
    buyer_plan.add_argument("--target-language", choices=("ja", "en"))
    route_plan = sub.add_parser("question-route-plan", help="plan from reviewed structured question facts")
    route_plan.add_argument("file", help="JSON object with product scope, focus, identity and media facts")
    route_plan.add_argument("--capability", action="append", default=[],
                            choices=sorted(question_routing.CAPABILITIES))
    route_plan_v2 = sub.add_parser("question-route-plan-v2", help="plan from separate object, task and identity facts")
    route_plan_v2.add_argument("file", help="v2 structured question facts JSON")
    route_plan_v2.add_argument("--resolution", help="optional evidence-backed catalog resolution JSON")
    route_plan_v2.add_argument("--capability", action="append", default=[],
                               choices=sorted(question_routing_v2.V2_CAPABILITIES))
    route_plan_v3 = sub.add_parser("question-route-plan-v3", help="plan with seller state, platform and rarity separated")
    route_plan_v3.add_argument("file", help="v3 structured question facts JSON")
    route_plan_v3.add_argument("--resolution", help="optional evidence-backed catalog resolution JSON")
    route_plan_v3.add_argument("--catalog-db", help="read-only catalog snapshot for automatic resolution")
    route_plan_v3.add_argument("--catalog-resolver-version", choices=("v1", "v2"), default="v2")
    route_plan_v3.add_argument("--capability", action="append", default=[],
                               choices=sorted(question_routing_v3.V3_CAPABILITIES))
    route_plan_v4 = sub.add_parser("question-route-plan-v4", help="plan trend and buy-or-wait evidence")
    route_plan_v4.add_argument("file", help="v4 structured question facts JSON")
    route_plan_v4.add_argument("--resolution", help="optional evidence-backed catalog resolution JSON")
    route_plan_v4.add_argument("--catalog-db", help="read-only catalog snapshot for automatic resolution")
    route_plan_v4.add_argument("--capability", action="append", default=[],
                               choices=sorted(question_routing_v4.CAPABILITIES))
    route_plan_v5 = sub.add_parser("question-route-plan-v5", help="plan seller timing, relative value and card selection")
    route_plan_v5.add_argument("file", help="v5 structured question facts JSON")
    route_plan_v5.add_argument("--resolution", help="optional evidence-backed catalog resolution JSON")
    route_plan_v5.add_argument("--catalog-db", help="read-only catalog snapshot for automatic resolution")
    route_plan_v5.add_argument("--capability", action="append", default=[],
                               choices=sorted(question_routing_v5.CAPABILITIES))
    for version, module in (("v6", question_routing_v6), ("v7", question_routing_v7)):
        route = sub.add_parser(f"question-route-plan-{version}", help="plan seller scope, merchant and proceeds evidence")
        route.add_argument("file", help=f"{version} structured question facts JSON")
        route.add_argument("--resolution", help="optional evidence-backed catalog resolution JSON")
        route.add_argument("--catalog-db", help="read-only catalog snapshot for resolution and cohort checks")
        route.add_argument("--sale-cohort", help="unit cohort JSON verified against --catalog-db")
        route.add_argument("--capability", action="append", default=[], choices=sorted(module.CAPABILITIES))
    number_explanation = sub.add_parser("number-explanation", help="internal release-scoped number comparison")
    number_explanation.add_argument("left_card_id")
    number_explanation.add_argument("right_card_id")
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
    collector = sub.add_parser("collector-discovery", help="execute internal source-backed collector tasks")
    collector.add_argument("question")
    collector.add_argument("--limit", type=int, default=50)
    collector.add_argument("--offset", type=int, default=0)
    inventory=sub.add_parser('collector-inventory',help='compare a user-asserted inventory to scoped internal catalog records')
    inventory.add_argument('file',help='JSON containing question, owned_items and optional pagination')
    journey=sub.add_parser('collector-journey',help='replay caller-owned collector actions without storing a conversation')
    journey.add_argument('file',help='JSON containing bounded turns and optional revision/limit')
    comparison=sub.add_parser('card-comparison',help='compare two internal scoped catalog coordinates without price or physical-copy inference')
    comparison.add_argument('file',help='JSON containing left and right card IDs or language/release/number scopes')
    sub.add_parser("supported-status", help="positive metadata support and deployed alias coverage")
    sub.add_parser('collector-evidence-status',help='scoped official declarations and proposed artwork findings')
    evidence_import=sub.add_parser('import-collector-evidence')
    evidence_import.add_argument('file')
    evidence_context=sub.add_parser('catalog-evidence')
    evidence_context.add_argument('card_id')
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    server.add_argument("--internal-catalog-api", action="store_true",
                        help="enable internal catalog HTTP routes; deploy only behind authentication")
    server.add_argument("--require-catalog-read-model", action="store_true",
                        help="require the fixed image's verified static read model before listening")
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
    partner_preview = sub.add_parser("preview-buyship-fixture",
                                     help="offline URL-to-quote preview; never creates an order")
    partner_preview.add_argument("fixture", help="JSON with resolve and quote responses")
    partner_preview.add_argument("card_id")
    partner_preview.add_argument("unit_id")
    partner_preview.add_argument("source")
    partner_preview.add_argument("native_id")
    partner_preview.add_argument("--destination", required=True, choices=("US", "HK"))
    partner_preview.add_argument("--state", help="required for US destinations")
    partner_preview.add_argument("--currency")
    partner_preview.add_argument("--variant-key")
    partner_preview.add_argument("--as-of", help="UTC time for a reproducible fixture preview")
    partner_shortlist = sub.add_parser("preview-buyship-shortlist",
                                       help="offline exact-unit quote ranking; never creates an order")
    partner_shortlist.add_argument("file", help="JSON shortlist with fixture paths")
    partner_shortlist.add_argument("--store", action="store_true",
                                   help="store only when the source explicitly permits partner quote retention")
    catalog = sub.add_parser("adapt-tcgdex-set", help="normalize one reviewed Japanese set JSON")
    catalog.add_argument("file")
    catalog.add_argument("--rights-reference", required=True)
    catalog.add_argument("--display-approved", action="store_true")
    catalog.add_argument("--output", required=True, help="new output JSONL file; never overwritten")
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.db, args.host, args.port, args.internal_catalog_api,
              require_catalog_read_model=args.require_catalog_read_model)
        return
    if args.command in {'collector-inventory','collector-journey','card-comparison'}:
        with closing(core.connect(args.db,readonly=True)) as db:
            payload=json.loads(Path(args.file).read_text(encoding='utf-8'))
            output=(card_comparison.compare(db,payload) if args.command=='card-comparison' else
                    collector_inventory.compare(db,payload) if args.command=='collector-inventory' else
                    collector_journey.replay(db,payload))
        print(json.dumps(output,ensure_ascii=False,indent=2));return
    if args.command in {'catalog-evidence','collector-evidence-status'}:
        with closing(core.connect(args.db,readonly=True)) as db:
            output=(collector_evidence.card_context(db,args.card_id) if args.command=='catalog-evidence'
                    else collector_evidence.status(db))
        print(json.dumps(output,ensure_ascii=False,indent=2));return
    if args.command == "question-route-plan":
        facts = json.loads(Path(args.file).read_text(encoding="utf-8"))
        print(json.dumps(question_routing.plan_question(
            facts, capabilities=set(args.capability)), ensure_ascii=False, indent=2))
        return
    if args.command == "question-route-plan-v2":
        facts = json.loads(Path(args.file).read_text(encoding="utf-8"))
        resolution = (json.loads(Path(args.resolution).read_text(encoding="utf-8"))
                      if args.resolution else None)
        print(json.dumps(question_routing_v2.plan_question(
            facts, resolution=resolution, capabilities=set(args.capability)),
            ensure_ascii=False, indent=2))
        return
    if args.command == "question-route-plan-v3":
        facts = json.loads(Path(args.file).read_text(encoding="utf-8"))
        if args.resolution and args.catalog_db:
            raise ValueError("choose --resolution or --catalog-db, not both")
        resolution = (json.loads(Path(args.resolution).read_text(encoding="utf-8"))
                      if args.resolution else None)
        if args.catalog_db:
            catalog_path = Path(args.catalog_db).resolve(strict=True)
            with closing(sqlite3.connect(f"{catalog_path.as_uri()}?mode=ro", uri=True)) as catalog_db:
                catalog_db.row_factory = sqlite3.Row
                resolver = (catalog_question_resolver if args.catalog_resolver_version == "v1"
                            else catalog_question_resolver_v2)
                plan = resolver.plan_question_with_catalog(
                    catalog_db, facts, capabilities=set(args.capability))
        else:
            plan = question_routing_v3.plan_question(
                facts, resolution=resolution, capabilities=set(args.capability))
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    if args.command == "question-route-plan-v4":
        facts = json.loads(Path(args.file).read_text(encoding="utf-8"))
        if args.resolution and args.catalog_db:
            raise ValueError("choose --resolution or --catalog-db, not both")
        resolution = (json.loads(Path(args.resolution).read_text(encoding="utf-8"))
                      if args.resolution else None)
        lookup = None
        if args.catalog_db:
            catalog_path = Path(args.catalog_db).resolve(strict=True)
            with closing(sqlite3.connect(f"{catalog_path.as_uri()}?mode=ro", uri=True)) as catalog_db:
                catalog_db.row_factory = sqlite3.Row
                lookup = catalog_question_resolver_v2.resolve_question(
                    catalog_db, question_routing_v4.catalog_projection(facts))
            resolution = lookup["resolution"]
        plan = question_routing_v4.plan_question(
            facts, resolution=resolution, capabilities=set(args.capability))
        if lookup is not None:
            plan["catalog_lookup"] = lookup
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    if args.command in {"question-route-plan-v5", "question-route-plan-v6", "question-route-plan-v7"}:
        routing = {"v5": question_routing_v5, "v6": question_routing_v6,
                   "v7": question_routing_v7}[args.command.rsplit("-", 1)[-1]]
        facts = json.loads(Path(args.file).read_text(encoding="utf-8"))
        routing.validate_facts(facts)
        if args.resolution and args.catalog_db:
            raise ValueError("choose --resolution or --catalog-db, not both")
        resolution = (json.loads(Path(args.resolution).read_text(encoding="utf-8"))
                      if args.resolution else None)
        lookup = None
        cohort_path = getattr(args, "sale_cohort", None)
        cohort = json.loads(Path(cohort_path).read_text(encoding="utf-8")) if cohort_path else None
        if cohort is not None and not args.catalog_db:
            raise ValueError("--sale-cohort requires --catalog-db to verify its units and evidence")
        if args.catalog_db:
            catalog_path = Path(args.catalog_db).resolve(strict=True)
            with closing(sqlite3.connect(f"{catalog_path.as_uri()}?mode=ro", uri=True)) as catalog_db:
                catalog_db.row_factory = sqlite3.Row
                lookup = catalog_question_resolver_v2.resolve_question(
                    catalog_db, routing.catalog_projection(facts))
                if cohort is not None:
                    routing.validate_sale_cohort(cohort)
                    if cohort != routing.build_sale_cohort(catalog_db, cohort["unit_ids"]):
                        raise ValueError("sale cohort evidence changed or does not match the catalog")
            resolution = lookup["resolution"]
        extra = {"sale_cohort": cohort} if not args.command.endswith("v5") else {}
        plan = routing.plan_question(facts, resolution=resolution,
                                     capabilities=set(args.capability), **extra)
        if lookup is not None:
            plan["catalog_lookup"] = lookup
        print(json.dumps(plan, ensure_ascii=False, indent=2))
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
    if args.command == "adapt-ebay-browse":
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
        rows = ebay_browse.normalize_search(payload, args.observed_at)
        destination = Path(args.output)
        if destination.exists():
            raise FileExistsError("adapter output already exists")
        destination.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                       for row in rows), encoding="utf-8")
        print(json.dumps({"observations": len(rows), "output": str(destination),
                          "resolution": "photo_required"}, ensure_ascii=False, indent=2))
        return
    if args.command == "probe-ebay-browse":
        client = ebay_browse.BrowseProbe(
            os.getenv("EBAY_CLIENT_ID", ""), os.getenv("EBAY_CLIENT_SECRET", ""),
            environment=args.environment,
            production_approved=args.production_approved and
                                os.getenv("EBAY_PRODUCTION_APPROVED") == "1")
        print(json.dumps(client.search_shape(args.query), ensure_ascii=False, indent=2))
        return
    with closing(core.connect(args.db)) as db, db:
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
        elif args.command == "import-card-number-conflicts":
            output = number_conflicts.apply_rules(db, read_jsonl(args.file))
        elif args.command == "import-card-number-aliases":
            output = number_aliases.apply_candidates(db, read_jsonl(args.file))
        elif args.command == "import-card-number-alias-visuals":
            output = number_aliases.apply_visual_context(db, read_jsonl(args.file))
        elif args.command == "import-card-number-alias-visual-recoveries":
            output = number_aliases.apply_visual_recoveries(db, read_jsonl(args.file))
        elif args.command == "import-card-number-alias-scan-candidates":
            output = number_aliases.apply_scan_candidates(db, read_jsonl(args.file))
        elif args.command == "import-card-multi-record-scans":
            output = multi_record_scans.apply_evidence(db, read_jsonl(args.file))
        elif args.command == "import-card-number-secondary-candidates":
            output = number_aliases.apply_secondary_candidates(db, read_jsonl(args.file))
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
        elif args.command == "supported-status":
            output = supported_catalog.status(db)
        elif args.command=='import-collector-evidence':
            output={'evidence_events':collector_evidence.import_evidence(db,read_jsonl(args.file))}
        elif args.command == "collector-discovery":
            output = collector_discovery.execute(db,args.question,limit=args.limit,offset=args.offset)
        elif args.command == "catalog-search":
            output = core.catalog_search_internal(db, args.query, set_code=args.set_code,
                                                  variant=args.variant, language=args.language,
                                                  printing_type=args.printing_type,
                                                  dex_id=args.dex_id,
                                                  illustrator=args.illustrator, limit=args.limit,
                                                  offset=args.offset,with_source_scans=args.with_source_scans)
        elif args.command == "catalog-card":
            output = core.catalog_card_internal(db, args.card_id)
        elif args.command == "listing-candidates":
            output = listing_candidates.retrieve(db, args.title, args.limit)
        elif args.command == "catalog-neighborhood":
            output = discovery_graph.card_neighborhood(db, args.card_id, args.include_proposed)
        elif args.command == "buyer-question-plan":
            output = buyer_questions.plan_card_question(
                db, args.question_type, args.card_id, args.target_language)
        elif args.command == "number-explanation":
            output = number_graph.explain_number_pair(db, args.left_card_id,
                                                       args.right_card_id)
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
        elif args.command == "approve-visual-resolution":
            output = offer_comparison.approve_visual_resolution(
                db, args.source, args.native_id, args.observed_at, args.card_id)
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
        elif args.command == "preview-buyship-fixture":
            fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
            destination = {"country": args.destination}
            if args.state:
                destination["state"] = args.state
            output = buyship_partner.preview_quote(
                db, card_id=args.card_id, unit_id=args.unit_id,
                source=args.source, native_id=args.native_id,
                destination=destination,
                client=buyship_partner.FixturePartnerClient(fixture),
                now=args.as_of, variant_key=args.variant_key, currency=args.currency)
        elif args.command == "preview-buyship-shortlist":
            shortlist_path = Path(args.file)
            shortlist = json.loads(shortlist_path.read_text(encoding="utf-8"))
            previews = []
            for candidate in shortlist["candidates"]:
                fixture_path = shortlist_path.parent / candidate["fixture"]
                fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                previews.append(buyship_partner.preview_quote(
                    db, card_id=shortlist["card_id"], unit_id=shortlist["unit_id"],
                    source=candidate["source"], native_id=candidate["native_id"],
                    destination=shortlist["destination"],
                    client=buyship_partner.FixturePartnerClient(fixture),
                    now=shortlist["as_of"], variant_key=candidate.get("variant_key"),
                    currency=shortlist.get("currency")))
            output = buyship_partner.rank_quote_previews(previews, now=shortlist["as_of"], db=db)
            if args.store:
                output["stored_quotes"] = buyship_partner.persist_quote_previews(db, previews)
                output["indexed_recommendation"] = core.recommend(
                    db, shortlist["unit_id"], shortlist["destination"]["country"],
                    shortlist["as_of"])
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
            output = core.index_for_unit(db, args.unit_id, args.date, args.as_of)
        else:
            output = core.purge_expired(db)
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
