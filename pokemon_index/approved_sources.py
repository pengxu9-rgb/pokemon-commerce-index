"""Default-off source routing for already-approved, guarded adapter instances.

No credentials or permissions are created here. CommerceLoop retains server-owned listing bindings. Adapter operations through this module are serialized. It refuses renderers, custom HTML fetchers and unbudgeted
adapters. In-flight transport operations are not hard-cancellable.
"""
from copy import deepcopy
import json
from datetime import datetime
from functools import wraps
from threading import RLock
from .dispatch_budget import DispatchBudget,DispatchDenied
from .ebay_official import BrowseClient,_https_json
from .marketplace_crawl import Crawler,PublicHTMLFetch,canonical_product_url

class SourceWiringError(ValueError): pass

_ADAPTER_LOCK=RLock()

def _serialized(method):
 @wraps(method)
 def wrapped(self,*args,**kwargs):
  with self._lock:
   return method(self,*args,**kwargs)
 return wrapped

class ApprovedSources:
 def __init__(self, *, policies, budget, crawler=None, ebay_client=None, enabled=False, public_listing_urls=()):
  if enabled is not True: raise SourceWiringError('source routing disabled')
  if type(budget) is not DispatchBudget: raise SourceWiringError('guarded budget required')
  if not isinstance(policies,dict) or not policies: raise SourceWiringError('policy required')
  self.policies=deepcopy(policies)
  for source,p in self.policies.items():
   if source not in {'ebay_us','mercari','snkrdunk'} or not isinstance(p,dict) or set(p)!={'mode','api_approved','crawl_approved','access_approval','photo_display_approved','partner_handoff_allowed'} or p['mode'] not in {'disabled','api_only','crawl_only','api_preferred'} or type(p['api_approved']) is not bool or type(p['crawl_approved']) is not bool or type(p['partner_handoff_allowed']) is not bool or type(p['photo_display_approved']) is not bool or not isinstance(p['access_approval'],str) or not __import__('re').fullmatch(r'[A-Za-z0-9._:-]{3,128}',p['access_approval']): raise SourceWiringError('invalid policy')
  needs_api=any(source=='ebay_us' and p['mode'] in {'api_only','api_preferred'} and p['api_approved'] for source,p in self.policies.items())
  needs_crawl=any((p['mode']=='crawl_only' or (p['mode']=='api_preferred' and source!='ebay_us')) and p['crawl_approved'] for source,p in self.policies.items())
  if needs_crawl and crawler is None: raise SourceWiringError('guarded crawler required')
  if needs_api and ebay_client is None: raise SourceWiringError('guarded approved API client required')
  self.crawler,self.api,self.budget=crawler,ebay_client,budget
  if not isinstance(public_listing_urls,(list,tuple)) or len(public_listing_urls)>32 or len(set(public_listing_urls))!=len(public_listing_urls):
   raise SourceWiringError('invalid server URL allowlist')
  for url in public_listing_urls:
   source,_,canonical=canonical_product_url(url)
   if url!=canonical or source not in self.policies: raise SourceWiringError('invalid server URL allowlist')
  self.public_listing_urls=frozenset(public_listing_urls)
  self._lock=_ADAPTER_LOCK
  self._revocation_lock=RLock(); self._revoked=set()
  self._crawl_authorizer=self._authorize_crawl_dispatch
  self._api_authorizer=lambda:self._authorize_dispatch('ebay_us','api')
  if self.crawler is not None: self.crawler.fetch.source_authorized=self._crawl_authorizer
  if self.api is not None: self.api.source_authorized=self._api_authorizer
  self._guard()
  self.listings={}; self.observations={}; self.snapshots={}; self.native_urls={}
 def _guard_adapters(self):
  if self.crawler is not None and (type(self.crawler) is not Crawler or type(self.crawler.fetch) is not PublicHTMLFetch or not self.crawler.fetch.enabled or self.crawler.renderer is not None or self.crawler.dispatch_budget is not self.budget or self.crawler.fetch.dispatch_budget is not self.budget or self.crawler.fetch.source_authorized is not self._crawl_authorizer):
   raise SourceWiringError('crawler guards changed')
  if self.api is not None and (type(self.api) is not BrowseClient or not self.api.enabled or self.api._transport is not _https_json or self.api.dispatch_budget is not self.budget or self.api.source_authorized is not self._api_authorizer):
   raise SourceWiringError('API guards changed')
 def _guard(self):
  self._guard_adapters()
  self.budget.check()
 def revoke(self, source):
  """Server-only revocation; independent of the in-flight adapter lock."""
  if source not in self.policies: raise SourceWiringError('source not configured')
  with self._revocation_lock: self._revoked.add(source)
 def _authorize_dispatch(self, source, method):
  with self._revocation_lock:
   if source in self._revoked: raise SourceWiringError('source revoked')
  if self._method(source)!=method: raise SourceWiringError('source mode changed')
  self.budget.check()
 def _authorize_crawl_dispatch(self, url):
  from urllib.parse import urlsplit
  source={'jp.mercari.com':'mercari','snkrdunk.com':'snkrdunk','www.snkrdunk.com':'snkrdunk','www.ebay.com':'ebay_us','ebay.com':'ebay_us'}.get(urlsplit(url).hostname)
  self._authorize_dispatch(source,'crawl')
 def authorize_handoff(self, source):
  self._guard(); self._method(source)
  if self.policies[source]['partner_handoff_allowed'] is not True:
   raise SourceWiringError('partner handoff not approved')
 def _project(self,item,source):
  result=deepcopy(item)
  if self.policies[source]['photo_display_approved'] is not True:
   result['listing_photos']=[]
  return result
 def project_retained(self,item):
  """Recheck current publication rights without admitting another read.

  Exhausting a read allowance does not revoke captured evidence. Source
  revocation, access/mode changes and photo permission changes still apply.
  """
  with self._revocation_lock:
   self._guard_adapters()
   source=item.get('source');method=self._method(source)
   if (item.get('source_provenance') or {}).get('method')!=method:
    raise SourceWiringError('source mode changed; research again')
   return self._project(item,source)
 def _observation(self,item):
  try:
   value=datetime.fromisoformat(item['observed_at'].replace('Z','+00:00'))
   if value.tzinfo is None or value.utcoffset() is None: raise ValueError()
   return value
  except (ValueError,TypeError,KeyError,AttributeError):
   raise SourceWiringError('invalid observation time')
 def _snapshot(self,item,method):
  # Only these query-specific search annotations may be absent on detail.
  # All listing, seller, grade, price, stock and evidence fields match exactly.
  annotations={'query_match_basis':{'collector_context','public_search_query_identity_unverified'},
               'name_match_status':{'recognized_character_context','identity_unverified'}} if method=='crawl' and item.get('source')=='mercari' else {}
  try:
   extras={k:item[k] for k in annotations if k in item}
   if any(not isinstance(v,str) or v not in annotations[k] for k,v in extras.items()):
    raise ValueError('invalid query annotation')
   core=json.dumps({k:v for k,v in item.items() if k not in {'observed_at','source_provenance',*annotations}},sort_keys=True,separators=(',',':'),allow_nan=False)
   return core,extras
  except (TypeError,ValueError):
   raise SourceWiringError('invalid observation content') from None
 def _validate_observation(self,url,observed,snapshot):
  if url in self.observations:
   previous=self.observations[url]
   if observed<previous: raise SourceWiringError('observation rollback')
   if observed==previous:
    old_core,old_extras=self.snapshots[url];core,extras=snapshot
    if core!=old_core or any(k in old_extras and old_extras[k]!=v for k,v in extras.items()):
     raise SourceWiringError('conflicting same-time observation')
    # Retain same-time annotation claims for future contradiction checks;
    # never copy them into a returned detail observation.
    return core,{**old_extras,**extras}
  return snapshot
 def _method(self,source):
  if source not in self.policies: raise SourceWiringError('source not configured')
  p=self.policies[source];mode=p['mode']
  with self._revocation_lock:
   if source in self._revoked: raise SourceWiringError('source revoked')
  if not p.get('access_approval'): raise SourceWiringError('source access required')
  if mode=='disabled': raise SourceWiringError('source disabled')
  # API capability is known before dispatch; errors never trigger fallback.
  if mode in {'api_only','api_preferred'} and source=='ebay_us':
   if not p['api_approved'] or self.api is None: raise SourceWiringError('API not approved or not configured')
   return 'api'
  if mode=='api_only': raise SourceWiringError('API unsupported')
  if not p['crawl_approved'] or self.crawler is None or source not in self.crawler.authorized_sources: raise SourceWiringError('crawl not approved')
  return 'crawl'
 @_serialized
 def search(self,source,query,limit=3):
  self._guard(); method=self._method(source); adapter=self.api if method=='api' else self.crawler
  response=adapter.search(query,limit=limit) if method=='api' else adapter.search(source,query,limit=limit)
  self._authorize_dispatch(source,method)
  if not isinstance(response,dict) or response.get('source')!=source or not isinstance(response.get('listings'),list) or len(response['listings'])>limit: raise SourceWiringError('invalid producer response')
  pending={};pending_times={};pending_snapshots={};pending_native={};ids=set();rows=[]
  for item in response['listings']:
   if not isinstance(item,dict) or item.get('source')!=source or not all(isinstance(item.get(k),str) and item[k] for k in ('native_id','url','observed_at')): raise SourceWiringError('invalid listing')
   url,native=item['url'],item['native_id']
   # eBay Browse supports only v1|legacy|0 in its current adapter; do not map
   # variation IDs to parent URL and assert copy identity.
   if method=='api' and not __import__('re').fullmatch(r'v1\|[0-9]{8,20}\|0',native): raise SourceWiringError('ambiguous item variation')
   if native in ids or url in pending or url in self.listings and self.listings[url]!=(source,native,method): raise SourceWiringError('ambiguous listing identity')
   if method=='api':
    # Browse search is discovery only. Its summaries can omit stock, grader,
    # printing aspects and photo evidence. Never retain a summary as the
    # selection baseline, then mistake those detail fields for later drift.
    # The same guarded client accounts for each detail request, including
    # admission, deadline and source revocation immediately before dispatch.
    url_source,legacy,canonical=canonical_product_url(url)
    if url_source!=source or canonical!=url or native!=f'v1|{legacy}|0':
     raise SourceWiringError('discovery URL differs from native listing')
    self._authorize_dispatch(source,method)
    discovered_at=self._observation(item)
    detail=adapter.detail(url)
    self._authorize_dispatch(source,method)
    if (not isinstance(detail,dict) or detail.get('source')!=source
        or detail.get('native_id')!=native or detail.get('url')!=url
        or detail.get('scope')!='listing' or detail.get('variant_status')=='unresolved'
        or self._observation(detail)<discovered_at):
     raise SourceWiringError('discovery detail identity changed or unavailable')
    item=detail
   observed=self._observation(item); key=(source,native)
   if key in self.native_urls and self.native_urls[key]!=url: raise SourceWiringError('listing identity changed')
   snapshot=self._validate_observation(url,observed,self._snapshot(item,method))
   pending_times[url]=observed;pending_snapshots[url]=snapshot;pending_native[key]=url
   ids.add(native);pending[url]=(source,native,method);row=self._project(item,source);row['source_provenance']={'source':source,'method':method,'observed_at':item['observed_at']};rows.append(row)
  self.listings.update(pending);self.observations.update(pending_times);self.snapshots.update(pending_snapshots);self.native_urls.update(pending_native);return dict(response,listings=rows)
 @_serialized
 def onboard_url(self,url):
  """Resolve one canonical public URL through its approved source, not a card match.

  This is not a purchase or authenticity check. A fresh detail response must
  bind the same source and listing; unresolved eBay variations are rejected.
  """
  self._guard()
  if url not in self.public_listing_urls: raise SourceWiringError('URL not authorized by server')
  source,identifier,canonical=canonical_product_url(url)
  if canonical!=url: raise SourceWiringError('canonical listing URL required')
  method=self._method(source)
  if method=='api' and url!=f'https://www.ebay.com/itm/{identifier}':
   raise SourceWiringError('canonical eBay item URL required')
  item=(self.api if method=='api' else self.crawler).detail(url)
  self._authorize_dispatch(source,method)
  if not isinstance(item,dict) or item.get('source')!=source or item.get('url')!=url or not isinstance(item.get('native_id'),str):
   raise SourceWiringError('listing identity changed')
  if item.get('scope')!='listing' or item.get('variant_status')=='unresolved':
   raise SourceWiringError('individual listing or variant is unresolved')
  native=item['native_id']
  expected=f'v1|{identifier}|0' if method=='api' else identifier
  if native!=expected: raise SourceWiringError('ambiguous item variation or listing identity')
  binding=(source,native,method); key=(source,native)
  if url in self.listings and self.listings[url]!=binding or key in self.native_urls and self.native_urls[key]!=url:
   raise SourceWiringError('ambiguous listing identity')
  observed=self._observation(item)
  snapshot=self._validate_observation(url,observed,self._snapshot(item,method))
  self.listings[url]=binding;self.native_urls[key]=url
  self.observations[url]=observed;self.snapshots[url]=snapshot
  result=self._project(item,source);result['source_provenance']={'source':source,'method':method,'observed_at':item['observed_at']};return result
 @_serialized
 def detail(self,url):
  self._guard()
  if url not in self.listings: raise SourceWiringError('unobserved URL cannot be refreshed')
  source,native,method=self.listings[url]
  if self._method(source)!=method: raise SourceWiringError('source mode changed; research again')
  item=(self.api if method=='api' else self.crawler).detail(url);self._authorize_dispatch(source,method)
  if not isinstance(item,dict) or item.get('source')!=source or item.get('native_id')!=native or item.get('url')!=url or not isinstance(item.get('observed_at'),str): raise SourceWiringError('listing identity changed')
  observed=self._observation(item)
  snapshot=self._validate_observation(url,observed,self._snapshot(item,method))
  self.observations[url]=observed;self.snapshots[url]=snapshot
  result=self._project(item,source);result['source_provenance']={'source':source,'method':method,'observed_at':item['observed_at']};return result
