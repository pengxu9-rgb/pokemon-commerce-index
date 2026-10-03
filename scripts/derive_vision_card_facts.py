"""Conservative image-only OCR observations, never catalog-informed labels.

The native program accepts only target id, image path and recognition language.
Freeze its input/protocol before execution; derive observations before the second
reader runs. Confidence is the engine output, not calibrated card accuracy.
"""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from pokemon_index.source_image_facts import validate_reading

MIN_CONFIDENCE = 0.5
FRACTION = re.compile(r'(?<![A-Za-z0-9])\d{1,6}\s*/\s*\d{1,6}(?![A-Za-z0-9])')
CATEGORIES = {"TRAINER'S", 'TRAINERS', 'トレーナーズ', 'ENERGY', 'エネルギー'}
EXCLUDED = CATEGORIES | {'ITEM', 'SUPPORTER', 'STADIUM', 'サポート', 'グッズ', 'スタジアム', 'ポケモンのどうぐ'}

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, rows):
    with path.open('x') as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False, sort_keys=True)+'\n')

def derive(ocr):
    """Only literal confident OCR lines; ambiguous fields remain unreadable."""
    regions = {r['region']:r['observations'] for r in ocr['regions']}
    header = [o for o in regions['header'] if o['confidence'] >= MIN_CONFIDENCE]
    category = any(o['text'].strip().upper() in CATEGORIES for o in header)
    title = []
    for o in header:
        x,y,w,h = o['box']; t=o['text'].strip()
        if t.upper() in EXCLUDED or re.search(r'\bHP\s*\d',t,re.I): continue
        if t.startswith(('Evolves from ', 'このポケモン', 'As long as ')) or 'から進化' in t: continue
        # Coordinates are relative to the native ROI, not full card coordinates.
        if 0.14 <= x < 0.66 and y+h/2 >= (0.40 if category else 0.63):
            title.append(o)
    title.sort(key=lambda o:(-round(o['box'][1]+o['box'][3]/2,1),o['box'][0]))
    hp_values=set()
    for o in header:
        if o['box'][0] < 0.66: continue
        m=re.fullmatch(r'HP\s*(\d{1,4})',o['text'].strip(),re.I)
        if m and 0<int(m[1])<10000: hp_values.add(int(m[1]))
    hp=next(iter(hp_values)) if len(hp_values)==1 else None
    # Absence only for an explicitly recognized trainer/energy header.
    hp_status='visible' if hp is not None else ('absent' if category and not hp_values else 'unreadable')
    fractions=set()
    for o in regions['footer']:
        x,y,w,h=o['box']
        if o['confidence']<MIN_CONFIDENCE or y+h/2>=0.60: continue
        fractions.update(m[0] for m in FRACTION.finditer(o['text']))
    reading=dict(title_text_parts=[o['text'].strip() for o in title],title_symbols=[],title_furigana=None,
        observed_number_text=next(iter(fractions)) if len(fractions)==1 else None,
        hp=hp,hp_status=hp_status,
        notes='Apple Vision OCR initial screening; confidence >=0.5, fixed header/footer ROIs. '
              'Symbols, furigana, unclear mechanics, missing denominators and unlabeled HP are not inferred. '
              'Native confidence is not a calibrated accuracy score.')
    validate_reading(reading)
    return reading

def prepare(cohort, inputs, protocol, binary):
    rows=list(map(json.loads,cohort.read_text().splitlines()))
    if len({r['target_id'] for r in rows})!=len(rows): raise ValueError('duplicate cohort')
    input_rows=[]
    for c in rows:
        if sha(Path(c['image_path']))!=c['image_sha256']: raise ValueError('image drift')
        input_rows.append(dict(target_id=c['target_id'],image_path=c['image_path'],language=c['endpoint_snapshot']['language']))
    write(inputs,input_rows)
    p=dict(schema='pokemon.apple-vision-image-only-protocol.v1',cohort_sha256=sha(cohort),
        input_sha256=sha(inputs),swift_source_sha256=sha(Path(__file__).with_name('vision_card_ocr.swift')),
        binary_sha256=sha(binary),derivation_script_sha256=sha(Path(__file__)),subjects=len(rows),
        minimum_engine_confidence=MIN_CONFIDENCE,expected_catalog_text_supplied=False,previous_verdicts_supplied=False,
        recognition_language_from_catalog=True,custom_words=[],language_correction=False,
        methods=['apple_vision_ocr','deterministic_literal_extraction'],
        independent_image_model_review=False,independent_ground_truth_established=False)
    with protocol.open('x') as f:f.write(json.dumps(p,indent=2)+'\n')
    return p

def compile(cohort, inputs, protocol, raw, output):
    p=json.loads(protocol.read_text())
    if p['cohort_sha256']!=sha(cohort) or p['input_sha256']!=sha(inputs) or p['derivation_script_sha256']!=sha(Path(__file__)):
        raise ValueError('frozen OCR inputs or derivation changed')
    rows=list(map(json.loads,cohort.read_text().splitlines()));native=list(map(json.loads,raw.read_text().splitlines()))
    if len(native)!=len(rows) or len({r['target_id'] for r in native})!=len(native):raise ValueError('incomplete native observations')
    keyed={r['target_id']:r for r in native}
    if set(keyed)!={r['target_id'] for r in rows}:raise ValueError('native cohort differs')
    out=[]
    for c in rows:
        n=keyed[c['target_id']]
        if sha(Path(c['image_path']))!=c['image_sha256']:raise ValueError('image drift')
        r=dict(schema='pokemon.source-image-fact-inspection.v1',target_id=c['target_id'],
            actor='local:apple-vision-ocr:card-facts-v1',model_family='apple-vision-ocr',
            model_version='VNRecognizeTextRequestRevision3',source_ref=c['source_ref'],image_sha256=c['image_sha256'],
            expected_catalog_context_visible=False,prior_verdicts_visible=False,reviewed_at=n['reviewed_at'],
            protocol_sha256=sha(protocol),native_output_file_sha256=sha(raw),native_observation=n,
            status='review_failed',reading=None,inspection_method='ocr_initial_screening')
        if n['status']=='recognized':
            if n['ocr']['language']!=c['endpoint_snapshot']['language'] or n['ocr']['custom_words'] or n['ocr']['language_correction']:
                raise ValueError('native recognition configuration differs')
            r.update(status='reviewed',reading=derive(n['ocr']),model_version=f"Vision revision {n['ocr']['revision']}; {n['ocr']['os']}")
        out.append(r)
    write(output,out)
    return dict(subjects=len(out),recognized=sum(r['status']=='reviewed' for r in out),independent_image_model_review=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prepare','compile'])
    for k in ['cohort','inputs','protocol']:p.add_argument('--'+k,type=Path,required=True)
    for k in ['binary','raw','output']:p.add_argument('--'+k,type=Path)
    a=p.parse_args()
    result=prepare(a.cohort,a.inputs,a.protocol,a.binary) if a.mode=='prepare' else compile(a.cohort,a.inputs,a.protocol,a.raw,a.output)
    print(json.dumps(result))
