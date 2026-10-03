import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from scripts.derive_vision_card_facts import derive
from pokemon_index.number_evidence import inspection_tier
from tests import test_source_image_facts as fixtures
from pokemon_index import source_image_facts as facts

def line(text,x=0.2,y=0.62,confidence=1):
    return dict(text=text,confidence=confidence,box=[x,y,0.3,0.2])
def native(header,footer):
    return dict(regions=[dict(region='header',observations=header),dict(region='footer',observations=footer)])

class VisionExtractionTests(unittest.TestCase):
    def test_absent_hp_requires_recognized_non_pokemon_category(self):
        r=derive(native([line('Pikachu')],[line('025/198',y=0.2)]))
        self.assertEqual(r['title_text_parts'],['Pikachu']);self.assertEqual(r['hp_status'],'unreadable')
        r=derive(native([line("TRAINER'S",x=0.03,y=0.8),line('Rare Candy',y=0.45)],[]))
        self.assertEqual(r['title_text_parts'],['Rare Candy']);self.assertEqual(r['hp_status'],'absent')

    def test_unlabeled_hp_and_low_confidence_numbers_are_not_inferred(self):
        r=derive(native([line('H,60',x=0.74,confidence=0.3),line('フォレトスQK',confidence=0.3)],[line('006/150PR',y=0.2,confidence=0.3)]))
        self.assertEqual(r['title_text_parts'],[]);self.assertIsNone(r['hp']);self.assertIsNone(r['observed_number_text'])

    def test_literal_fraction_excludes_prefixes_and_ambiguous_multiple_values(self):
        for strings in [['TG03/TG30'],['AB003/190'],['3/190','4/190']]:
            r=derive(native([], [line(s,y=0.2) for s in strings]));self.assertIsNone(r['observed_number_text'])
        r=derive(native([line('HP270',x=0.7)],[line('G PAL EN 005/193 **',y=0.2)]))
        self.assertEqual(r['observed_number_text'],'005/193');self.assertEqual(r['hp'],270)

    def test_mechanic_missing_from_ocr_remains_missing_and_no_symbols_are_invented(self):
        r=derive(native([line('Forretress'),line('Evolves from Pineco',y=0.5)],[]))
        self.assertEqual(r['title_text_parts'],['Forretress']);self.assertEqual(r['title_symbols'],[])
        self.assertIsNone(r['title_furigana'])

    def test_ocr_is_never_reported_as_two_image_models(self):
        self.assertEqual(inspection_tier([dict(model_family='apple-vision-ocr'),dict(model_family='google')]),'ocr_and_image_model_screening')
        self.assertEqual(inspection_tier([dict(model_family='openai'),dict(model_family='google')]),'two_image_model_families')
        self.assertEqual(inspection_tier([dict(model_family='other'),dict(model_family='google')]),'separate_review_families')

class VisionTierIntegrationTests(unittest.TestCase):
    setUp = fixtures.SourceImageFactTests.setUp
    tearDown = fixtures.SourceImageFactTests.tearDown
    sign = fixtures.SourceImageFactTests.sign
    def test_mixed_method_counts_are_disclosed_and_do_not_approve_identity(self):
        r=copy.deepcopy(self.row);r['reviews'][0]['model_family']='apple-vision-ocr';self.sign(r)
        facts.import_evidence(self.db,[r]);c=facts.context(self.db,self.cid);status=facts.status(self.db)
        self.assertEqual(c['inspection_tier'],'ocr_and_image_model_screening')
        self.assertEqual(status['ocr_screening_source_fact_subjects'],1)
        self.assertEqual(status['two_image_model_source_fact_subjects'],0)
        for field in facts.FALSE_CLAIMS:self.assertFalse(c[field])

class ReviewAttemptLedgerTests(unittest.TestCase):
    def test_failed_remote_request_retains_image_bound_attempt_without_credentials(self):
        from scripts import review_source_image_facts as runner
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);image=p/'image.png';image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
            c=p/'cohort.jsonl';out=p/'reviews.jsonl'
            c.write_text(json.dumps(dict(target_id='fixture-1',image_path=str(image),
                source_ref='https://assets.tcgdex.net/en/sv/sv01/001/high.webp',
                image_sha256=hashlib.sha256(image.read_bytes()).hexdigest()))+'\n')
            with patch.object(runner.subprocess,'check_output',return_value='secret-fixture-token'), patch.object(runner,'_call_model',side_effect=TimeoutError('fixture timeout')):
                runner.run(c,out,'fixture-project','global',2)
            review=json.loads(out.read_text());attempt=json.loads(out.with_suffix('.attempts.jsonl').read_text())
            self.assertEqual(review['status'],'review_failed');self.assertEqual(review['attempt_id'],attempt['attempt_id'])
            self.assertEqual(review['image_sha256'],attempt['image_sha256'])
            self.assertFalse(json.loads(out.with_suffix('.protocol.json').read_text())['expected_catalog_text_supplied'])
            for f in p.glob('*.json*'):self.assertNotIn('secret-fixture-token',f.read_text())

    def test_unbounded_concurrency_is_rejected_before_credentials_or_files(self):
        from scripts import review_source_image_facts as runner
        with patch.object(runner.subprocess,'check_output') as credentials:
            for workers in [0,9,True]:
                with self.assertRaises(ValueError):runner.run(Path('missing'),Path('missing'),'fixture','global',workers)
            credentials.assert_not_called()
