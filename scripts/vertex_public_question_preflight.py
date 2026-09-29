"""Gemini source-fidelity review before a public-question cohort is frozen.

The model sees a researcher-transcribed original-post context, short source
anchor, and candidate paraphrase. It does not fetch the URL itself. A separate
reviewer must inspect the original page; both reviews remain silver evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts.vertex_concept_review import MODEL, _call_model

PROMPT_VERSION = "public-question-source-fidelity-gemini-v1"
STATUSES = {"faithful", "inferred_case", "mismatch", "unverifiable"}


def _request(candidate: dict, evidence: dict) -> tuple[dict, str]:
    prompt = f"""Independently assess whether a short Pokémon-question paraphrase
preserves the ORIGINAL POSTER's actual question. Ignore all replies and do not
answer the card question. You cannot fetch the URL yourself; the original-post
context below was transcribed by a researcher, so judge only that supplied
context and mark unverifiable if it lacks enough support. Check actor, object,
explicit goal, and whether media is truly available in this review.

Return JSON with exactly status and reason. Status is one of:
faithful (same actor/object/explicit goal, condensed without material changes),
inferred_case (plausible new question inferred from a post, not explicitly asked),
mismatch (actor, object, goal, or available media materially changed),
unverifiable (source text supplied is too thin to check).
Do not use an old price as current market evidence.

URL: {candidate['source_url']}
Original-post locator: {evidence['post_locator']}
Evidence method: {evidence['verification_method']}
Short original quote: {evidence['anchor']}
Transcribed original-post context: {evidence['source_context']}
Candidate question: {candidate['question']}
Candidate media_state: {candidate['media_state']}
"""
    request = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json",
                                    "temperature": 0, "maxOutputTokens": 2000}}
    return request, hashlib.sha256(prompt.encode()).hexdigest()


def run(source: Path, evidence_path: Path, checkpoint: Path,
        project: str, location: str) -> dict:
    candidates = read_jsonl(source)
    evidence = {row["id"]: row for row in read_jsonl(evidence_path)}
    if len(evidence) != len(candidates) or set(evidence) != {row["id"] for row in candidates}:
        raise ValueError("source evidence does not cover candidates")
    source_sha, evidence_sha = sha_file(source), sha_file(evidence_path)
    existing = read_jsonl(checkpoint) if checkpoint.exists() else []
    by_id = {row["id"]: row for row in existing}
    if len(by_id) != len(existing) or set(by_id) - set(evidence):
        raise ValueError("invalid Gemini checkpoint")
    for row in existing:
        if (row.get("model_family") != "google" or
                row.get("source_sha256") != source_sha or
                row.get("evidence_sha256") != evidence_sha):
            raise ValueError("Gemini checkpoint input changed")
    pending = [row for row in candidates if row["id"] not in by_id]
    token = (subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                     text=True, stderr=subprocess.DEVNULL).strip()
             if pending else None)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint.open("a", encoding="utf-8") as handle:
        for candidate in pending:
            request, prompt_sha = _request(candidate, evidence[candidate["id"]])
            response = _call_model(project, location, token, request)
            choices = response.get("candidates") or []
            if not choices or choices[0].get("finishReason") != "STOP":
                raise ValueError(f"incomplete Gemini response for {candidate['id']}")
            raw = "".join(part.get("text", "") for part in
                          choices[0].get("content", {}).get("parts", []))
            answer = json.loads(raw)
            if (not isinstance(answer, dict) or set(answer) != {"status", "reason"}
                    or answer["status"] not in STATUSES
                    or not isinstance(answer["reason"], str) or not answer["reason"].strip()):
                raise ValueError(f"invalid Gemini answer for {candidate['id']}")
            row = {"id": candidate["id"], "model_family": "google",
                   "source_sha256": source_sha, "evidence_sha256": evidence_sha,
                   "status": answer["status"], "reason": answer["reason"],
                   "requested_model": MODEL,
                   "model_version": response.get("modelVersion"),
                   "prompt_version": PROMPT_VERSION, "prompt_sha256": prompt_sha,
                   "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                   "usage_metadata": response.get("usageMetadata")}
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
    rows = read_jsonl(checkpoint)
    return {"questions": len(candidates), "reviewed": len(rows),
            "statuses": {status: sum(row["status"] == status for row in rows)
                         for status in sorted(STATUSES)}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="global")
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.evidence, args.checkpoint,
                         args.project, args.location), ensure_ascii=False))


if __name__ == "__main__":
    main()
