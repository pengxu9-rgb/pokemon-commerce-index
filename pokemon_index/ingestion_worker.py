"""Recoverable, bounded feed-call queue for operator-owned persistent SQLite.

Adapters return normalized observations. No scheduler or live connector is
enabled here. Call budgets include retries; failed/crashed reservations count.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from . import core


class RetryableFeedError(Exception):
    """Adapter classifies an authorized feed failure as transient."""


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS feed_job (
          job_id TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES source_policy(source),
          request_json TEXT NOT NULL, request_sha TEXT NOT NULL, created_at TEXT NOT NULL,
          state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
          due_at TEXT NOT NULL, lease_until TEXT, last_code TEXT);
        CREATE TABLE IF NOT EXISTS feed_budget (
          source TEXT NOT NULL, utc_date TEXT NOT NULL, used INTEGER NOT NULL,
          PRIMARY KEY(source,utc_date));
        CREATE TABLE IF NOT EXISTS ingest_receipt (
          source TEXT NOT NULL, native_id TEXT NOT NULL, observed_at TEXT NOT NULL,
          payload_sha TEXT NOT NULL, PRIMARY KEY(source,native_id,observed_at));
    ''')


def enqueue(db, job_id, source, request, *, now):
    core._policy(db, source)
    # Only discovery coordinates, never auth material, arbitrary URLs or images.
    if not isinstance(request, dict) or set(request)-{'query','page','native_ids','product_ids'}:
        raise ValueError('request must contain discovery coordinates only')
    if not isinstance(job_id,str) or not job_id.strip():
        raise ValueError('job id required')
    encoded = _encoded(request)
    if len(encoded)>20000:
        raise ValueError('feed request too large')
    sha=hashlib.sha256(encoded.encode()).hexdigest()
    now=core.parse_time(now).isoformat()
    with db:
        existing=db.execute('SELECT source,request_sha FROM feed_job WHERE job_id=?',(job_id,)).fetchone()
        if existing and (existing['source']!=source or existing['request_sha']!=sha):
            raise ValueError('job id already binds a different request')
        db.execute('INSERT OR IGNORE INTO feed_job VALUES (?,?,?,?,?,\'pending\',0,?,NULL,NULL)',
                   (job_id,source,encoded,sha,now,now))


def _ingest(db, rows, source, instant):
    """All observations, receipts and job completion commit together."""
    fields=('title','url','seller_native_id','status','price_minor','currency',
            'evidence_ref','poll_reason','native_created','native_updated')
    imported=unresolved=duplicates=0
    policy=core._policy(db,source)
    cutoff=instant-timedelta(days=policy['retention_days'])
    for raw in rows:
        row=dict(raw)
        if row.get('source')!=source:
            raise ValueError('feed response source mismatch')
        at=core.parse_time(row['observed_at'])
        if at>instant or at<cutoff:
            raise ValueError('observation outside permitted time window')
        row['observed_at']=at.isoformat()
        key=(source,row['native_id'],row['observed_at'])
        sha=hashlib.sha256(_encoded(row).encode()).hexdigest()
        receipt=db.execute('SELECT payload_sha FROM ingest_receipt WHERE source=? AND native_id=? AND observed_at=?',key).fetchone()
        if receipt:
            if receipt[0]!=sha:
                raise ValueError('conflicting immutable observation')
            duplicates+=1;continue
        old=db.execute('SELECT * FROM observation WHERE source=? AND native_id=? AND observed_at=?',key).fetchone()
        if old:
            for field in fields:
                value=row.get(field, 'discovery' if field=='poll_reason' else None)
                if field in {'native_created','native_updated'} and value is not None:
                    value=str(value)
                if value!=old[field]:
                    raise ValueError('conflicting immutable observation')
            # Prior unjournalled resolutions cannot be silently changed either.
            unit,method=core.resolve(db,row)
            prior=db.execute('SELECT unit_id FROM listing WHERE source=? AND native_id=?',key[:2]).fetchone()
            if prior and unit!=prior[0]:
                raise ValueError('existing observation resolution needs review')
            duplicates+=1
        else:
            counts=core.import_observations(db,[row],commit=False)
            imported+=counts['imported'];unresolved+=counts['unresolved']
        db.execute('INSERT INTO ingest_receipt VALUES (?,?,?,?)',(*key,sha))
    return dict(imported=imported,unresolved=unresolved,duplicates=duplicates)


def run_next(db, fetch, *, source, now, calls_per_day=100, max_attempts=3,
             max_batch=100, lease_seconds=120):
    for value in (calls_per_day,max_attempts,max_batch,lease_seconds):
        if type(value) is not int or value<1:
            raise ValueError('positive worker bounds required')
    core._policy(db,source)
    instant=core.parse_time(now);stamp=instant.isoformat();day=instant.date().isoformat()
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute("UPDATE feed_job SET state='failed',last_code='attempt_limit' WHERE source=? AND state='running' AND lease_until<=? AND attempts>=?",(source,stamp,max_attempts))
        job=db.execute("""SELECT * FROM feed_job WHERE source=? AND attempts<? AND
            ((state IN ('pending','retry') AND due_at<=?) OR (state='running' AND lease_until<=?))
            ORDER BY created_at,job_id LIMIT 1""",(source,max_attempts,stamp,stamp)).fetchone()
        if not job:
            db.commit();return {'status':'idle'}
        used=db.execute('SELECT used FROM feed_budget WHERE source=? AND utc_date=?',(source,day)).fetchone()
        if used and used[0]>=calls_per_day:
            db.commit();return {'status':'quota_blocked','calls_used':used[0]}
        db.execute('INSERT INTO feed_budget VALUES (?,?,1) ON CONFLICT(source,utc_date) DO UPDATE SET used=used+1',(source,day))
        attempt=job['attempts']+1
        db.execute("UPDATE feed_job SET state='running',attempts=?,lease_until=?,last_code=NULL WHERE job_id=?",
                   (attempt,(instant+timedelta(seconds=lease_seconds)).isoformat(),job['job_id']))
        db.commit()
    except Exception:
        db.rollback();raise
    try:
        response=fetch(json.loads(job['request_json']))
        if not isinstance(response,list) or len(response)>max_batch:
            raise ValueError('invalid or oversized normalized response')
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT state,attempts FROM feed_job WHERE job_id=?',(job['job_id'],)).fetchone()
        if current['state']!='running' or current['attempts']!=attempt:
            db.rollback();return {'status':'lease_superseded'}
        counts=_ingest(db,response,source,instant)
        db.execute("UPDATE feed_job SET state='done',lease_until=NULL,last_code=NULL WHERE job_id=?",(job['job_id'],))
        db.commit()
        return dict(status='done',job_id=job['job_id'],attempt=attempt,**counts)
    except (RetryableFeedError, ValueError, KeyError, TypeError) as error:
        db.rollback()
        retry=isinstance(error,RetryableFeedError) and attempt<max_attempts
        code='transient_feed_failure' if isinstance(error,RetryableFeedError) else 'invalid_or_conflicting_evidence'
        due=(instant+timedelta(seconds=min(3600,60*2**(attempt-1)))).isoformat()
        with db:
            db.execute("UPDATE feed_job SET state=?,due_at=?,lease_until=NULL,last_code=? WHERE job_id=? AND state='running' AND attempts=?",
                       ('retry' if retry else 'failed',due,code,job['job_id'],attempt))
        return {'status':'retry' if retry else 'failed','job_id':job['job_id'],'code':code}
    # Unexpected errors leave the committed lease recoverable after timeout.
    except Exception:
        db.rollback()
        raise


def monitor(db, *, source, now):
    policy=core._policy(db,source);instant=core.parse_time(now)
    rows=db.execute('SELECT status,observed_at FROM observation o WHERE source=? AND observed_at=(SELECT MAX(observed_at) FROM observation WHERE source=o.source AND native_id=o.native_id AND observed_at<=?)',(source,instant.isoformat())).fetchall()
    cutoff=instant-timedelta(hours=policy['listing_ttl_hours'])
    active=[r for r in rows if r['status']=='on_sale']
    return {'source':source,'as_of':instant.isoformat(),'fresh_on_sale':sum(cutoff<=core.parse_time(r['observed_at'])<=instant for r in active),
            'stale_on_sale':sum(core.parse_time(r['observed_at'])<cutoff for r in active),
            'job_states':{r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM feed_job WHERE source=? GROUP BY state',(source,))}}


def purge(db, *, now):
    instant=core.parse_time(now)
    removed=core.purge_expired(db,now)
    with db:
        removed['feed_job']=removed['ingest_receipt']=0
        for policy in db.execute('SELECT * FROM source_policy').fetchall():
            cutoff=(instant-timedelta(days=policy['retention_days'])).isoformat()
            for table,column in [('feed_job','created_at'),('ingest_receipt','observed_at')]:
                removed[table]+=db.execute(f'DELETE FROM {table} WHERE source=? AND {column}<?',(policy['source'],cutoff)).rowcount
    return removed
