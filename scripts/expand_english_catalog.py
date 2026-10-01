"""Add source-declared English versions without replacing existing identities.

The raw extraction is compared with the frozen baseline before import. New
versions remain disabled for offer matching; API families are retained as
unresolved references rather than silently merged into physical printings.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from pokemon_index import core
from scripts import build_tcgdex_international, build_discovery_facets, build_card_classifications


def compact(value):
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def verify_source(repo, revision, series):
    paths = ["LICENSE"] + ["data/" + name for name in series] + ["data/" + name + ".ts" for name in series]
    tree = subprocess.check_output(["git", "ls-tree", "-rz", revision, "--", *paths], cwd=repo)
    blobs = {}
    for entry in tree.split(b"\0"):
        if entry:
            metadata, path = entry.split(b"\t", 1)
            if metadata.split()[1] == b"blob":
                blobs[path.decode()] = metadata.split()[2].decode()
    local = {"LICENSE"}
    for name in series:
        local.add("data/" + name + ".ts")
        local.update(p.relative_to(repo).as_posix() for p in (repo / "data" / name).rglob("*") if p.is_file())
    if local != set(blobs):
        raise ValueError("source files differ from pinned Git tree")
    for path, expected in blobs.items():
        raw = (repo / path).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if actual != expected:
            raise ValueError("source Git blob changed: " + path)
    return len(blobs)


def classify(rows, db):
    """Hold source disagreements and never modify a baseline record."""
    existing = {r["card_id"]: dict(r) for r in db.execute("SELECT * FROM card WHERE language='en'")}
    groups = {}
    for row in existing.values():
        groups.setdefault((row["set_code"], row["collector_number"]), []).append(row)
    accepted, holds, skipped = [], [], []
    ids = set()
    for row in rows:
        cid = core.card_id(row["language"], row["set_code"], row["collector_number"], row["variant"])
        if cid in ids:
            raise ValueError("duplicate expansion identity")
        ids.add(cid)
        if cid in existing:
            skipped.append(cid)
            continue
        neighbors = groups.get((row["set_code"].upper(), core.normalize_collector_number(row["collector_number"])), [])
        if neighbors and any(compact(n["name"]) != compact(row["name"]) for n in neighbors):
            holds.append({"candidate": row, "existing_card_ids": [n["card_id"] for n in neighbors],
                          "reason": "same coordinates have conflicting names"})
            continue
        accepted.append({**row, "match_eligible": False, "display_allowed": False,
                         "attributes": {"source_declared_variant": row["variant"],
                                        "physical_printing_verified": False,
                                        "expansion_batch": "english-history-v1"}})
    return accepted, holds, skipped


def build(repo, revision, series, baseline, output):
    if output.exists():
        raise FileExistsError(output)
    verified_blobs = verify_source(repo, revision, series)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as temporary:
        temp = Path(temporary)
        raw, sets = temp / "cards.jsonl", temp / "sets.jsonl"
        extraction = build_tcgdex_international.build(
            repo, revision, series, raw, sets, output / "source-audit.json", output / "source-gaps.jsonl")
        db = core.connect(baseline, readonly=True)
        try:
            rows, holds, skipped = classify([json.loads(line) for line in raw.read_text().splitlines()], db)
            old_sets = {r[0] for r in db.execute("SELECT set_code FROM catalog_set_localized WHERE language='en'")}
            new_sets = [json.loads(line) for line in sets.read_text().splitlines()
                        if json.loads(line)["set_code"].upper() not in old_sets]
            baseline_groups = {(r[0], r[1]) for r in db.execute(
                "SELECT DISTINCT set_code,collector_number FROM card WHERE language='en'")}
            baseline_count = db.execute("SELECT COUNT(*) FROM card").fetchone()[0]
        finally:
            db.close()
        accepted = temp / "accepted.jsonl"
        accepted.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        with (output / "cards.jsonl.gz").open("xb") as stream:
            with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as archive:
                archive.write(accepted.read_bytes())
        for name, records in (("sets.jsonl", new_sets), ("conflict-holds.jsonl", holds)):
            (output / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        facets = build_discovery_facets.build(repo, revision, [accepted], output / "facets.jsonl.gz", output / "facets-audit.json")
        categories = build_card_classifications.build(repo, revision, [accepted], output / "classifications.jsonl.gz", output / "classifications-audit.json")
    new_groups = {(r["set_code"].upper(), core.normalize_collector_number(r["collector_number"])) for r in rows}
    report = {"schema": "pokemon.catalog-expansion.v1", "revision": revision,
              "verified_git_blobs": verified_blobs,
              "baseline_printings": baseline_count,
              "source": "https://github.com/tcgdex/cards-database/tree/" + revision,
              "series": sorted(series), "source_extraction": extraction,
              "added_source_version_records": len(rows), "added_set_metadata": len(new_sets),
              "card_bearing_sets_in_batch": len({r["set_code"].upper() for r in rows}),
              "unique_set_number_groups_in_batch": len(new_groups),
              "new_set_number_groups": len(new_groups - baseline_groups),
              "previously_indexed_groups_enriched": len(new_groups & baseline_groups),
              "conflict_holds": len(holds), "existing_identities_skipped": len(skipped),
              "added_match_eligible": 0, "added_display_approved": 0,
              "facets": {k: v for k, v in facets.items() if k != "facet_parse_gaps"},
              "classifications": {k: v for k, v in categories.items() if k != "parse_gaps"},
              "scope": "internal source-declared versions; not verified physical copies, counterparts or prices",
              "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir())}}
    (output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--series", action="append", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.repo.resolve(), args.revision, args.series, args.baseline, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
