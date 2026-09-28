"""Local, matcher-blind double-review workbench for private listing samples.

Serve only on 127.0.0.1. The queue and SQLite decisions remain in work/ and
are not bundled with the catalog. A reviewer must actually inspect a card
photo before a non-unknown finish can enter the exported human gold set.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pokemon_index.core import normalize_collector_number

REVIEWER_RE = re.compile(r"[A-Za-z0-9_-]{2,40}\Z")
SET_RE = re.compile(r"[A-Za-z0-9-]{1,24}\Z")
NUMBER_RE = re.compile(r"[A-Za-z0-9-]{1,16}(?:/[A-Za-z0-9-]{1,16})?\Z")
VARIANT_RE = re.compile(r"[a-z][a-z0-9_-]{0,79}\Z")
LABEL_FIELDS = ("single_card", "language", "set_code", "number", "variant",
                "grade_status", "grade_company", "grade_value")


def load_queue(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    queue = {row["item_key"]: row for row in rows}
    if not rows or len(queue) != len(rows):
        raise ValueError("review queue is empty or contains duplicate item keys")
    for row in rows:
        if not str(row.get("url", "")).startswith("https://"):
            raise ValueError("listing URL must use HTTPS")
        if not isinstance(row.get("image_urls"), list) or any(
                not isinstance(url, str) or not url.startswith("https://")
                for url in row["image_urls"]):
            raise ValueError("image URLs must be HTTPS links")
    return queue


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS review (
            item_key TEXT NOT NULL, reviewer TEXT NOT NULL,
            submitted_at TEXT NOT NULL, label_json TEXT NOT NULL,
            PRIMARY KEY(item_key, reviewer)
        );
        CREATE TABLE IF NOT EXISTS adjudication (
            item_key TEXT PRIMARY KEY, adjudicator TEXT NOT NULL,
            submitted_at TEXT NOT NULL, label_json TEXT NOT NULL,
            reason TEXT NOT NULL
        );
    """)
    return db


@contextmanager
def session(path: Path):
    db = connect(path)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def validate_reviewer(value: object) -> str:
    if not isinstance(value, str) or not REVIEWER_RE.fullmatch(value):
        raise ValueError("reviewer ID must be 2–40 letters, digits, '_' or '-'")
    return value


def validate_label(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("label must be an object")
    single = value.get("single_card")
    if single not in {"yes", "no", "uncertain"}:
        raise ValueError("single_card must be yes, no or uncertain")
    language = value.get("language") or "unknown"
    if language not in {"ja", "en", "ko", "zh", "unknown"}:
        raise ValueError("invalid language")
    set_code = str(value.get("set_code") or "").strip()
    number = str(value.get("number") or "").strip()
    variant = value.get("variant") or "unknown"
    if set_code and not SET_RE.fullmatch(set_code):
        raise ValueError("invalid set code")
    if number and not NUMBER_RE.fullmatch(number):
        raise ValueError("invalid collector number")
    if not isinstance(variant, str) or not VARIANT_RE.fullmatch(variant):
        raise ValueError("invalid finish variant")
    image_seen = value.get("image_seen") is True
    if variant != "unknown" and not image_seen:
        raise ValueError("a specific finish requires a card photo actually reviewed")
    if single != "yes" and (set_code or number or variant != "unknown"):
        raise ValueError("non-single listing cannot have a single-card identity")
    grade_company = str(value.get("grade_company") or "").upper().strip()
    grade_value = str(value.get("grade_value") or "").strip()
    grade_status = value.get("grade_status") or ("graded" if grade_company else "unknown")
    if grade_status not in {"unknown", "raw", "graded"}:
        raise ValueError("grade status must be unknown, raw or graded")
    if grade_company and grade_company not in {"PSA", "BGS", "CGC", "ARS", "PGC", "OTHER"}:
        raise ValueError("invalid grading company")
    if bool(grade_company) != bool(grade_value):
        raise ValueError("grading company and grade must be filled together")
    if grade_status == "graded" and not grade_company:
        raise ValueError("graded status requires company and grade")
    if grade_status != "graded" and grade_company:
        raise ValueError("raw or unknown grade cannot have company and grade")
    if grade_status != "unknown" and not image_seen:
        raise ValueError("a known raw or graded status requires a listing photo reviewed")
    if single != "yes" and grade_status != "unknown":
        raise ValueError("non-single listing cannot have one graded-card label")
    if len(grade_value) > 20:
        raise ValueError("grade value is too long")
    if grade_value and not re.fullmatch(r"(?:10\+?|[1-9](?:\.5)?)", grade_value):
        raise ValueError("grade must use a canonical numeric value, such as 9.5 or 10+")
    notes = str(value.get("evidence_notes") or "").strip()
    if len(notes) > 2000:
        raise ValueError("evidence notes are too long")
    if (set_code or number or variant != "unknown" or grade_status != "unknown") and not notes:
        raise ValueError("known identity, finish or grading status requires evidence notes")
    return {
        "single_card": single, "language": language,
        "set_code": set_code.upper() if set_code else None,
        "number": normalize_collector_number(number) if number else None,
        "variant": variant, "grade_status": grade_status,
        "grade_company": grade_company or None,
        "grade_value": grade_value or None, "image_seen": image_seen,
        "evidence_notes": notes,
    }


def reviews_for(db: sqlite3.Connection, item_key: str) -> list[dict]:
    def legacy_status(label: dict) -> dict:
        label.setdefault("grade_status", "graded" if label.get("grade_company") else "unknown")
        return label
    return [{"reviewer": row["reviewer"], "submitted_at": row["submitted_at"],
             "label": legacy_status(json.loads(row["label_json"]))}
            for row in db.execute(
                "SELECT reviewer,submitted_at,label_json FROM review WHERE item_key=? ORDER BY submitted_at, reviewer",
                (item_key,)).fetchall()]


def disagree(first: dict, second: dict) -> bool:
    return any(first["label"][field] != second["label"][field] for field in LABEL_FIELDS)


def status(queue: dict[str, dict], db: sqlite3.Connection) -> dict:
    result = {"items": len(queue), "reviewed_once": 0, "reviewed_twice": 0,
              "conflicts": 0, "adjudicated": 0, "ready_for_gold": 0}
    for item_key in queue:
        rows = reviews_for(db, item_key)
        result["reviewed_once"] += len(rows) >= 1
        result["reviewed_twice"] += len(rows) >= 2
        if len(rows) >= 2:
            conflict = disagree(rows[0], rows[1])
            result["conflicts"] += conflict
            adjudicated = bool(db.execute("SELECT 1 FROM adjudication WHERE item_key=?",
                                         (item_key,)).fetchone())
            result["adjudicated"] += adjudicated
            result["ready_for_gold"] += not conflict or adjudicated
    return result


def next_review(queue: dict[str, dict], db: sqlite3.Connection, reviewer: str) -> dict:
    done = {row[0] for row in db.execute("SELECT item_key FROM review WHERE reviewer=?", (reviewer,))}
    for key, item in queue.items():
        if key not in done and len(reviews_for(db, key)) < 2:
            return {"item": item, "reviewer_done": len(done), "total": len(queue)}
    return {"item": None, "reviewer_done": len(done), "total": len(queue)}


def next_conflict(queue: dict[str, dict], db: sqlite3.Connection) -> dict:
    for key, item in queue.items():
        rows = reviews_for(db, key)
        if len(rows) >= 2 and disagree(rows[0], rows[1]) and not db.execute(
                "SELECT 1 FROM adjudication WHERE item_key=?", (key,)).fetchone():
            return {"item": item, "reviews": rows[:2]}
    return {"item": None, "reviews": []}


def export_gold(queue: dict[str, dict], db: sqlite3.Connection, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"gold export already exists: {output}")
    rows = []
    pending = 0
    for key, item in queue.items():
        reviews = reviews_for(db, key)
        if len(reviews) < 2:
            pending += 1
            continue
        conflict = disagree(reviews[0], reviews[1])
        adjudication = db.execute("SELECT * FROM adjudication WHERE item_key=?", (key,)).fetchone()
        if conflict and not adjudication:
            pending += 1
            continue
        label = json.loads(adjudication["label_json"]) if adjudication else reviews[0]["label"]
        label.setdefault("grade_status", "graded" if label.get("grade_company") else "unknown")
        photo_confirmed = bool(label["image_seen"] and
                               (adjudication or reviews[1]["label"]["image_seen"]))
        if not photo_confirmed:
            label = {**label, "variant": "unknown", "grade_status": "unknown",
                     "grade_company": None, "grade_value": None}
        single = label["single_card"] == "yes"
        row = {
            "item_key": key,
            "source": item["source"], "native_id": item["native_id"],
            "title": item["title"], "url": item["url"],
            "single_card": label["single_card"],
            "language": label["language"],
            "identity_status": ("abstain" if not single else "complete" if label["set_code"]
                                and label["number"] else "partial"),
            "label_status": ("abstain" if not single else "matched" if label["set_code"]
                             and label["number"] and label["variant"] != "unknown" else "partial"),
            "proposed_set": label["set_code"] if single else None,
            "proposed_number": label["number"] if single else None,
            "proposed_variant": label["variant"] if single and label["variant"] != "unknown" else None,
            "grade_company": label["grade_company"] if single else None,
            "grade_value": label["grade_value"] if single else None,
            "grade_status": label["grade_status"] if single else "unknown",
            "human_reviewed": True,
            "reviewers": [review["reviewer"] for review in reviews[:2]],
            "review_evidence": [{"reviewer": review["reviewer"],
                                 "submitted_at": review["submitted_at"],
                                 "image_seen": review["label"]["image_seen"],
                                 "evidence_notes": review["label"].get("evidence_notes", "")}
                                for review in reviews[:2]],
            "adjudicator": adjudication["adjudicator"] if adjudication else None,
            "adjudication_reason": adjudication["reason"] if adjudication else None,
            "image_seen": label["image_seen"],
            "evidence_notes": label.get("evidence_notes", ""),
        }
        rows.append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                      encoding="utf-8")
    return {"exported": len(rows), "pending": pending, "output": str(output)}


def serve(queue_path: Path, db_path: Path, port: int) -> None:
    queue = load_queue(queue_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with session(db_path):
        pass
    ui = Path(__file__).with_name("review_ui.html").read_bytes()
    js = Path(__file__).with_name("review_ui.js").read_bytes()
    css = Path(__file__).with_name("review_ui.css").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' https:; "
                             "script-src 'self'; style-src 'self'; connect-src 'self'; "
                             "base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, value: object) -> None:
            self._send(code, json.dumps(value, ensure_ascii=False).encode("utf-8"))

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                self._send(200, ui, "text/html; charset=utf-8")
                return
            if parsed.path == "/review_ui.js":
                self._send(200, js, "text/javascript; charset=utf-8")
                return
            if parsed.path == "/review_ui.css":
                self._send(200, css, "text/css; charset=utf-8")
                return
            params = parse_qs(parsed.query)
            try:
                with session(db_path) as db:
                    if parsed.path == "/api/status":
                        self._json(200, status(queue, db))
                    elif parsed.path == "/api/next":
                        reviewer = validate_reviewer(params.get("reviewer", [""])[0])
                        self._json(200, next_review(queue, db, reviewer))
                    elif parsed.path == "/api/conflict":
                        validate_reviewer(params.get("reviewer", [""])[0])
                        self._json(200, next_conflict(queue, db))
                    else:
                        self._json(404, {"error": "not found"})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self) -> None:
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                self._json(403, {"error": "cross-origin submission blocked"})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json(415, {"error": "application/json required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"error": "invalid Content-Length"})
                return
            if length < 1 or length > 16384:
                self._json(413, {"error": "invalid request size"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be an object")
                reviewer = validate_reviewer(payload.get("reviewer"))
                key = payload.get("item_key")
                if key not in queue:
                    raise ValueError("unknown queue item")
                label = validate_label(payload.get("label"))
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                with session(db_path) as db:
                    if self.path == "/api/review":
                        rows = reviews_for(db, key)
                        if any(row["reviewer"] == reviewer for row in rows):
                            raise ValueError("this reviewer already submitted this item")
                        if len(rows) >= 2:
                            raise ValueError("two independent reviews already exist")
                        db.execute("INSERT INTO review VALUES (?,?,?,?)",
                                   (key, reviewer, now, json.dumps(label, ensure_ascii=False)))
                    elif self.path == "/api/adjudicate":
                        rows = reviews_for(db, key)
                        if len(rows) < 2 or not disagree(rows[0], rows[1]):
                            raise ValueError("item has no two-review disagreement")
                        if reviewer in {row["reviewer"] for row in rows[:2]}:
                            raise ValueError("adjudicator must be a third person")
                        reason = str(payload.get("reason") or "").strip()
                        if len(reason) < 10 or len(reason) > 2000:
                            raise ValueError("adjudication reason must be 10–2000 characters")
                        db.execute("INSERT INTO adjudication VALUES (?,?,?,?,?)",
                                   (key, reviewer, now, json.dumps(label, ensure_ascii=False), reason))
                    else:
                        self._json(404, {"error": "not found"})
                        return
                self._json(201, {"saved": True, "item_key": key})
            except (ValueError, KeyError, sqlite3.IntegrityError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Private review workbench: http://127.0.0.1:{port}/ ({len(queue)} items)", flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    web = sub.add_parser("serve")
    web.add_argument("--queue", type=Path, required=True)
    web.add_argument("--db", type=Path, required=True)
    web.add_argument("--port", type=int, default=8766)
    export = sub.add_parser("export")
    export.add_argument("--queue", type=Path, required=True)
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.queue, args.db, args.port)
    else:
        with session(args.db) as db:
            print(json.dumps(export_gold(load_queue(args.queue), db, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
