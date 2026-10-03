import copy,json,unittest
from pokemon_index import core,number_evidence as n,source_image_facts as f,source_mechanic as m,supported_catalog as s
class SourceMechanicTests(unittest.TestCase):
 def setUp(self):
  self.db=core.connect(':memory:');core.init_db(self.db)
  core.import_cards(self.db,[dict(language='ja',set_code='SM12A',collector_number='011/173',variant=v,name='シェイミ',rarity='None',provenance='tcgdex:'+('a'*40)+':data/test.ts:sha256:'+('b'*64),rights_reference='fixture',match_eligible=True) for v in ['normal','holo']])
  self.cid='ja:SM12A:011/173:normal';snap=n.snapshot(self.db,self.cid);src='https://www.pokemon-card.com/card-search/details.php/card/37215'
  self.ref=dict(source='ptcg-database',native_id='37215',name='シェイミprismstar',provenance='fixture')
  core.import_card_references(self.db,[self.ref|dict(source_jp_id=37215,set_code='SM12A',collector_number='011/173',rights_reference='fixture')])
  reading=dict(title_text_parts=['シェイミ'],title_symbols=[dict(kind='prism_star',after_text_part=0)],title_furigana=None,observed_number_text='011/173',hp=80,hp_status='visible',notes='fixture')
  reviews=[dict(actor=a,model_family=family,model_version=None,reviewed_at='2026-10-03T00:00:00Z',review_record_sha256=h*64,source_ref=src,image_sha256='c'*64,prior_verdicts_visible=False,expected_catalog_context_visible=False,reading=copy.deepcopy(reading)) for a,family,h in [('first','openai','d'),('second','google','e')]]
  self.fact=dict(schema=f.SCHEMA,revision=1,card_id=self.cid,endpoint_snapshot=snap,identity_sha256=s.digest(snap),source_ref=src,image_sha256='c'*64,source_file_sha256='b'*64,pinned_source_hp=80,cohort_snapshot_sha256='f'*64,reviews=reviews,recorded_at='2026-10-03T00:01:00Z',**{k:False for k in f.FALSE_CLAIMS});self.fact['event_id']=f.event_id(self.fact);f.import_evidence(self.db,[self.fact])
  self.row=dict(schema=m.SCHEMA,revision=1,card_id=self.cid,endpoint_snapshot=snap,identity_sha256=s.digest(snap),source_fact_event_id=self.fact['event_id'],source_fact_sha256=s.digest(self.fact),reference=self.ref,official=dict(url=src,page_sha256='1'*64,fetched_at='2026-10-03T00:02:00Z',name='シェイミ',set_code='SM12A',collector_number='011/173',title_symbol='prism_star',special_rule='prism_star',page_kind='single_number'),mechanic='prism_star',recorded_at='2026-10-03T00:03:00Z',**{k:False for k in m.FALSE_CLAIMS});self.sign(self.row)
 def sign(self,r):r['event_id']=m.event_id(r);return r
 def tearDown(self):self.db.close()
 def test_official_binding_is_advisory_exact_and_idempotent(self):
  m.import_evidence(self.db,[self.row,self.row]);ctx=f.context(self.db,self.cid);bound=ctx['source_mechanic_binding']
  self.assertTrue(bound['current_endpoint_and_fact']);self.assertEqual(bound['status'],'official_coordinate_mechanic_supported')
  self.assertEqual(ctx['name_status'],'unconfirmed');self.assertFalse(ctx['number_reading_qualification_changed'])
  self.assertIsNone(f.context(self.db,'ja:SM12A:011/173:holo'))
  self.assertEqual(m.status(self.db)['source_mechanic_binding_events'],1)
  for k in m.FALSE_CLAIMS:self.assertIs(bound[k],False)
 def test_wrong_coordinate_source_mechanic_and_backdating_rejected(self):
  for change in [lambda r:r['official'].update(collector_number='012/173'),lambda r:r['official'].update(url='https://www.pokemon-card.com/card-search/details.php/card/37216'),lambda r:r['official'].update(title_symbol='ordinary'),lambda r:r['official'].update(special_rule='ordinary'),lambda r:r.update(recorded_at='2026-10-03T00:00:00Z')]:
   r=copy.deepcopy(self.row);change(r);self.sign(r)
   with self.assertRaises(ValueError):m.import_evidence(self.db,[r])
 def test_changed_fact_hash_or_reference_cannot_bind(self):
  for change in [lambda r:r.update(source_fact_sha256='2'*64),lambda r:r.update(source_fact_event_id='missing'),lambda r:r['reference'].update(provenance='different')]:
   r=copy.deepcopy(self.row);change(r);self.sign(r)
   with self.assertRaises(ValueError):m.import_evidence(self.db,[r])
 def test_new_fact_head_invalidates_and_cannot_transfer_binding(self):
  m.import_evidence(self.db,[self.row]);fact=copy.deepcopy(self.fact);fact.update(revision=2,recorded_at='2026-10-03T00:04:00Z');fact['event_id']=f.event_id(fact);f.import_evidence(self.db,[fact])
  ctx=m.context(self.db,self.cid);self.assertEqual(ctx['status'],'stale_binding');self.assertIsNone(ctx['official'])
  self.assertEqual(m.status(self.db)['stale_source_mechanic_bindings'],1)
  r=copy.deepcopy(self.row);r.update(revision=2,recorded_at='2026-10-03T00:05:00Z');self.sign(r)
  with self.assertRaises(ValueError):m.import_evidence(self.db,[r])
 def test_unagreed_or_unknown_image_symbol_rejected(self):
  fact=copy.deepcopy(self.fact);fact.update(revision=2);fact['reviews'][1]['reading']['title_symbols'][0]['kind']='unknown';fact['event_id']=f.event_id(fact);f.import_evidence(self.db,[fact])
  r=copy.deepcopy(self.row);r.update(source_fact_event_id=fact['event_id'],source_fact_sha256=s.digest(fact));self.sign(r)
  with self.assertRaises(ValueError):m.import_evidence(self.db,[r])
 def test_positive_commerce_flag_rolls_back_whole_import(self):
  bad=copy.deepcopy(self.row);bad.update(revision=2,price_comparable=True);self.sign(bad)
  with self.assertRaises(ValueError):m.import_evidence(self.db,[self.row,bad])
  self.assertEqual(m.status(self.db)['source_mechanic_binding_events'],0)
 def test_product_assets_have_narrow_official_paths(self):
  n._source('https://www.30th.pokemon-card.com/images/m6a/cards/m6a_104_wtwf8lme.png')
  for url in ['https://www.30th.pokemon-card.com/images/m6a/cards/m6a_151152_49uhte7p.png','https://30th.pokemon-card.com/images/m6a/cards/m6a_104_wtwf8lme.png','https://www.30th.pokemon-card.com/images/m6a/cards/m6a_104_wtwf8lme.png?price=1','https://www.30th.pokemon-card.com/images/m6a/cards/../m6a_104_wtwf8lme.png']:
   with self.assertRaises(ValueError):n._source(url)
 def test_journey_revision_binds_mechanic_evidence(self):
  from pokemon_index import collector_journey
  before=collector_journey.catalog_revision(self.db);m.import_evidence(self.db,[self.row]);after=collector_journey.catalog_revision(self.db)
  self.assertNotEqual(before,after)
  m.import_evidence(self.db,[self.row]);self.assertEqual(after,collector_journey.catalog_revision(self.db))
