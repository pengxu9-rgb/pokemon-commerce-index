CREATE VIEW IF NOT EXISTS active_card_metadata_evidence AS
SELECT e.* FROM card_metadata_evidence e
JOIN card c ON c.card_id=e.card_id
JOIN card_reference r ON r.set_code=c.set_code AND r.collector_number=c.collector_number
WHERE NOT EXISTS (SELECT 1 FROM card_metadata_evidence later
    WHERE later.card_id=e.card_id AND later.revision>e.revision)
AND c.language=json_extract(e.record_json,'$.identity.language')
AND c.set_code=json_extract(e.record_json,'$.identity.set_code')
AND c.collector_number=json_extract(e.record_json,'$.identity.collector_number')
AND c.variant=json_extract(e.record_json,'$.identity.variant')
AND c.name=json_extract(e.record_json,'$.identity.name')
AND c.rarity IS json_extract(e.record_json,'$.identity.rarity')
AND c.provenance=json_extract(e.record_json,'$.identity.provenance')
AND r.source=json_extract(e.record_json,'$.reference.source')
AND r.native_id=json_extract(e.record_json,'$.reference.native_id')
AND r.name=json_extract(e.record_json,'$.reference.name')
AND r.provenance=json_extract(e.record_json,'$.reference.provenance')
AND (SELECT COUNT(*) FROM card_reference all_refs
    WHERE all_refs.set_code=c.set_code AND all_refs.collector_number=c.collector_number)=1;

CREATE VIEW IF NOT EXISTS discovery_card_facet AS
SELECT f.* FROM card_facet f WHERE NOT EXISTS (
    SELECT 1 FROM active_card_metadata_evidence e WHERE e.card_id=f.card_id
    AND (json_extract(e.record_json,'$.official.page_kind')='numbered_parts'
      OR (json_extract(e.record_json,'$.official.page_kind')='single_number'
      AND ((f.facet_type='illustrator' AND json_array_length(e.record_json,'$.official.illustrators')>0)
        OR (f.facet_type='dex_id' AND json_extract(e.record_json,'$.official.dex_id') IS NOT NULL)))))
UNION ALL
SELECT e.card_id, 'illustrator', j.value,
       e.evidence_id, json_extract(e.record_json,'$.official.url')
FROM active_card_metadata_evidence e, json_each(e.record_json,'$.official.illustrators') j
WHERE json_extract(e.record_json,'$.official.page_kind')='single_number'
AND NOT EXISTS (SELECT 1 FROM card_facet seed WHERE seed.card_id=e.card_id
    AND seed.facet_type='illustrator' AND NOT EXISTS
      (SELECT 1 FROM json_each(e.record_json,'$.official.illustrators') credit WHERE credit.value=seed.value))
UNION ALL
SELECT e.card_id, 'dex_id', CAST(json_extract(e.record_json,'$.official.dex_id') AS TEXT),
       e.evidence_id, json_extract(e.record_json,'$.official.url')
FROM active_card_metadata_evidence e
WHERE json_extract(e.record_json,'$.official.page_kind')='single_number'
AND json_extract(e.record_json,'$.official.dex_id') IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM card_facet seed WHERE seed.card_id=e.card_id
    AND seed.facet_type='dex_id' AND seed.value<>CAST(json_extract(e.record_json,'$.official.dex_id') AS TEXT));
