"""Exact source-scan coverage; no sibling fallback or live/display approval."""
from collections import Counter
from . import source_image_facts,number_evidence,variant_dimension_hold,collector_runtime


def present(db,table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone())


def evidence(db,cid):
    primary=source_image_facts.context(db,cid) if present(db,'source_image_fact_evidence') else None
    if primary is not None:return 'source_image_facts',primary
    secondary=number_evidence.context(db,cid) if present(db,'card_number_reading_evidence') else None
    return ('number_reading',secondary) if secondary is not None else (None,None)


def availability(db,cid):
    hold=variant_dimension_hold.context(db,cid);basis,ctx=evidence(db,cid)
    status=('identity_hold' if hold else 'missing_source_scan_evidence' if ctx is None else
            'stale_source_scan_evidence' if not ctx['current_endpoint'] else
            'held_source_scan_evidence' if basis=='number_reading' and (not ctx['visible_text_agreement'] or ctx['source_coordinate_conflict']) else
            'current_source_scan_evidence')
    return dict(schema='pokemon.catalog-media-availability.v1',status=status,evidence_basis=basis,
        reason=(hold['reason'] if hold else 'no exact imported source scan evidence' if ctx is None else
                'primary source evidence is stale; no secondary fallback' if not ctx['current_endpoint'] else
                'number reading held or coordinate scope conflicts; observed text retained' if status=='held_source_scan_evidence' else
                'current exact source evidence; live fetch, display rights and physical printing remain unverified'),
        with_source_scans_eligible=status=='current_source_scan_evidence',
        source_scan_event_id=ctx['event_id'] if ctx else None,
        warnings=(ctx.get('warnings',[]) if basis=='source_image_facts' else
                  ['source_number_coordinate_conflict'] if ctx and ctx.get('source_coordinate_conflict') else []),
        inspection_tier=ctx['inspection_tier'] if ctx else None,current_endpoint=bool(ctx and ctx['current_endpoint']),
        source_ref=ctx['source_ref'] if ctx else None,image_sha256=ctx['image_sha256'] if ctx else None,
        live_fetch_verified=False,display_allowed=False,physical_printing_verified=False)


def subjects(db):
    ids=set()
    for table in ('source_image_fact_evidence','card_number_reading_evidence'):
        collector_runtime.checkpoint()
        if present(db,table):
            for row in db.execute('SELECT DISTINCT card_id FROM '+table):
                collector_runtime.checkpoint();ids.add(row[0])
    return ids


def current_ids(db):
    frozen=collector_runtime.snapshot_media_ids(db)
    if frozen is not None:
        # A caller cannot poison another request by changing its returned set.
        ids=set(frozen)
        collector_runtime.checkpoint()
        return ids
    ids=set()
    for cid in subjects(db):
        collector_runtime.checkpoint()
        current=availability(db,cid)['with_source_scans_eligible']
        collector_runtime.checkpoint()
        if current:ids.add(cid)
    return ids


def status(db):
    ids=subjects(db);contexts=[]
    for cid in ids:
        collector_runtime.checkpoint();contexts.append(availability(db,cid))
        collector_runtime.checkpoint()
    counts=Counter({key:0 for key in ('current_source_scan_evidence','stale_source_scan_evidence',
        'held_source_scan_evidence','missing_source_scan_evidence','identity_hold')})
    counts.update(c['status'] for c in contexts)
    held_ids={r['identity']['card_id'] for r in variant_dimension_hold.rows_for(db)}
    counts['identity_hold']+=len(held_ids-ids)
    total=db.execute('SELECT count(*) FROM card').fetchone()[0]
    counts['missing_source_scan_evidence']+=total-len(ids|held_ids)
    assert sum(counts.values())==total
    return dict(schema='pokemon.source-scan-coverage.v1',catalog_records=total,
        source_scan_subjects=len(ids),current_source_scan_subjects=counts['current_source_scan_evidence'],
        by_status=dict(counts),by_evidence_basis=dict(Counter(c['evidence_basis'] for c in contexts)),
        live_media_availability='unverified',image_display_permissions=0,
        scope='Primary image facts if present; otherwise exact agreed number readings. Held/stale primary never falls through; no live/display/physical approval.')
