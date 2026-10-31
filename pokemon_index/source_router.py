"""Offline API-first adapter policy experiment; no production networking.

Only inert fixture adapters are accepted. This is not an authorization or a
network client, and cannot be wired into production without separate adapters,
source permissions, common budget enforcement and independent review.
"""
from copy import deepcopy
from datetime import datetime, timezone
import time

class SourceRoutingError(ValueError):
    pass

class UnsupportedCoverage(SourceRoutingError):
    """Provider declares a specific operation unsupported before dispatch."""

class FixtureAdapter:
    """Deterministic in-memory fake with an existing crawler-shaped interface."""
    def __init__(self, source, rows, *, unsupported=(), failure=None):
        if not isinstance(source, str) or not source or not isinstance(rows, list):
            raise ValueError('invalid fixture')
        self.source, self.rows, self.unsupported, self.failure = source, deepcopy(rows), set(unsupported), failure
        self.calls=[]
    def search(self, source, query, limit=5):
        self.calls.append('search')
        if source != self.source: raise SourceRoutingError('source mismatch')
        if 'search' in self.unsupported: raise UnsupportedCoverage('unsupported')
        if self.failure: raise SourceRoutingError(self.failure)
        return deepcopy(self.rows[:limit])
    def detail(self, url):
        self.calls.append('detail')
        if 'detail' in self.unsupported: raise UnsupportedCoverage('unsupported')
        if self.failure: raise SourceRoutingError(self.failure)
        result = [r for r in self.rows if r.get('url') == url]
        if len(result) != 1: raise SourceRoutingError('fixture detail unavailable')
        return deepcopy(result[0])

class SourceRouter:
    """Explicit per-source modes, shared fixture attempt budget, sticky detail."""
    def __init__(self, policies, adapters, *, enabled=False, max_attempts=8, deadline_seconds=20, clock=time.monotonic, cancelled=lambda: False):
        if type(enabled) is not bool or type(max_attempts) is not int or not 1<=max_attempts<=32 or not isinstance(deadline_seconds,(int,float)) or isinstance(deadline_seconds,bool) or not 0<deadline_seconds<=60:
            raise ValueError('invalid router configuration')
        if not isinstance(policies, dict) or not isinstance(adapters,dict) or not callable(clock) or not callable(cancelled): raise ValueError('invalid router configuration')
        self.enabled,self.remaining,self.clock,self.cancelled=enabled,max_attempts,clock,cancelled
        self.deadline=clock()+deadline_seconds
        self.policies,self.adapters,self.bindings,self.ids,self.snapshots=deepcopy(policies),dict(adapters),{},{},{}
        for source, policy in self.policies.items():
            if not isinstance(source,str) or not source or not isinstance(policy,dict) or set(policy)!={'mode','api_approved','crawl_approved'} or policy['mode'] not in {'disabled','api_only','crawl_only','api_preferred'} or type(policy['api_approved']) is not bool or type(policy['crawl_approved']) is not bool:
                raise ValueError('invalid source policy')
        for key,adapter in self.adapters.items():
            if not isinstance(key,tuple) or len(key)!=2 or key[0] not in policies or key[1] not in {'api','crawl'} or type(adapter) is not FixtureAdapter or adapter.source!=key[0]: raise ValueError('only matching inert fixtures accepted')
    def _check(self):
        if not self.enabled: raise SourceRoutingError('router disabled')
        if self.cancelled(): raise SourceRoutingError('cancelled')
        if self.clock() >= self.deadline: raise SourceRoutingError('deadline exceeded')
    def _attempt(self,source,mode,operation,*args):
        self._check(); policy=self.policies[source]
        if not policy[mode+'_approved']: raise SourceRoutingError('source method not approved')
        adapter=self.adapters.get((source,mode))
        if adapter is None: raise SourceRoutingError('fixture adapter unavailable')
        if self.remaining<=0: raise SourceRoutingError('attempt budget exhausted')
        self.remaining-=1
        result=getattr(adapter,operation)(*args)
        self._check()
        return result
    @staticmethod
    def _validate(row,source):
        if not isinstance(row,dict) or row.get('source')!=source or not all(isinstance(row.get(k),str) and 0<len(row[k])<=2048 for k in ('native_id','url','observed_at')): raise SourceRoutingError('invalid listing observation')
        try:
            stamp=datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
            if stamp.tzinfo is None: raise ValueError()
            stamp.astimezone(timezone.utc)
        except (TypeError,ValueError): raise SourceRoutingError('invalid observation timestamp') from None
        return row
    def _continuity(self, row):
        old=self.snapshots.get(row["url"])
        if old:
            before=datetime.fromisoformat(old["observed_at"].replace("Z","+00:00"))
            after=datetime.fromisoformat(row["observed_at"].replace("Z","+00:00"))
            if after < before or after == before and old != row: raise SourceRoutingError("observation rollback or conflict")

    def search(self,source,query,limit=5):
        self._check()
        if source not in self.policies or not isinstance(query,str) or not query.strip() or len(query)>240 or type(limit) is not int or not 1<=limit<=20: raise SourceRoutingError('invalid request')
        policy=self.policies[source]; mode=policy['mode']
        if mode=='disabled': raise SourceRoutingError('source disabled')
        first='crawl' if mode=='crawl_only' else 'api'
        try: rows=self._attempt(source,first,'search',source,query,limit)
        except UnsupportedCoverage:
            if mode!='api_preferred': raise
            # Explicit independent crawl approval is required. Never fallback for
            # denials, auth, rate limits, timeouts, cancellation or empty results.
            rows=self._attempt(source,'crawl','search',source,query,limit);first='crawl'
        if not isinstance(rows,list) or len(rows)>limit: raise SourceRoutingError('invalid result')
        additions={}; output=[]; ids=set()
        for row in rows:
            row=self._validate(row,source); self._continuity(row); key=(source,row['native_id']); url=row['url']
            if key in ids or url in additions or key in self.ids and self.ids[key] != url or url in self.bindings and self.bindings[url] != (source,row['native_id'],first): raise SourceRoutingError('duplicate or conflicting listing identity')
            ids.add(key);additions[url]=(source,row['native_id'],first)
            result=deepcopy(row);result['source_provenance']={'source':source,'method':first,'observed_at':row['observed_at'],'fixture':True};output.append(result)
        self.bindings.update(additions)
        self.ids.update({(source,native):url for url,(_,native,_) in additions.items()})
        self.snapshots.update({row["url"]:deepcopy(row) for row in rows})
        return output
    def detail(self,url):
        self._check()
        if not isinstance(url,str) or url not in self.bindings: raise SourceRoutingError('listing was not observed')
        source,native,mode=self.bindings[url]
        row=self._validate(self._attempt(source,mode,'detail',url),source)
        if row['url']!=url or row['native_id']!=native: raise SourceRoutingError('listing identity changed')
        self._continuity(row);self.snapshots[url]=deepcopy(row)
        result=deepcopy(row);result['source_provenance']={'source':source,'method':mode,'observed_at':row['observed_at'],'fixture':True}
        return result
