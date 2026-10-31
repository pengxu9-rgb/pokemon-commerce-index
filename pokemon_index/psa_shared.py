"""Account-wide PSA admission, single flight and opt-in record-only caching.

Storage must offer generation compare-and-swap. No automatic new quota period,
local fallback, refund after dispatch, offer comparison cache, or live request
exists here. The operator supplies the actual account's approved quota window.
"""
from __future__ import annotations
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets


class StoreUnavailable(Exception):
    pass


def instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('invalid shared PSA time')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed.astimezone(timezone.utc)


class SharedPSA:
    def __init__(self, store, *, namespace, window_start, window_end, limit,
                 purchase_reserve, cache_approval=None, cache_seconds=0,
                 lease_seconds=90, max_entries=128):
        if (not isinstance(namespace, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,100}', namespace)
                or type(limit) is not int or not 1 <= limit <= 10000
                or type(purchase_reserve) is not int or not 0 <= purchase_reserve <= limit
                or type(cache_seconds) is not int or not 0 <= cache_seconds <= 3600
                or type(lease_seconds) is not int or not 30 <= lease_seconds <= 120
                or type(max_entries) is not int or not 1 <= max_entries <= 128
                or cache_approval is not None and (not isinstance(cache_approval, str)
                    or not re.fullmatch(r'[A-Za-z0-9:._/-]{1,200}', cache_approval))
                or cache_seconds and not cache_approval):
            raise ValueError('invalid shared PSA configuration')
        start, end = instant(window_start), instant(window_end)
        if not timedelta(seconds=60) <= end-start <= timedelta(days=2):
            raise ValueError('explicit bounded PSA quota period required')
        self.store, self.start, self.end = store, start, end
        self.limit, self.reserve = limit, purchase_reserve
        self.cache_seconds, self.lease_seconds, self.max_entries = cache_seconds, lease_seconds, max_entries
        self.scope = hashlib.sha256(namespace.encode()).hexdigest()
        policy = ['v2', namespace, start.isoformat(), end.isoformat(), limit, purchase_reserve,
                  cache_approval, cache_seconds, lease_seconds, max_entries]
        self.policy = hashlib.sha256(json.dumps(policy).encode()).hexdigest()

    def _new(self, now):
        return dict(schema='pokemon.psa-shared.v2', scope=self.scope, policy=self.policy,
                    start=self.start.isoformat(), end=self.end.isoformat(), used=0,
                    last_clock=now.isoformat(), leases={}, cache={}, purchase_uses={})

    @staticmethod
    def _now(clock):
        # Real clients supply their clock, sampled after each storage read.
        # Timestamp values remain supported for deterministic offline callers.
        return instant(clock() if callable(clock) else clock)

    def _load(self, now):
        held = self.store.read()
        now = self._now(now)
        generation, state = held if held is not None else ('0', self._new(now))
        expected = {'schema','scope','policy','start','end','used','last_clock','leases','cache','purchase_uses'}
        if (not isinstance(state, dict) or set(state) != expected
                or state['schema'] != 'pokemon.psa-shared.v2' or state['scope'] != self.scope
                or type(state['used']) is not int or not 0 <= state['used'] <= 10000
                or not isinstance(state['leases'], dict) or len(state['leases']) > 128
                or not isinstance(state['cache'], dict) or len(state['cache']) > 128
                or not isinstance(state['purchase_uses'], dict) or len(state['purchase_uses']) > self.max_entries
                or len(state['purchase_uses']) > state['used']
                or any(not re.fullmatch(r'[a-f0-9]{64}', key) or used is not True for key, used in state['purchase_uses'].items())
                or not isinstance(state['policy'],str) or not re.fullmatch(r'[a-f0-9]{64}',state['policy'])
                or not instant(state['start']) < instant(state['end'])
                or instant(state['last_clock']) > now+timedelta(seconds=1)):
            raise StoreUnavailable()
        # Commit order need not equal request-entry order. Tolerate at most one
        # second of replica skew, moving only forward so no lease/cache/window
        # is revived. Larger clock rollback still fails closed.
        now = max(now, instant(state['last_clock']))
        if state['policy'] != self.policy:
            # Only an explicit subsequent non-overlapping operator window may
            # reset counters. Different limits/replicas cannot reset an active one.
            if instant(state['end']) > self.start or now < self.start:
                raise StoreUnavailable()
            state = self._new(now)
        if state['start'] != self.start.isoformat() or state['end'] != self.end.isoformat() or state['used'] > self.limit:
            raise StoreUnavailable()
        state = copy.deepcopy(state)
        state['last_clock'] = now.isoformat()
        for key, lease in list(state['leases'].items()):
            if (not re.fullmatch(r'[a-f0-9]{64}', key) or not isinstance(lease, dict)
                    or set(lease) != {'id','expires'} or not isinstance(lease['id'], str)
                    or not re.fullmatch(r'[a-f0-9]{48}',lease['id']) or instant(lease['expires'])>instant(state['end'])):
                raise StoreUnavailable()
            if instant(lease['expires']) <= now:
                del state['leases'][key]
        return generation, state, now

    @staticmethod
    def key(cert):
        if not isinstance(cert, str) or not re.fullmatch(r'[0-9]{7,12}', cert):
            raise ValueError('invalid PSA certificate')
        return hashlib.sha256(cert.encode()).hexdigest()

    def acquire(self, cert, *, now, purpose='shortlist', dispatch_allowed=True):
        clock = now; now = self._now(clock); key = self.key(cert)
        if purpose not in {'shortlist','purchase'}:
            raise ValueError('invalid server PSA priority')
        if type(dispatch_allowed) is not bool:raise ValueError('invalid local PSA admission')
        if not self.start <= now < self.end:
            return {'status':'quota_window_closed'}
        try:
            for _ in range(5):
                generation, state, now = self._load(clock)
                if not self.start <= now < self.end:
                    return {'status':'quota_window_closed'}
                for item, cached in list(state['cache'].items()):
                    if (not re.fullmatch(r'[a-f0-9]{64}', item) or not isinstance(cached, dict)
                            or set(cached) != {'expires','value'}):
                        raise StoreUnavailable()
                    if not self.cache_seconds or instant(cached['expires']) <= now:
                        del state['cache'][item]
                cached = state['cache'].get(key)
                if cached:
                    value=cached['value']
                    if (not isinstance(value,dict) or instant(cached['expires'])!=instant(value['expires_at'])
                            or not instant(value['checked_at'])<=now<instant(value['expires_at'])
                            or instant(value['expires_at'])>min(self.end,instant(value['checked_at'])+timedelta(seconds=self.cache_seconds))):
                        raise StoreUnavailable()
                    return {'status':'cached','value':copy.deepcopy(cached['value']),'observed_at':now.isoformat()}
                if key in state['leases']:
                    return {'status':'lookup_busy'}
                if not dispatch_allowed:
                    return {'status':'lookup_rate_limited'}
                available = self.limit-state['used']
                if available <= 0:
                    return {'status':'quota_exhausted'}
                # A certificate gets at most one reserved dispatch per account
                # window, even after reselecting, another replica, or failure.
                reserve_eligible = (purpose == 'purchase' and key not in state['purchase_uses']
                                    and len(state['purchase_uses']) < self.max_entries)
                if not reserve_eligible and available <= self.reserve:
                    return {'status':'purchase_quota_reserved'}
                if len(state['leases']) >= self.max_entries:
                    return {'status':'lookup_busy'}
                lease_id = secrets.token_hex(24)
                state['used'] += 1  # Commit before dispatch, including failures.
                if reserve_eligible:
                    state['purchase_uses'][key] = True
                state['leases'][key] = dict(id=lease_id, expires=min(self.end, now+timedelta(seconds=self.lease_seconds)).isoformat())
                if self.store.write(generation, state):
                    return {'status':'admitted','key':key,'id':lease_id,'observed_at':now.isoformat()}
            return {'status':'lookup_busy'}
        except Exception:
            return {'status':'shared_store_unavailable'}

    def can_dispatch(self, lease, *, now):
        try:
            _,state,now=self._load(now);held=state['leases'].get(lease['key'])
            return self.start<=now<self.end and held is not None and held['id']==lease['id'] and now<instant(held['expires'])
        except Exception:return False

    def finish(self, lease, value, *, now, receipt=False):
        clock = now
        try:
            for _ in range(5):
                generation, state, now = self._load(clock)
                held = state['leases'].get(lease['key'])
                if (not self.start <= now < self.end or not held or held['id'] != lease['id']
                        or instant(held['expires']) <= now):
                    return False
                del state['leases'][lease['key']]
                if self.cache_seconds and value is not None:
                    if value.get('status') != 'found' or value.get('comparison',{}).get('status') != 'not_compared':
                        return False
                    expires = min(self.end, instant(value['expires_at']), instant(value['checked_at'])+timedelta(seconds=self.cache_seconds))
                    if now < expires:
                        value = copy.deepcopy(value);value['expires_at'] = expires.isoformat()
                        if len(state['cache']) >= self.max_entries:
                            del state['cache'][min(state['cache'], key=lambda k: instant(state['cache'][k]['expires']))]
                        state['cache'][lease['key']] = {'expires':expires.isoformat(),'value':value}
                if self.store.write(generation, state):
                    return {'observed_at':now.isoformat()} if receipt else True
            return False
        except Exception:
            return False
