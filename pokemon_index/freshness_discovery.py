"""Opt-in, bounded observation index; no scheduler, network or transaction capability."""
from datetime import datetime, timezone
from copy import deepcopy

_ALLOWED={'available','sold','unknown'}
def _time(value):
    if not isinstance(value,str): raise ValueError('timestamp required')
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('timezone required')
    return t.astimezone(timezone.utc)

class DiscoveryIndex:
    def __init__(self, *, enabled=False, capacity=1000):
        if type(enabled) is not bool or type(capacity) is not int or not 1 <= capacity <= 10000:raise ValueError('invalid discovery configuration')
        self.enabled=enabled;self.capacity=capacity;self._records={}
    def ingest(self, observations, *, now):
        if not self.enabled:raise ValueError('discovery disabled')
        if not isinstance(observations,list) or len(observations)>100:raise ValueError('bounded list required')
        current=_time(now); updates={}
        for row in observations:
            if not isinstance(row,dict) or set(row)!={'source','listing_id','url','status','price_minor','currency','observed_at'}:raise ValueError('invalid observation')
            if not all(isinstance(row[k],str) and 0<len(row[k])<=2048 for k in ('source','listing_id','url')):raise ValueError('invalid identity')
            if row['status'] not in _ALLOWED or row['price_minor'] is not None and (type(row['price_minor']) is not int or row['price_minor']<0):raise ValueError('invalid listing state')
            if row['currency'] is not None and (not isinstance(row['currency'],str) or len(row['currency'])!=3 or not row['currency'].isalpha() or not row['currency'].isupper()):raise ValueError('invalid currency')
            when=_time(row['observed_at'])
            if when>current:raise ValueError('future observation')
            key=(row['source'],row['listing_id']);old=updates.get(key) or self._records.get(key)
            if old and old['url']!=row['url']:raise ValueError('listing identity conflict')
            if old and _time(old['observed_at'])==when and old!=row:raise ValueError('contradictory same-time observation')
            if not old or _time(old['observed_at'])<when: updates[key]=deepcopy(row)
        if len(set(self._records)|set(updates))>self.capacity:raise ValueError('capacity exceeded')
        self._records.update(updates)
        return len(updates)
    def get(self,source,listing_id):
        return deepcopy(self._records.get((source,listing_id)))
