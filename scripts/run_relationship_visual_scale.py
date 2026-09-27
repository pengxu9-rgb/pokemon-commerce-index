"""Run a frozen relationship queue through checkpointed Vertex artwork triage.

Each worker calls the existing source-bound visual reviewer. Failed workers can
resume from their per-row checkpoint; final merge rejects missing or extra IDs.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scripts.relationship_pilot import read_jsonl, write_jsonl
from scripts.vertex_relationship_artwork_triage import FIELDS, PROMPT_VERSION
from scripts.vertex_concept_review import MODEL


def _batch(queue: list[dict], work: Path, size: int) -> list[tuple[int, Path]]:
    if size < 1:
        raise ValueError("chunk size must be positive")
    work.mkdir(parents=True, exist_ok=True)
    chunks = []
    for number, start in enumerate(range(0, len(queue), size)):
        path = work / f"chunk-{number:03d}.jsonl"
        subset = queue[start:start + size]
        if path.exists():
            if read_jsonl(path) != subset:
                raise ValueError(f"frozen chunk changed: {path}")
        else:
            write_jsonl(path, subset)
        chunks.append((number, path))
    return chunks


def _run_chunk(number: int, path: Path, args: argparse.Namespace) -> tuple[int, int]:
    lock_path = args.work / f"chunk-{number:03d}.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _run_chunk_locked(number, path, args)


def _run_chunk_locked(number: int, path: Path,
                      args: argparse.Namespace) -> tuple[int, int]:
    prefix = args.work / f"chunk-{number:03d}"
    result, audit = Path(str(prefix) + "-results.csv"), Path(str(prefix) + "-audit.json")
    checkpoint = Path(str(prefix) + "-checkpoint.jsonl")
    log = Path(str(prefix) + "-run.log")
    if result.exists() and audit.exists():
        return number, 0
    command = [sys.executable, "-m", "scripts.vertex_relationship_artwork_triage",
               "--queue", str(path), "--source-queues", str(args.queue),
               "--repo", str(args.repo), "--checkpoint", str(checkpoint),
               "--output", str(result), "--audit", str(audit),
               "--official-jp-repo", str(args.official_jp_repo),
               "--official-jp-revision", args.official_jp_revision]
    if args.discover_en_assets:
        command.append("--discover-en-assets")
    if args.prior_artwork_audit:
        command.extend(["--prior-artwork-audit", str(args.prior_artwork_audit)])
    if args.curated_assets:
        command.extend(["--curated-assets", str(args.curated_assets)])
    for attempt in range(3):
        # A previous run may have completed the CSV write and failed before
        # committing its audit. The row checkpoint is the authoritative resume.
        if result.exists() != audit.exists():
            result.unlink(missing_ok=True)
            audit.unlink(missing_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"attempt {attempt + 1}\n")
            completed = subprocess.run(command, stdout=handle, stderr=handle,
                                       check=False)
        if completed.returncode == 0:
            return number, attempt + 1
    raise RuntimeError(f"visual chunk {number} failed after three attempts; see {log}")


def _merge(queue: list[dict], chunks: list[tuple[int, Path]], work: Path,
           output: Path, audit_path: Path) -> dict:
    if output.exists() or audit_path.exists():
        raise FileExistsError("merged visual outputs must be new")
    rows, details = {}, {}
    batch_meta = None
    for number, path in chunks:
        prefix = work / f"chunk-{number:03d}"
        result = Path(str(prefix) + "-results.csv")
        audit = json.loads(Path(str(prefix) + "-audit.json").read_text())
        meta = {key: audit.get(key) for key in (
            "model", "project", "location", "prompt_version", "pinned_revision")}
        if (meta["model"] != MODEL or meta["prompt_version"] != PROMPT_VERSION
                or not meta["pinned_revision"]):
            raise ValueError(f"visual chunk {number} has unexpected model or source version")
        if batch_meta is None:
            batch_meta = meta
        elif meta != batch_meta:
            raise ValueError("visual chunks used different model or source versions")
        with result.open(encoding="utf-8", newline="") as handle:
            batch_rows = list(csv.DictReader(handle))
        expected = {row["candidate_id"] for row in read_jsonl(path)}
        if (audit.get("candidate_rows") != len(expected)
                or {row["candidate_id"] for row in batch_rows} != expected
                or {row["candidate_id"] for row in audit["rows"]} != expected
                or len(batch_rows) != len(expected) or len(audit["rows"]) != len(expected)):
            raise ValueError(f"visual chunk {number} has missing or extra IDs")
        for row in batch_rows:
            if row["candidate_id"] in rows:
                raise ValueError("duplicate visual verdict")
            rows[row["candidate_id"]] = row
        for row in audit["rows"]:
            details[row["candidate_id"]] = row
    expected = {row["candidate_id"] for row in queue}
    if set(rows) != expected or set(details) != expected:
        raise ValueError("merged verdicts differ from frozen queue")
    for row in queue:
        cid = row["candidate_id"]
        if (rows[cid]["source_snapshot_sha256"] != row["source_snapshot_sha256"]
                or details[cid]["source_snapshot_sha256"] != row["source_snapshot_sha256"]):
            raise ValueError("visual verdict source snapshot drifted")
        verdict = rows[cid]
        if verdict["artwork_decision"] in {"same", "different"}:
            if (verdict["ja_image_status"] != "included"
                    or verdict["en_image_status"] != "included"
                    or details[cid].get("model_version") != MODEL
                    or not details[cid].get("response_sha256")):
                raise ValueError("visual verdict lacks source-bound model evidence")
            if verdict["en_image_identity"] != "match":
                details[cid]["identity_gate_original_decision"] = verdict["artwork_decision"]
                details[cid]["identity_gate"] = "blocked_english_image_identity"
                verdict["artwork_decision"] = "uncertain"
                verdict["evidence_limits"] += (
                    " English card identity was not visually confirmed; artwork verdict withheld.")
    ordered_rows = [rows[row["candidate_id"]] for row in queue]
    ordered_details = [details[row["candidate_id"]] for row in queue]
    report = {**batch_meta, "model": MODEL, "prompt_version": PROMPT_VERSION,
              "scope": "AI artwork triage only; no verified printing or price equivalence",
              "queue_sha256": hashlib.sha256(json.dumps(
                  queue, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
              "candidate_rows": len(queue),
              "decisions": dict(sorted(Counter(
                  row["artwork_decision"] for row in ordered_rows).items())),
              "both_images_included": sum(
                  row["ja_image_status"] == "included" and
                  row["en_image_status"] == "included" for row in ordered_rows),
              "rows": ordered_details}
    with output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(ordered_rows)
    audit_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--official-jp-repo", type=Path, required=True)
    parser.add_argument("--official-jp-revision", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--discover-en-assets", action="store_true")
    parser.add_argument("--prior-artwork-audit", type=Path,
                        help="reuse previously audited images only when their hashes still match")
    parser.add_argument("--curated-assets", type=Path,
                        help="source-bound image candidates with content hashes")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError("workers must be positive")
    queue = read_jsonl(args.queue)
    chunks = _batch(queue, args.work, args.chunk_size)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(_run_chunk, number, path, args)
                   for number, path in chunks]
        for future in as_completed(futures):
            number, attempts = future.result()
            print(f"chunk {number + 1}/{len(chunks)} complete ({attempts} run attempts)",
                  flush=True)
    report = _merge(queue, chunks, args.work, args.output, args.audit)
    print(json.dumps({key: report[key] for key in
                      ("candidate_rows", "decisions", "both_images_included")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
