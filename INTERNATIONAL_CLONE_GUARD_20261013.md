# Immutable request clone guard

An independent review after PR #4 merged reproduced a data-consistency gap: replacing the attached SQLite clone could preserve its schema version and read-only flag while changing its facts. Both native and packaged read models accepted that replacement. The PR #4 CI and package receipts are retained, and no image from that package was submitted to Cloud Build.

An active request now installs a scoped SQLite authorizer, rejects attachment replacement and clone writes, and protects the tracked connection's deserialization and authorizer APIs. A forbidden attempt permanently invalidates that request even if its caller catches the error. Cached reads and context exit check the same guard. Cleanup restores the prior authorizer; ordinary mutable imports and native artifact generation outside a request remain supported. This protects the application connection API, and is not a sandbox for hostile Python extensions that deliberately replace base-class setters or private attributes.

Requests with changed facts return the existing `503 catalog_snapshot_changed` response. A fresh admission must recover with complete native response parity. The runtime revision changes to `17f89aeb6bc24088e36103cd9435687a831f622f06630191b8d0902fb4d4f4ad`; older conversations must restart and reconfirm context. Artifacts must be regenerated from each actual finalized database, source policy and engine profile.

All 86 inputs, the original 65-input provenance prefix, existing IDs, 51 logical tables and trading boundaries remain unchanged. No card, artwork, marketplace price, display/purchase grant, frontend, IAM or resource change is included. The next 3,000-record English metadata plan remains unapplied.

The repair requires independent source review, full Python and Node tests, all 3,952 native/materialized/loaded binding checks, exact-source CI, immutable image verification and all 21 actual private staging checks before promotion. Earlier local timing and cloud results do not validate this new runtime. Default staging traffic remains on revision 43 until a candidate passes.

Rollback uses the saved rollout receipt with the unchanged guarded rollback helper. It restores the captured concrete revision percentages only while that rollout owns traffic and refuses to overwrite a later unrelated rollout. Preserve all tags and failed reports. A zero-traffic failed candidate requires no default-traffic change.
