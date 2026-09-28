# AI-first listing review

AI may handle routine exact-card, printing and grade review. Human review handles disagreement, incomplete evidence and a **random audit of AI approvals**. Auditing only uncertain items would miss confident AI mistakes. This process is separate from card authenticity and condition grading.

## Current implementation

`scripts.ai_review_triage` accepts previously obtained reviews from at least two distinct model families. It **does not call models, download images or promote listings into the ask index**. Model IDs are assertions in the input, not cryptographic provider attestations. Production model calls and photo use require the marketplace's specific written permission, approved storage/retention, and provider response evidence.

Start with the [frozen listing sample](BLIND_LISTING_BENCHMARK.md). If authorized images were inspected, each input row includes `image_urls` and an aligned list of SHA-256 hashes of the actual image bytes in `image_sha256`. A changing URL is not sufficient evidence. Each AI response must include:

```json
{
  "item_key": "source:native_id",
  "model_family": "independent-family-a",
  "listing_sha256": "sha256 of the frozen listing fields",
  "image_sha256": ["sha256 of each inspected image"],
  "confidence": {"identity": 0.99, "printing": 0.98, "grade": 0.97},
  "label": {
    "single_card": "yes", "language": "ja", "set_code": "SV2A",
    "number": "173/165", "variant": "standard",
    "grade_status": "raw", "grade_company": null, "grade_value": null,
    "image_seen": true, "evidence_notes": "Photo 1 shows the printed number and finish."
  }
}
```

The helper `listing_sha256(item)` computes the listing fingerprint. Each family gets the frozen title, description and authorized image evidence **independently**, without the other model's answer or matcher prediction. Self-reported confidence is used only to route work; the human audit measures observed accuracy.

```
python3 -m scripts.ai_review_triage triage \
  --sample-dir ../../work/benchmark/representative-v1 \
  --ai-reviews ../../work/benchmark/ai-reviews.jsonl \
  --out-dir ../../work/benchmark/ai-triage-v1 \
  --min-confidence 0.95 --audit-size 300 --seed 20260928 \
  --media-ai-rights-ref 'source-specific photo AI permission record'
```

All model families must agree on single-card status, language, set, number, exact printing and raw/graded company/value. Approval also requires a hashed image snapshot, specific evidence notes and confidence above the routing threshold for every field. Missing reviews, disagreement, unknown identity/printing/grade, missing photo evidence and low confidence go to `human_queue.jsonl`. A random subset of the AI approvals goes into the **same queue**, without its AI answer or audit designation. The remaining approvals stay `pending_audit`; no offer is imported by this tool.

Run the existing [local human workbench](catalog/review-workbench.md) against `human_queue.jsonl` and export gold labels. The audit command compares only the random AI-approval subset; reviews of escalations can be used for individual resolution in a later authorized ingestion flow.

```
python3 -m scripts.ai_review_triage audit \
  --sample-dir ../../work/benchmark/representative-v1 \
  --triage-dir ../../work/benchmark/ai-triage-v1 \
  --human-gold ../../work/benchmark/ai-triage-v1/human_gold.jsonl \
  --output ../../work/benchmark/ai-triage-v1/audit_report.json
```

The first auto-join gate still needs a complete representative review of at least 300 **randomly audited AI approvals**, a joint printing+grade Wilson 95% lower bound of at least 0.98, and zero accepted multi-card listings. This is an initial proposed risk threshold, not an observed result. If it fails, keep AI approvals review-only and diagnose errors. Once an independently verified baseline passes for a source and printing segment, continue random high-confidence audits alongside uncertainty escalations and stop automatic joining if drift appears. The current tool does not implement that later release or drift controller.

There are no current authorized listing photos or model responses in this repository. Synthetic tests verify routing and audit calculations only.
