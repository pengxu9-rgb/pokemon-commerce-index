"""Rebuild the private catalog from one ordered, hash-checked manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from contextlib import closing
from pathlib import Path

from pokemon_index import core, discovery_graph, number_conflicts, supported_catalog,collector_evidence,card_metadata,coordinate_family,printing_evidence,source_corrections,number_evidence,source_image_facts
from pokemon_index.cli import read_jsonl
from pokemon_index import source_mechanic, catalog_locale, coverage_qualification, product_text,variant_dimension_hold,catalog_locale_indexes

def import_ai_artwork_proposals(db, rows) -> int:
    proposals = list(rows)
    if any(row.get("relation_type") != "same_artwork" or
           row.get("review_status") != "proposed" or
           row.get("asserted_by") != "ai-artwork-review-v1"
           for row in proposals):
        raise ValueError("catalog artwork imports must remain AI proposals")
    return discovery_graph.assert_relationships(db, proposals)


OPERATIONS = {
    "import-catalog-locale-lookup-indexes": catalog_locale_indexes.import_manifest_evidence,
    "import-variant-dimension-holds": variant_dimension_hold.import_manifest_evidence,
    "import-publisher-product-text": product_text.import_manifest_evidence,
    "import-coverage-candidates": coverage_qualification.import_manifest_candidates,
    "import-catalog-locales": catalog_locale.import_manifest_evidence,
    "import-sets": core.import_sets,
    "import-cards": core.import_cards,
    "import-card-identity-exceptions": core.apply_card_identity_exceptions,
    "import-card-rarity-corrections": core.apply_card_rarity_corrections,
    "import-card-number-conflicts": number_conflicts.apply_rules,
    "import-card-references": core.import_card_references,
    "import-card-facets": core.import_card_facets,
    "import-card-classifications": core.import_card_classifications,
    "import-ai-artwork-proposals": import_ai_artwork_proposals,
    "import-release-evidence": supported_catalog.import_releases,
    "import-catalog-vocabulary": supported_catalog.import_vocabulary,
    "import-supported-cards": supported_catalog.import_supported,
    "import-character-families": supported_catalog.import_families,
    "import-concept-review-bundle": core.import_concept_review_bundle,
    "import-collector-evidence": collector_evidence.import_evidence,
    "import-official-card-metadata": card_metadata.import_evidence,
    "import-coordinate-families": coordinate_family.import_evidence,
    "import-release-metadata": supported_catalog.import_release_metadata,
    "import-printing-source-evidence": printing_evidence.import_evidence,
    "import-reviewed-relationships": discovery_graph.assert_relationships,
    "import-source-corrections": source_corrections.import_evidence,
    "import-number-reading-evidence": number_evidence.import_evidence,
    "import-source-image-facts": source_image_facts.import_evidence,
    "import-source-mechanic-bindings": source_mechanic.import_evidence,
}


def build(manifest_path: Path, output: Path) -> dict:
    manifest_path = manifest_path.resolve()
    root = manifest_path.parent
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != "pokemon.catalog-build.v1":
        raise ValueError("unknown catalog build manifest schema")
    steps = manifest.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("catalog manifest has no steps")
    verified = []
    for step in steps:
        if not isinstance(step, dict) or step.get("operation") not in OPERATIONS:
            raise ValueError("catalog manifest contains an unknown operation")
        relative = Path(str(step.get("path", "")))
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file():
            raise ValueError("catalog input path escapes the manifest directory")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != step.get("sha256"):
            raise ValueError(f"catalog input hash changed: {relative}")
        verified.append((step["operation"], path))
    output = output.resolve()
    if output.exists():
        raise FileExistsError("catalog snapshot output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".catalog-build-", suffix=".sqlite3",
                                        dir=output.parent)
    os.close(handle)
    try:
        with closing(core.connect(temporary)) as db:
            core.init_db(db)
            for operation, path in verified:
                if operation == "import-concept-review-bundle":
                    core.import_concept_review_bundle(db, json.loads(path.read_text()))
                else:
                    OPERATIONS[operation](db, read_jsonl(str(path)))
            status = core.catalog_status(db)
            hold_status=variant_dimension_hold.status(db)
            actual = {"printings": status["printings"], "sets": status["sets"],
                      "match_eligible": status["match_eligible"],
                      "display_approved": status["display_approved"],
                      "reference_records": status["reference_records"],
                      "identity_exceptions": db.execute(
                          "SELECT COUNT(*) FROM card_identity_exception").fetchone()[0],
                      "number_conflict_rules": db.execute(
                          "SELECT COUNT(*) FROM card_number_conflict_rule").fetchone()[0],
                      "relationship_assertions": db.execute(
                          "SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0],
                      "verified_relationships": db.execute(
                          "SELECT COUNT(*) FROM card_relationship_assertion WHERE review_status='verified'").fetchone()[0],
                      "ai_artwork_proposals": db.execute(
                          """SELECT COUNT(*) FROM card_relationship_assertion
                          WHERE relation_type='same_artwork' AND review_status='proposed'
                          AND asserted_by='ai-artwork-review-v1'""").fetchone()[0]}
            if "rarity_corrections" in manifest.get("expected", {}):
                actual["rarity_corrections"] = db.execute(
                    "SELECT COUNT(*) FROM card_rarity_correction").fetchone()[0]
            supported = supported_catalog.status(db)
            for key,value in card_metadata.status(db).items():
                if key in manifest.get('expected',{}):
                    actual[key]=value
            for key,value in coordinate_family.status(db).items():
                if key in manifest.get('expected',{}):actual[key]=value
            for key,value in printing_evidence.status(db).items():
                if key in manifest.get('expected',{}):actual[key]=value
            for key,value in source_corrections.status(db).items():
                if key in manifest.get('expected',{}):actual[key]=value
            for key,value in number_evidence.status(db).items():
                if key in manifest.get('expected',{}):actual[key]=value
            for key,value in source_image_facts.status(db).items():
                if key in manifest.get('expected',{}):actual[key]=value
            for key,value in source_mechanic.status(db).items():
                if key in manifest.get('expected',{}):actual[key]=value
            for key,value in coverage_qualification.status(db).items():
                if key in manifest.get('expected',{}):actual[key]=value
            for key,value in {'variant_dimension_hold_events':hold_status['events'],'variant_dimension_held_ids':hold_status['held_legacy_ids']}.items():
                if key in manifest.get('expected',{}):actual[key]=value
            for key,value in product_text.status(db).items():
                if key in manifest.get('expected',{}):actual[key]=value
            for key in ("current_supported_targets", "bilingual_alias_revisions", "concept_review_events",
                        "release_evidence_records", "vocabulary_records", "character_families"):
                if key in manifest.get("expected", {}):
                    actual[key] = supported[key]
            if 'collector_evidence_events' in manifest.get('expected',{}):
                actual['collector_evidence_events']=db.execute('SELECT COUNT(*) FROM catalog_collector_evidence').fetchone()[0]
                for key,value in collector_evidence.status(db).items():
                    if 'collector_'+key in manifest['expected']:actual['collector_'+key]=value
            if actual != manifest.get("expected"):
                raise ValueError(f"catalog build counts differ: {actual}")
            # An operator may finish evidence while a long build is running.
            # Reject that mixed snapshot instead of publishing it under the
            # manifest hash validated before ingestion.
            for step,(_,path) in zip(steps,verified):
                with path.open('rb') as source:
                    if hashlib.file_digest(source,'sha256').hexdigest()!=step['sha256']:
                        raise ValueError('catalog input changed during build: '+step['path'])
            if manifest_path.read_bytes()!=manifest_bytes:
                raise ValueError('catalog manifest changed during build')
        os.replace(temporary, output)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return {"output": str(output), "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "steps": len(steps), **actual}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("catalog-build-manifest-discovery-v1.json"))
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.manifest, args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
