CREATE VIEW IF NOT EXISTS active_source_correction_evidence AS
SELECT e.* FROM source_correction_evidence e JOIN printing_source_evidence p
ON p.event_id=json_extract(e.record_json,'$.parent_event_id')
WHERE p.record_json=json_extract(e.record_json,'$.parent_record_json')
AND NOT EXISTS (SELECT 1 FROM printing_source_evidence later WHERE later.subject_kind=p.subject_kind AND later.subject_id=p.subject_id AND later.revision>p.revision)
AND NOT EXISTS (SELECT 1 FROM source_correction_evidence later WHERE later.correction_key=e.correction_key AND later.revision>e.revision)
AND (SELECT COUNT(*) FROM card x WHERE x.language=e.language AND x.set_code=e.set_code AND x.collector_number=e.collector_number)=json_array_length(e.record_json,'$.snapshot.cards')
AND NOT EXISTS (SELECT 1 FROM json_each(e.record_json,'$.snapshot.cards') j WHERE NOT EXISTS (SELECT 1 FROM card x WHERE x.card_id IS json_extract(j.value,'$.card_id') AND x.language IS json_extract(j.value,'$.language') AND x.set_code IS json_extract(j.value,'$.set_code') AND x.collector_number IS json_extract(j.value,'$.collector_number') AND x.variant IS json_extract(j.value,'$.variant') AND x.name IS json_extract(j.value,'$.name') AND x.rarity IS json_extract(j.value,'$.rarity') AND x.provenance IS json_extract(j.value,'$.provenance') AND x.rights_reference IS json_extract(j.value,'$.rights_reference') AND x.display_allowed IS json_extract(j.value,'$.display_allowed') AND x.match_eligible IS json_extract(j.value,'$.match_eligible') AND x.attributes_json IS json_extract(j.value,'$.attributes_json')))
AND (SELECT COUNT(*) FROM card_reference x WHERE x.set_code=e.set_code AND x.collector_number=e.collector_number)=json_array_length(e.record_json,'$.snapshot.references')
AND NOT EXISTS (SELECT 1 FROM json_each(e.record_json,'$.snapshot.references') j WHERE NOT EXISTS (SELECT 1 FROM card_reference x WHERE x.source IS json_extract(j.value,'$.source') AND x.native_id IS json_extract(j.value,'$.native_id') AND x.set_code IS json_extract(j.value,'$.set_code') AND x.collector_number IS json_extract(j.value,'$.collector_number') AND x.name IS json_extract(j.value,'$.name') AND x.rarity IS json_extract(j.value,'$.rarity') AND x.attributes_json IS json_extract(j.value,'$.attributes_json') AND x.provenance IS json_extract(j.value,'$.provenance') AND x.rights_reference IS json_extract(j.value,'$.rights_reference') AND x.display_allowed IS json_extract(j.value,'$.display_allowed')))
AND (SELECT COUNT(*) FROM card c JOIN card_facet x ON x.card_id=c.card_id WHERE c.language=e.language AND c.set_code=e.set_code AND c.collector_number=e.collector_number)=json_array_length(e.record_json,'$.snapshot.facets')
AND NOT EXISTS (SELECT 1 FROM json_each(e.record_json,'$.snapshot.facets') j WHERE NOT EXISTS (SELECT 1 FROM card_facet x WHERE x.card_id IS json_extract(j.value,'$.card_id') AND x.facet_type IS json_extract(j.value,'$.facet_type') AND x.value IS json_extract(j.value,'$.value') AND x.provenance IS json_extract(j.value,'$.provenance') AND x.rights_reference IS json_extract(j.value,'$.rights_reference')))
AND (e.kind<>'reference_boundary' OR (EXISTS(SELECT 1 FROM card c WHERE c.card_id IS json_extract(e.record_json,'$.new_card.card_id') AND c.language IS json_extract(e.record_json,'$.new_card.language') AND c.set_code IS json_extract(e.record_json,'$.new_card.set_code') AND c.collector_number IS json_extract(e.record_json,'$.new_card.collector_number') AND c.variant IS json_extract(e.record_json,'$.new_card.variant') AND c.name IS json_extract(e.record_json,'$.new_card.name') AND c.rarity IS json_extract(e.record_json,'$.new_card.rarity') AND c.provenance IS json_extract(e.record_json,'$.new_card.provenance') AND c.rights_reference IS json_extract(e.record_json,'$.new_card.rights_reference') AND c.display_allowed IS json_extract(e.record_json,'$.new_card.display_allowed') AND c.match_eligible IS json_extract(e.record_json,'$.new_card.match_eligible') AND c.attributes_json IS json_extract(e.record_json,'$.new_card.attributes_json')) AND EXISTS(SELECT 1 FROM card_reference r WHERE r.source IS json_extract(e.record_json,'$.new_reference.source') AND r.native_id IS json_extract(e.record_json,'$.new_reference.native_id') AND r.set_code IS json_extract(e.record_json,'$.new_reference.set_code') AND r.collector_number IS json_extract(e.record_json,'$.new_reference.collector_number') AND r.name IS json_extract(e.record_json,'$.new_reference.name') AND r.rarity IS json_extract(e.record_json,'$.new_reference.rarity') AND r.attributes_json IS json_extract(e.record_json,'$.new_reference.attributes_json') AND r.provenance IS json_extract(e.record_json,'$.new_reference.provenance') AND r.rights_reference IS json_extract(e.record_json,'$.new_reference.rights_reference') AND r.display_allowed IS json_extract(e.record_json,'$.new_reference.display_allowed'))));

CREATE VIEW IF NOT EXISTS effective_card_reference AS
SELECT r.* FROM card_reference r WHERE NOT EXISTS (
 SELECT 1 FROM source_correction_evidence e WHERE e.kind='reference_boundary'
 AND ((r.source=json_extract(e.record_json,'$.reference_exclusion.source') AND r.native_id=json_extract(e.record_json,'$.reference_exclusion.native_id'))
 OR (r.source=json_extract(e.record_json,'$.new_reference.source') AND r.native_id=json_extract(e.record_json,'$.new_reference.native_id'))))
UNION ALL
SELECT r.* FROM card_reference r JOIN active_source_correction_evidence e
ON e.kind='reference_boundary' AND r.source=json_extract(e.record_json,'$.new_reference.source') AND r.native_id=json_extract(e.record_json,'$.new_reference.native_id');

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

CREATE VIEW IF NOT EXISTS base_discovery_card_facet AS
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

CREATE VIEW IF NOT EXISTS discovery_card_facet AS
WITH blocked_artist_cards AS MATERIALIZED (
 SELECT DISTINCT json_extract(j.value,'$.card_id') AS card_id
 FROM source_correction_evidence e,json_each(e.record_json,'$.snapshot.cards') j
 WHERE e.kind='printed_artist'
), active_artist_facts AS MATERIALIZED (
 SELECT json_extract(j.value,'$.card_id') AS card_id,'illustrator' AS facet_type,
        json_extract(e.record_json,'$.value') AS value,e.event_id AS provenance,
        json_extract(json_extract(e.record_json,'$.parent_record_json'),'$.sources[0].url') AS rights_reference
 FROM active_source_correction_evidence e,json_each(e.record_json,'$.snapshot.cards') j
 WHERE e.kind='printed_artist'
)
SELECT f.* FROM base_discovery_card_facet f
LEFT JOIN blocked_artist_cards blocked ON blocked.card_id=f.card_id
WHERE NOT (f.facet_type='illustrator' AND blocked.card_id IS NOT NULL)
UNION ALL SELECT * FROM active_artist_facts;
