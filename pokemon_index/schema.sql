PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_policy (
  source TEXT PRIMARY KEY,
  rights_reference TEXT NOT NULL,
  ingest_allowed INTEGER NOT NULL CHECK (ingest_allowed IN (0, 1)),
  display_allowed INTEGER NOT NULL CHECK (display_allowed IN (0, 1)),
  cross_source_use_allowed INTEGER NOT NULL CHECK (cross_source_use_allowed IN (0, 1)),
  seller_analytics_allowed INTEGER NOT NULL CHECK (seller_analytics_allowed IN (0, 1)),
  media_ai_allowed INTEGER NOT NULL DEFAULT 0 CHECK (media_ai_allowed IN (0, 1)),
  cross_region_use_allowed INTEGER NOT NULL DEFAULT 0 CHECK (cross_region_use_allowed IN (0, 1)),
  retention_days INTEGER NOT NULL CHECK (retention_days > 0),
  listing_ttl_hours INTEGER NOT NULL CHECK (listing_ttl_hours > 0),
  expires_at TEXT
);

CREATE TABLE IF NOT EXISTS card (
  card_id TEXT PRIMARY KEY,
  language TEXT NOT NULL,
  set_code TEXT NOT NULL,
  collector_number TEXT NOT NULL,
  variant TEXT NOT NULL DEFAULT 'standard',
  name TEXT NOT NULL,
  rarity TEXT,
  provenance TEXT NOT NULL,
  rights_reference TEXT NOT NULL,
  display_allowed INTEGER NOT NULL CHECK (display_allowed IN (0, 1)),
  match_eligible INTEGER NOT NULL DEFAULT 1 CHECK (match_eligible IN (0, 1)),
  attributes_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(language, set_code, collector_number, variant)
);

-- Source snapshots remain immutable; official-page corrections overlay them.
CREATE TABLE IF NOT EXISTS card_identity_exception (
  card_id TEXT PRIMARY KEY REFERENCES card(card_id),
  original_name TEXT NOT NULL,
  source_provenance TEXT NOT NULL,
  corrected_name TEXT NOT NULL,
  corrected_rarity TEXT,
  official_url TEXT NOT NULL,
  official_page_sha256 TEXT NOT NULL,
  reason TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_set (
  set_code TEXT PRIMARY KEY,
  name_ja TEXT,
  release_date_ja TEXT,
  official_card_count INTEGER NOT NULL CHECK (official_card_count >= 0),
  provenance TEXT NOT NULL,
  rights_reference TEXT NOT NULL,
  display_allowed INTEGER NOT NULL CHECK (display_allowed IN (0, 1))
);

CREATE TABLE IF NOT EXISTS catalog_set_localized (
  language TEXT NOT NULL,
  set_code TEXT NOT NULL,
  name TEXT,
  release_date TEXT,
  official_card_count INTEGER NOT NULL CHECK (official_card_count >= 0),
  provenance TEXT NOT NULL,
  rights_reference TEXT NOT NULL,
  display_allowed INTEGER NOT NULL CHECK (display_allowed IN (0, 1)),
  PRIMARY KEY(language, set_code)
);

CREATE TABLE IF NOT EXISTS card_reference (
  source TEXT NOT NULL,
  native_id TEXT NOT NULL,
  set_code TEXT,
  collector_number TEXT,
  name TEXT NOT NULL,
  rarity TEXT,
  attributes_json TEXT NOT NULL,
  provenance TEXT NOT NULL,
  rights_reference TEXT NOT NULL,
  display_allowed INTEGER NOT NULL CHECK (display_allowed IN (0, 1)),
  PRIMARY KEY(source, native_id)
);

-- Source-backed discovery facets describe a character or artist, never a
-- printing counterpart or a market price.
CREATE TABLE IF NOT EXISTS card_facet (
  card_id TEXT NOT NULL REFERENCES card(card_id),
  facet_type TEXT NOT NULL CHECK (facet_type IN ('dex_id', 'illustrator')),
  value TEXT NOT NULL,
  provenance TEXT NOT NULL,
  rights_reference TEXT NOT NULL,
  PRIMARY KEY(card_id, facet_type, value)
);

-- Source classifications are retrieval signals, not printing relationships.
CREATE TABLE IF NOT EXISTS card_classification (
  card_id TEXT PRIMARY KEY REFERENCES card(card_id),
  category TEXT NOT NULL CHECK (category IN ('Pokemon', 'Trainer', 'Energy')),
  subtype TEXT,
  provenance TEXT NOT NULL,
  rights_reference TEXT NOT NULL
);

-- A curated bilingual name concept connects words, not physical printings.
-- Revisions are append-only so a withdrawn translation ceases retrieval.
CREATE TABLE IF NOT EXISTS concept_review_event (
  event_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL,
  review_revision INTEGER NOT NULL CHECK (review_revision > 0),
  source_snapshot_sha256 TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('approve', 'reject', 'uncertain')),
  reviewer TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
  record_json TEXT NOT NULL,
  UNIQUE(proposal_id, review_revision)
);

CREATE TABLE IF NOT EXISTS bilingual_concept_revision (
  concept_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  category TEXT NOT NULL CHECK (category IN ('Pokemon', 'Trainer', 'Energy')),
  name_ja TEXT NOT NULL,
  name_en TEXT NOT NULL,
  source_ja TEXT NOT NULL,
  source_en TEXT NOT NULL,
  rights_reference TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('approved', 'withdrawn')),
  review_event_id TEXT REFERENCES concept_review_event(event_id),
  PRIMARY KEY(concept_id, revision)
);

-- Reviewed claims connect printings without implying that their prices are interchangeable.
-- Assertions are append-only; the latest assertion for an edge is its current review state.
CREATE TABLE IF NOT EXISTS card_relationship_assertion (
  assertion_id TEXT PRIMARY KEY,
  left_card_id TEXT NOT NULL REFERENCES card(card_id),
  right_card_id TEXT NOT NULL REFERENCES card(card_id),
  relation_type TEXT NOT NULL CHECK (relation_type IN
    ('localization_counterpart', 'same_artwork', 'collecting_alternative')),
  review_status TEXT NOT NULL CHECK (review_status IN ('proposed', 'verified', 'rejected')),
  evidence_ref TEXT NOT NULL,
  rights_reference TEXT NOT NULL,
  asserted_by TEXT NOT NULL,
  reviewer TEXT,
  asserted_at TEXT NOT NULL,
  CHECK (left_card_id < right_card_id)
);

-- Store structured purchase intent; no conversation transcript or marketplace claim is inferred.
CREATE TABLE IF NOT EXISTS exploration_session (
  session_id TEXT PRIMARY KEY,
  owner_key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('exploring', 'targeted', 'paused')),
  constraints_json TEXT NOT NULL,
  shortlist_json TEXT NOT NULL,
  target_card_id TEXT REFERENCES card(card_id),
  version INTEGER NOT NULL CHECK (version > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exploration_revision (
  session_id TEXT NOT NULL REFERENCES exploration_session(session_id),
  version INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY(session_id, version)
);

CREATE TABLE IF NOT EXISTS priceable_unit (
  unit_id TEXT PRIMARY KEY,
  card_id TEXT NOT NULL REFERENCES card(card_id),
  grade_company TEXT NOT NULL,
  grade_value TEXT NOT NULL,
  condition_bucket TEXT NOT NULL,
  UNIQUE(card_id, grade_company, grade_value, condition_bucket)
);

CREATE TABLE IF NOT EXISTS listing (
  source TEXT NOT NULL REFERENCES source_policy(source),
  native_id TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  seller_native_id TEXT,
  unit_id TEXT REFERENCES priceable_unit(unit_id),
  resolution_method TEXT NOT NULL CHECK (resolution_method IN ('exact', 'explicit', 'unresolved', 'human')),
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  current_status TEXT NOT NULL,
  current_price_minor INTEGER,
  currency TEXT NOT NULL,
  PRIMARY KEY(source, native_id)
);

CREATE TABLE IF NOT EXISTS observation (
  source TEXT NOT NULL,
  native_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  seller_native_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('on_sale', 'trading', 'sold_out', 'gone')),
  price_minor INTEGER CHECK (price_minor IS NULL OR price_minor >= 0),
  currency TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  poll_reason TEXT NOT NULL CHECK (poll_reason IN ('discovery', 'tracking', 'panel', 'auction_end')),
  native_created TEXT,
  native_updated TEXT,
  PRIMARY KEY(source, native_id, observed_at),
  FOREIGN KEY(source, native_id) REFERENCES listing(source, native_id)
);

CREATE TABLE IF NOT EXISTS raw_item_blob (
  source TEXT NOT NULL REFERENCES source_policy(source),
  native_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(source, native_id, observed_at)
);

CREATE TABLE IF NOT EXISTS resolution_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  native_id TEXT NOT NULL,
  unit_id TEXT REFERENCES priceable_unit(unit_id),
  method TEXT NOT NULL CHECK (method IN ('exact', 'explicit', 'unresolved', 'human')),
  rule_version TEXT NOT NULL,
  resolved_at TEXT NOT NULL,
  reviewer TEXT,
  reason TEXT,
  FOREIGN KEY(source, native_id) REFERENCES listing(source, native_id)
);

CREATE TABLE IF NOT EXISTS landed_quote (
  source TEXT NOT NULL,
  native_id TEXT NOT NULL,
  destination TEXT NOT NULL,
  currency TEXT NOT NULL,
  components_json TEXT NOT NULL,
  total_minor INTEGER NOT NULL CHECK (total_minor >= 0),
  quoted_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  assumptions_json TEXT NOT NULL,
  PRIMARY KEY(source, native_id, destination, quoted_at),
  FOREIGN KEY(source, native_id) REFERENCES listing(source, native_id)
);

-- Image bytes are not stored. Every AI finding binds to a specific listing
-- observation and source-authorized photo references and hashes.
CREATE TABLE IF NOT EXISTS offer_media_snapshot (
  source TEXT NOT NULL,
  native_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  front_ref TEXT NOT NULL,
  front_sha256 TEXT NOT NULL,
  back_ref TEXT,
  back_sha256 TEXT,
  rights_reference TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  PRIMARY KEY(source, native_id, observed_at),
  FOREIGN KEY(source, native_id, observed_at)
    REFERENCES observation(source, native_id, observed_at)
);

CREATE TABLE IF NOT EXISTS offer_visual_review (
  review_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  native_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  card_id TEXT NOT NULL REFERENCES card(card_id),
  model_family TEXT NOT NULL,
  model_version TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
  front_sha256 TEXT NOT NULL,
  back_sha256 TEXT,
  identity_decision TEXT NOT NULL CHECK (identity_decision IN ('match', 'mismatch', 'uncertain')),
  observed_finish TEXT,
  finish_decision TEXT NOT NULL CHECK (finish_decision IN ('match', 'mismatch', 'uncertain')),
  condition_bucket TEXT,
  condition_decision TEXT NOT NULL CHECK (condition_decision IN ('assessed', 'uncertain')),
  evidence_ref TEXT NOT NULL,
  rationale TEXT NOT NULL,
  FOREIGN KEY(source, native_id, observed_at)
    REFERENCES offer_media_snapshot(source, native_id, observed_at)
);

CREATE TABLE IF NOT EXISTS verified_sale (
  source TEXT NOT NULL,
  native_id TEXT NOT NULL,
  settled_at TEXT NOT NULL,
  paid_minor INTEGER NOT NULL CHECK (paid_minor >= 0),
  currency TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  PRIMARY KEY(source, native_id, settled_at),
  FOREIGN KEY(source, native_id) REFERENCES listing(source, native_id)
);

CREATE INDEX IF NOT EXISTS idx_card_search ON card(language, set_code, collector_number);
CREATE INDEX IF NOT EXISTS idx_card_number_set ON card(collector_number, set_code);
CREATE INDEX IF NOT EXISTS idx_card_reference_identity ON card_reference(set_code, collector_number);
CREATE INDEX IF NOT EXISTS idx_card_facet_lookup_nocase ON card_facet(facet_type, value COLLATE NOCASE, card_id);
CREATE INDEX IF NOT EXISTS idx_card_relationship_pair ON card_relationship_assertion(left_card_id, right_card_id, relation_type, asserted_at);
CREATE INDEX IF NOT EXISTS idx_card_relationship_reverse ON card_relationship_assertion(right_card_id, left_card_id, relation_type, asserted_at);
CREATE INDEX IF NOT EXISTS idx_card_facet_lookup ON card_facet(facet_type, value, card_id);
CREATE INDEX IF NOT EXISTS idx_exploration_owner ON exploration_session(owner_key, updated_at);
CREATE INDEX IF NOT EXISTS idx_listing_unit ON listing(unit_id, current_status);
CREATE INDEX IF NOT EXISTS idx_observation_time ON observation(observed_at);
CREATE INDEX IF NOT EXISTS idx_raw_item_time ON raw_item_blob(source, observed_at);
CREATE INDEX IF NOT EXISTS idx_resolution_item ON resolution_record(source, native_id, resolved_at);
CREATE INDEX IF NOT EXISTS idx_quote_expiry ON landed_quote(expires_at);
CREATE INDEX IF NOT EXISTS idx_offer_visual_snapshot ON offer_visual_review(source, native_id, observed_at, model_family, reviewed_at);
