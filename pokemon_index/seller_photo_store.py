"""Private, in-memory, pre-ingested listing-photo delivery. Never fetches URLs.

This adapter is disabled unless server code explicitly inserts authorized bytes.
Authorization records bind the exact owner's offer, source evidence, bytes, and
expiry. It only accepts a narrow static PNG subset and re-encodes image data;
no catalog artwork or user-supplied network endpoint is a substitute.
"""
from __future__ import annotations

import copy
import hashlib
import secrets
import struct
import zlib
from datetime import datetime, timezone

MAX_BYTES = 2 * 1024 * 1024
MAX_DIMENSION = 1024
MAX_IMAGES = 64
MAX_TOTAL_BYTES = 16 * 1024 * 1024
PREFIX = '/api/creator/pokemon/seller-photo/'


def _time(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('invalid timestamp')
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('timezone required')
    return t.astimezone(timezone.utc)


def _chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def sanitize_png(data):
    """Decode/verify a bounded static RGB/RGBA PNG and remove metadata."""
    if not isinstance(data, bytes) or not 57 <= len(data) <= MAX_BYTES or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('unsupported image')
    position, ihdr, parts, finished = 8, None, [], False
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError('truncated PNG')
        size = struct.unpack('>I', data[position:position+4])[0]
        kind = data[position+4:position+8]
        end = position + 12 + size
        if size > MAX_BYTES or end > len(data):
            raise ValueError('oversized PNG chunk')
        body = data[position+8:position+8+size]
        crc = struct.unpack('>I', data[position+8+size:end])[0]
        if crc != zlib.crc32(kind + body) & 0xffffffff:
            raise ValueError('invalid PNG checksum')
        if kind == b'IHDR' and ihdr is None and not parts and position == 8 and size == 13:
            ihdr = body
        elif kind == b'IDAT' and ihdr is not None and not finished:
            parts.append(body)
        elif kind == b'IEND' and ihdr is not None and parts and size == 0:
            finished = True
            if end != len(data):
                raise ValueError('PNG trailing bytes forbidden')
        else:
            # Reject all metadata, palettes, animation and unknown extensions.
            raise ValueError('unsupported PNG structure')
        position = end
        if finished:
            break
    if not finished or ihdr is None:
        raise ValueError('incomplete PNG')
    width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', ihdr)
    if (not 1 <= width <= MAX_DIMENSION or not 1 <= height <= MAX_DIMENSION
            or depth != 8 or color not in (2, 6) or compression or filtering or interlace):
        raise ValueError('unsupported PNG dimensions or format')
    row_length = 1 + width * (3 if color == 2 else 4)
    expected = row_length * height
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(b''.join(parts), expected + 1)
    except zlib.error as exc:
        raise ValueError('invalid PNG compression') from exc
    if len(decoded) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('invalid PNG data length')
    if any(decoded[i * row_length] > 4 for i in range(height)):
        raise ValueError('invalid PNG filter')
    sanitized = b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', ihdr) + _chunk(b'IDAT', zlib.compress(decoded, 9)) + _chunk(b'IEND', b'')
    if len(sanitized) > MAX_BYTES:
        raise ValueError('image exceeds limit')
    return sanitized


def _displayable_listing(offer):
    """Keep sold observations, reject withdrawn or contradictory stock states."""
    state, availability = offer.get('listing_status'), offer.get('availability')
    if offer.get('scope') != 'listing' or state not in {'on_sale','sold_out','unknown'} or availability not in {'available','sold_out','unknown'}:
        return False
    if state == 'sold_out' and availability != 'sold_out':
        return False
    if state == 'on_sale' and availability == 'sold_out':
        return False
    return True


def _binding(owner, offer_id, offer, photo):
    return {'owner': owner, 'offer_id': offer_id, 'source': offer['source'],
            'listing_id': offer['native_id'], 'listing_url': offer['url'],
            'offer_observed_at': offer['observed_at'], 'photo_url': photo['url'],
            'evidence_ref': photo['evidence_ref'], 'observed_at': photo['observed_at'],
            'role': photo['role']}


class SellerPhotoStore:
    """A bounded server-owned store. No ingestion HTTP endpoint is provided."""
    def __init__(self, authorizer=None):
        if authorizer is not None and not callable(authorizer):
            raise ValueError("photo authorizer must be a server-owned callable")
        self._authorizer = authorizer
        self._records = {}

    def _approved(self, approval, binding):
        if self._authorizer is None:
            return False
        try:
            return self._authorizer(copy.deepcopy(approval), copy.deepcopy(binding)) is True
        except Exception:
            return False

    def put_authorized(self, owner, offer_id, offer, photo_index, data, approval, now):
        photos = offer.get('listing_photos')
        if not isinstance(photos, list) or type(photo_index) is not int or not 0 <= photo_index < len(photos):
            raise ValueError('photo not bound to this listing')
        photo = photos[photo_index]
        if (not _displayable_listing(offer) or not offer.get('evidence_ref')
                or photo.get('evidence_ref') != offer['evidence_ref']
                or _time(photo.get('observed_at')) != _time(offer['observed_at'])):
            raise ValueError('current exact-listing evidence required')
        binding = _binding(owner, offer_id, offer, photo)
        required = {'owner','offer_id','source','listing_id','listing_url','offer_observed_at','photo_url',
                    'evidence_ref','observed_at','role','input_sha256','grant_id','permitted_use','expires_at'}
        if not isinstance(approval, dict) or set(approval) != required:
            raise ValueError('exact reviewed authorization required')
        if any(approval[k] != v for k,v in binding.items()) or photo['listing_url'] != offer['url']:
            raise ValueError('authorization does not match exact listing')
        if (approval['permitted_use'] != 'private_offer_comparison' or not isinstance(approval['grant_id'], str)
                or not 1 <= len(approval['grant_id']) <= 200 or any(ord(c) < 33 or ord(c) > 126 for c in approval['grant_id'])
                or not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != approval['input_sha256']
                or _time(approval['expires_at']) <= _time(now) or _time(offer['fresh_until']) <= _time(now)
                or _time(photo['observed_at']) > _time(offer['observed_at']) or _time(offer['observed_at']) > _time(now)):
            raise ValueError('photo authorization expired or invalid')
        if (not self._approved(approval, binding) or offer.get('listing_status') == 'gone'):
            raise ValueError('photo display not authorized')
        clean = sanitize_png(data)
        expires = min(_time(offer['fresh_until']), _time(approval['expires_at']))
        for old_token, record in list(self._records.items()):
            if record['expires_at'] <= _time(now) or not self._approved(record['approval'], record['binding']):
                del self._records[old_token]
                continue
            if record['binding'] == binding:
                if record['bytes'] == clean and record['approval'] == approval and record['expires_at'] == expires:
                    return old_token
                # New grant or different bytes replace this exact image binding.
                del self._records[old_token]
        if (len(self._records) >= MAX_IMAGES or sum(len(r['bytes']) for r in self._records.values()) + len(clean) > MAX_TOTAL_BYTES
                or sum(r['binding']['owner'] == owner and r['binding']['offer_id'] == offer_id for r in self._records.values()) >= 8):
            raise ValueError('photo store capacity exceeded')
        token = secrets.token_hex(32)
        self._records[token] = {'binding': binding, 'expires_at': expires,
                                'bytes': clean, 'grant_id': approval['grant_id'], 'approval': copy.deepcopy(approval)}
        return token

    def _live(self, token, owner, offer_id, offer, now):
        record = self._records.get(token)
        if (not record or record['expires_at'] <= _time(now) or _time(offer['fresh_until']) <= _time(now)
                or not _displayable_listing(offer)
                or not offer.get('evidence_ref') or record['binding']['evidence_ref'] != offer['evidence_ref']
                or _time(record['binding']['observed_at']) != _time(offer['observed_at'])
                or record['binding']['owner'] != owner or record['binding']['offer_id'] != offer_id):
            return None
        if not self._approved(record['approval'], record['binding']):
            return None
        photos = offer.get('listing_photos', [])
        if not any(_binding(owner, offer_id, offer, photo) == record['binding'] for photo in photos):
            return None
        return record

    def manifest(self, owner, offer_id, offer, now):
        rows = []
        for token in list(self._records):
            record = self._live(token, owner, offer_id, offer, now)
            if not record:
                continue
            b = record['binding']
            rows.append({'media_path': PREFIX + token, 'role':'listing_photo', 'source':b['source'],
                         'listing_id':b['listing_id'], 'listing_url':b['listing_url'],
                         'evidence_ref':b['evidence_ref'], 'observed_at':offer['observed_at']})
        return {'state':'available', 'items':rows} if rows else {'state':'unavailable', 'reason': 'delivery_unavailable' if offer.get('listing_photos') else 'not_received'}

    def get(self, token, owner, offer_id, offer, now):
        record = self._live(token, owner, offer_id, offer, now)
        if not record:
            raise KeyError('photo unavailable')
        return bytes(record['bytes'])

    def token_binding(self, token):
        record = self._records.get(token)
        return copy.deepcopy(record['binding']) if record else None

    def revoke_grant(self, grant_id):
        for token, record in list(self._records.items()):
            if record['grant_id'] == grant_id:
                del self._records[token]
