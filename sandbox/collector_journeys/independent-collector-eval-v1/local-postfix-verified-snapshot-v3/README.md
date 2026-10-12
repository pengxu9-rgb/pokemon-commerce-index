# Verified-snapshot local replay

These are the final local checks after the bounded usefulness fixes, using the byte-verified ec7104e CI catalog snapshot. They do not claim a new manifest build or exact-commit CI result.

The unchanged 30-case cohort meets all mechanical constraints; actual Python HTTP → Node executes all 49 prefixes (47 accepted responses and two expected authority rejections) with exact direct-response/session equivalence. Runtime, catalog, frozen fixtures and original CI reports remain unchanged during the run. This is not a usefulness score or human/held-out evaluation.

Full raw JSON reports are gzip-compressed without content changes. Verify the compressed and decoded SHA-256 values in receipt-manifest.json. Read with `gzip -dc <report.json.gz>`. Compact per-case outcomes and the original-CI comparison are uncompressed. Earlier local runs remain historical; the final CI for the published source is the release gate.
