"""Unverified certificate-number candidates from one retained listing's photos.

No PSA API, model service, arbitrary URL, image persistence, grading decision or
automatic certificate lookup. OCR numbers always require human confirmation.
"""
from __future__ import annotations
import hashlib
import os
import re
import ssl
import struct
import subprocess
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from .listing_evidence import photo_url
from .marketplace_crawl import _PinnedHTTPS, USER_AGENT

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 64000000


def dimensions(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)>=24:
        if data[12:16]!=b'IHDR':raise ValueError('unsupported image')
        return struct.unpack('>II',data[16:24])
    if data[:2]==b'\xff\xd8':
        p=2
        for _ in range(1000):
            if p+4>len(data) or data[p]!=255:break
            while p<len(data) and data[p]==255:p+=1
            marker=data[p];p+=1
            if marker in (0xD8,0xD9):continue
            length=int.from_bytes(data[p:p+2],'big')
            if length<2 or p+length>len(data):break
            if marker in (0xC0,0xC1,0xC2) and length>=7:
                h,w=struct.unpack('>HH',data[p+3:p+7]);return w,h
            p+=length
    raise ValueError('unsupported image')


def fetch_photo(url, *, source, budget, authorize):
    if photo_url(url,source) is None:raise ValueError('unbound image')
    authorize();budget.consume()
    parsed=urlsplit(url)
    deadline=time.monotonic()+6
    conn=_PinnedHTTPS(parsed.hostname,timeout=min(3,budget.check()),context=ssl.create_default_context())
    try:
        conn.connect();authorize();budget.check()
        if time.monotonic()>=deadline:raise TimeoutError('image deadline')
        conn.sock.settimeout(min(3,deadline-time.monotonic()))
        conn.request('GET',parsed.path,headers={'User-Agent':USER_AGENT,'Accept':'image/jpeg,image/png','Accept-Encoding':'identity'})
        read_socket=conn.sock
        response=conn.getresponse()
        if (response.status!=200 or response.getheader('Content-Encoding','identity')!='identity'
                or response.getheader('Content-Type','').split(';')[0] not in {'image/jpeg','image/png'}):raise ValueError('image unavailable')
        length=response.getheader('Content-Length')
        if length is not None and (not length.isascii() or not length.isdecimal() or int(length)>MAX_IMAGE_BYTES):raise ValueError('image too large')
        chunks=[];size=0
        while size<=MAX_IMAGE_BYTES:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('image deadline')
            read_socket.settimeout(min(1,remaining))
            part=response.read1(min(65536,MAX_IMAGE_BYTES+1-size))
            if not part:break
            chunks.append(part);size+=len(part)
        data=b''.join(chunks);budget.check()
        if len(data)>MAX_IMAGE_BYTES:raise ValueError('image too large')
        w,h=dimensions(data)
        if (not 1<=w<=16000 or not 1<=h<=16000 or w*h>MAX_IMAGE_PIXELS
                or data.startswith(b'\x89PNG') and w*h>16000000):raise ValueError('image dimensions too large')
        return data
    finally:conn.close()


def normalize_image(data):
    # JPEG shrink-on-load avoids handing full camera-resolution images to OCR.
    # No SVG/URL input: the transport already admitted only bounded JPEG/PNG.
    script="""const sharp=require('/app/creator/node_modules/sharp');sharp.cache(false);sharp.concurrency(1);let size=0,parts=[];
process.stdin.on('data',p=>{size+=p.length;if(size>8388608)process.exit(1);parts.push(p);});
process.stdin.on('end',async()=>{try{const out=await sharp(Buffer.concat(parts),{limitInputPixels:64000000,sequentialRead:true,failOn:'warning'}).rotate().resize({width:1800,height:2400,fit:'inside',withoutEnlargement:true,fastShrinkOnLoad:true}).flatten({background:'white'}).grayscale().png().toBuffer();if(out.length>8388608)process.exit(1);process.stdout.write(out);}catch{process.exitCode=1;}});"""
    value=subprocess.run(['/usr/local/bin/node','-e',script],input=data,stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,timeout=4,check=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','VIPS_CONCURRENCY':'1'})
    if len(value.stdout)>8388608:raise ValueError('normalized image too large')
    w,h=dimensions(value.stdout)
    if w>1800 or h>2400:raise ValueError('normalized image dimensions invalid')
    return value.stdout


def tesseract(data):
    data=normalize_image(data)
    # Fixed executable and arguments; image bytes go via stdin, never a shell.
    result=subprocess.run(['/usr/bin/tesseract','stdin','stdout','--psm','11','-l','eng','tsv'],
        input=data,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=3,check=True,
        env={'PATH':'/usr/bin:/bin','OMP_THREAD_LIMIT':'1'})
    if len(result.stdout)>262144:raise ValueError('OCR response too large')
    words=[]
    for line in result.stdout.decode('utf-8').splitlines()[1:5001]:
        fields=line.split('\t')
        if len(fields)!=12:continue
        try:confidence=float(fields[10])
        except ValueError:continue
        word=fields[11].strip()
        if re.fullmatch(r'[0-9]{7,12}',word) and 85<=confidence<=100:
            words.append((word,confidence))
    return words[:16]


class CertificateReader:
    def __init__(self, *, enabled=False, budget=None, fetch=fetch_photo, ocr=tesseract,
                 available=None, now=lambda:datetime.now(timezone.utc).isoformat()):
        self.enabled,self.budget,self.fetch,self.ocr,self.now=enabled,budget,fetch,ocr,now
        self.available=available if available is not None else lambda:os.path.isfile('/usr/bin/tesseract')
        self.lock=threading.Lock()

    def read(self, offer, *, authorize):
        now=self.now()
        result=dict(schema='pokemon.certificate-evidence.v1',offer_id=offer['offer_id'],source=offer['source'],
            native_id=offer['native_id'],listing_url=offer['url'],listing_observed_at=offer['observed_at'],
            checked_at=now,expires_at=offer['fresh_until'],status='number_not_read',candidates=[],
            psa_queried=False,certificate_verified=False,physical_authenticity_verified=False)
        if offer['grade']['company']!='PSA':
            result['status']='grade_not_psa';return result
        claim=offer.get('certificate_number_claim')
        if isinstance(claim,str) and re.fullmatch(r'[0-9]{7,12}',claim):
            result['candidates'].append(dict(number=claim,basis='seller_text',photo_url=None,
                evidence_ref=offer.get('evidence_ref') or 'seller-claimed-number',confidence=None,requires_confirmation=True))
        if not self.enabled or not self.available() or self.budget is None:
            result['status']='candidate_found' if result['candidates'] else 'ocr_unavailable';return result
        if not self.lock.acquire(blocking=False):result['status']='ocr_busy';return result
        deadline=time.monotonic()+18
        try:
            for photo in (offer.get('listing_photos') or [])[:2]:
                if time.monotonic()+10>deadline:break
                try:
                    authorize(photo['url'])
                    data=self.fetch(photo['url'],source=offer['source'],budget=self.budget,authorize=lambda:authorize(photo['url']))
                    digest='photo-ocr:sha256:'+hashlib.sha256(data).hexdigest()
                    if time.monotonic()>=deadline:break
                    for number,confidence in self.ocr(data):
                        if (not isinstance(number,str) or not re.fullmatch(r'[0-9]{7,12}',number)
                                or type(confidence) not in (float,int) or not 85<=confidence<=100):continue
                        result['candidates'].append(dict(number=number,basis='photo_ocr',photo_url=photo['url'],
                            evidence_ref=digest,confidence=confidence,requires_confirmation=True))
                        if len(result['candidates'])>=8:break
                except Exception:continue
                if len(result['candidates'])>=8:break
        finally:self.lock.release()
        numbers={c['number'] for c in result['candidates']}
        result['status']='number_conflict' if len(numbers)>1 else 'candidate_found' if numbers else 'number_not_read'
        return result
