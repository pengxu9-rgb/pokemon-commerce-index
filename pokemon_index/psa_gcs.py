"""Fixed-host GCS generation-CAS adapter. Inactive unless explicitly configured."""
from __future__ import annotations
import json
import re
import ssl
import threading
import time
from urllib import request, error
from urllib.parse import quote
from .psa_shared import SharedPSA, StoreUnavailable


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*_a,**_k):return None


def transport(url, *, method='GET', headers=None, body=None):
    opener=request.build_opener(NoRedirect(),request.HTTPSHandler(context=ssl.create_default_context()))
    req=request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with opener.open(req,timeout=2) as response:
            data=response.read(1048577)
            if response.geturl()!=url or len(data)>1048576:raise StoreUnavailable()
            return response.status,json.loads(data)
    except error.HTTPError as exc:
        code=exc.code;exc.close();return code,None


class GCSStore:
    def __init__(self, bucket, key, *, io=transport, token=None):
        if (not isinstance(bucket,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,62}',bucket)
                or not re.fullmatch(r'psa-private/v1/[a-f0-9]{64}\.json',key)):
            raise ValueError('invalid PSA shared store location')
        self.bucket,self.key,self.io,self.token=bucket,key,io,token
        self._token=None;self._token_until=0;self._last_write=0;self._lock=threading.Lock()

    def _auth(self):
        if self.token is not None:return self.token()
        if self._token is None or self._token_until<=time.monotonic():
            status,value=self.io('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',headers={'Metadata-Flavor':'Google'})
            if (status!=200 or not isinstance(value,dict) or not isinstance(value.get('access_token'),str)
                    or not re.fullmatch(r'[!-~]{1,8192}',value['access_token'])
                    or type(value.get('expires_in')) is not int or not 1<=value['expires_in']<=86400):raise StoreUnavailable()
            self._token=value['access_token'];self._token_until=time.monotonic()+max(0,value['expires_in']-60)
        return self._token

    def _call(self,path,**kwargs):
        headers={'Authorization':'Bearer '+self._auth(),**kwargs.pop('headers',{})}
        return self.io('https://storage.googleapis.com'+path,headers=headers,**kwargs)

    def read(self):
        path='/storage/v1/b/'+self.bucket+'/o/'+quote(self.key,safe='')
        status,meta=self._call(path+'?fields=generation,size')
        if status==404:return None
        if (status!=200 or not isinstance(meta,dict) or not re.fullmatch(r'[0-9]{1,30}',str(meta.get('generation','')))
                or not str(meta.get('size','')).isdigit() or int(meta['size'])>1048576):raise StoreUnavailable()
        generation=str(meta['generation'])
        status,value=self._call(path+'?alt=media&generation='+generation)
        if status!=200 or not isinstance(value,dict):raise StoreUnavailable()
        return generation,value

    def write(self,generation,value):
        if not isinstance(generation,str) or not re.fullmatch(r'[0-9]{1,30}',generation):raise StoreUnavailable()
        body=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
        if len(body)>1048576:raise StoreUnavailable()
        with self._lock:
            # A single object allows about one mutation per second. Unknown
            # outcomes and throttling are not retried as a second PSA dispatch.
            delay=1.05-(time.monotonic()-self._last_write)
            if delay>0:time.sleep(delay)
            status,meta=self._call('/upload/storage/v1/b/'+self.bucket+'/o?uploadType=media&name='+quote(self.key,safe='')+'&ifGenerationMatch='+generation+'&fields=generation',method='POST',headers={'Content-Type':'application/json'},body=body)
            self._last_write=time.monotonic()
        if status==412:return False
        if status!=200 or not isinstance(meta,dict) or not re.fullmatch(r'[0-9]{1,30}',str(meta.get('generation',''))):raise StoreUnavailable()
        return True


def configure(env, *, enabled=False):
    if not enabled:return None  # No metadata, credential or storage reads.
    keys=['PSA_SHARED_BUCKET','PSA_QUOTA_NAMESPACE','PSA_QUOTA_START','PSA_QUOTA_END','PSA_QUOTA_LIMIT','PSA_PURCHASE_RESERVE']
    if any(not isinstance(env.get(k),str) or not env[k] for k in keys):raise ValueError('shared PSA account quota configuration required')
    def integer(key,default=None):
        value=env.get(key,default)
        if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,5}',value):raise ValueError('invalid PSA quota number')
        return int(value)
    import hashlib
    namespace=env['PSA_QUOTA_NAMESPACE'];scope=hashlib.sha256(namespace.encode()).hexdigest()
    cache_seconds=integer('PSA_CACHE_SECONDS','0')
    approval=env.get('PSA_CACHE_APPROVAL_REF');retention=env.get('PSA_CACHE_RETENTION_REVIEW_REF')
    if cache_seconds:
        if any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9:._/-]{1,200}',v) for v in (approval,retention)):
            raise ValueError('PSA cache license and storage-retention review are required')
        approval='sha256:'+hashlib.sha256(json.dumps([approval,retention]).encode()).hexdigest()
    return SharedPSA(GCSStore(env['PSA_SHARED_BUCKET'],'psa-private/v1/'+scope+'.json'),namespace=namespace,
        window_start=env['PSA_QUOTA_START'],window_end=env['PSA_QUOTA_END'],limit=integer('PSA_QUOTA_LIMIT'),
        purchase_reserve=integer('PSA_PURCHASE_RESERVE'),cache_approval=approval,cache_seconds=cache_seconds)
