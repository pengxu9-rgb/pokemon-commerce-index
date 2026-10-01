import copy
import json
import sqlite3
import unittest
from pathlib import Path

from pokemon_index import core, card_metadata, collector_discovery, collector_journey, supported_catalog, discovery_graph
from scripts.audit_japanese_metadata_batch import parse_page


class OfficialMetadataTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');core.init_db(self.db)
        seed=dict(language='ja',set_code='FIX',collector_number='001/100',variant='normal',name='ピカチュウ',
                  rarity=None,provenance='fixture:pinned',rights_reference='fixture',match_eligible=False,display_allowed=False)
        core.import_cards(self.db,[seed]);self.cid='ja:FIX:001/100:normal'
        core.import_card_references(self.db,[dict(source='ptcg-database',source_jp_id='123',set_code='FIX',
            collector_number='001/100',name='ピカチュウ',provenance='reference:pinned',rights_reference='fixture')])
        entry=dict(set_code='FIX',collector_number='001/100',part_role=None,rarity='C',rarity_status='recognized_icon',rarity_icons=['ic_rare_c_c.gif'])
        self.record=dict(schema='pokemon.official-card-metadata.v1',revision=1,status='source_supported',card_id=self.cid,
            identity=supported_catalog.identity_snapshot(self.db.execute('SELECT * FROM card').fetchone()),
            reference=dict(source='ptcg-database',native_id='123',name='ピカチュウ',provenance='reference:pinned'),
            official=dict(url='https://www.pokemon-card.com/card-search/details.php/card/123',page_sha256='a'*64,
                fetched_at='2026-10-01T00:00:00Z',name='ピカチュウ',numbered_entries=[entry],page_kind='single_number',
                illustrators=['Fixture Artist'],dex_id=25,**entry),**{k:False for k in card_metadata.FALSE_CLAIMS})
        self.sign(self.record)
    def sign(self,r):r['evidence_id']=card_metadata.event_id(r);return r
    def tearDown(self):self.db.close()

    def test_missing_facets_are_discoverable_without_enabling_commerce(self):
        card_metadata.import_evidence(self.db,[self.record])
        r=collector_discovery.execute(self.db,'Japanese Fixture Artist cards')
        self.assertEqual([c['card_id'] for c in r['cards']],[self.cid])
        self.assertEqual(r['cards'][0]['rarity'],'C');self.assertIsNone(r['cards'][0]['source_rarity'])
        self.assertFalse(r['cards'][0]['automatic_offer_join_allowed'])
        self.assertEqual(self.db.execute('SELECT rarity,match_eligible,display_allowed FROM card').fetchone()[:],(None,0,0))

    def test_conflicting_facet_is_excluded_and_additional_credit_is_allowed(self):
        core.import_card_facets(self.db,[dict(card_id=self.cid,facet_type='illustrator',value='Wrong Artist',provenance='seed',rights_reference='fixture')])
        card_metadata.import_evidence(self.db,[self.record])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM discovery_card_facet WHERE facet_type='illustrator'").fetchone()[0],0)
        self.assertEqual(card_metadata.context(self.db,self.cid)['facet_status']['illustrator'],'source_conflict')
        self.db.execute("UPDATE card_facet SET value='Fixture Artist'")
        second=copy.deepcopy(self.record);second['revision']=2;second['official']['illustrators'].append('Second Artist');self.sign(second)
        card_metadata.import_evidence(self.db,[second])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM discovery_card_facet WHERE facet_type='illustrator'").fetchone()[0],2)

    def test_source_drift_censors_metadata_facets_and_changes_journey_revision(self):
        card_metadata.import_evidence(self.db,[self.record]);before=collector_journey.catalog_revision(self.db)
        self.db.execute("UPDATE card_reference SET provenance='changed'")
        self.assertNotEqual(before,collector_journey.catalog_revision(self.db))
        self.assertEqual(card_metadata.context(self.db,self.cid)['status'],'stale_official_metadata')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM discovery_card_facet').fetchone()[0],0)

    def test_graph_uses_co_credits_without_claiming_counterpart_or_prices(self):
        record=copy.deepcopy(self.record);record['official']['illustrators'].append('Second Artist');self.sign(record)
        card_metadata.import_evidence(self.db,[record])
        core.import_cards(self.db,[dict(language='en',set_code='OTHER',collector_number='002/100',variant='normal',name='Other',provenance='fixture',rights_reference='fixture')])
        core.import_card_facets(self.db,[dict(card_id='en:OTHER:002/100:normal',facet_type='illustrator',value='Second Artist',provenance='fixture',rights_reference='fixture')])
        neighbors=discovery_graph.card_neighborhood(self.db,self.cid)
        self.assertEqual(neighbors['metadata_neighbors']['same_illustrator']['total'],1)
        self.assertEqual(neighbors['metadata_neighbors']['same_illustrator']['facet_values'],['Fixture Artist','Second Artist'])
        self.assertFalse(neighbors['metadata_neighbors']['same_illustrator']['price_comparable'])
        self.assertEqual(neighbors['relationships'],[])

    def test_official_evidence_change_invalidates_existing_journey_revision(self):
        card_metadata.import_evidence(self.db,[self.record]);before=collector_journey.catalog_revision(self.db)
        second=copy.deepcopy(self.record);second['revision']=2;second['official']['page_sha256']='b'*64;self.sign(second)
        card_metadata.import_evidence(self.db,[second])
        self.assertNotEqual(before,collector_journey.catalog_revision(self.db))

    def test_derived_view_change_invalidates_existing_journey_revision(self):
        before=collector_journey.catalog_revision(self.db)
        self.db.execute('DROP VIEW discovery_card_facet')
        self.db.execute('CREATE VIEW discovery_card_facet AS SELECT * FROM card_facet')
        self.assertNotEqual(before,collector_journey.catalog_revision(self.db))

    def test_forged_rarity_and_commerce_claim_roll_back(self):
        for mutate in [lambda r:r.update(automatic_offer_join_allowed=True),lambda r:r['official'].update(rarity='SAR')]:
            bad=copy.deepcopy(self.record);mutate(bad);self.sign(bad)
            with self.assertRaises(ValueError):card_metadata.import_evidence(self.db,[self.record,bad])
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM card_metadata_evidence').fetchone()[0],0)

    def test_numbered_parts_keep_membership_scope_and_block_copy_selection(self):
        parts=copy.deepcopy(self.record);parts['official']['page_kind']='numbered_parts'
        parts['official']['part_role']='左';parts['official']['numbered_entries'][0]['part_role']='左'
        other=copy.deepcopy(parts['official']['numbered_entries'][0]);other.update(collector_number='002/100',part_role='右')
        parts['official']['numbered_entries'].append(other);self.sign(parts)
        card_metadata.import_evidence(self.db,[parts])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM discovery_card_facet').fetchone()[0],0)
        request=dict(turns=[dict(type='ask',question='Japanese FIX 001/100 normal')])
        result=collector_journey.replay(self.db,request)
        self.assertIn('numbered_part_copy_evidence',result['selection_blockers']);self.assertFalse(result['selection_allowed'])

    def test_parser_keeps_two_numbered_parts_and_no_rarity_as_unknown(self):
        raw='''<h1 class="Heading1 mt20">ピカチュウ</h1><div class="subtext Text-fjalla">
        <img src="/card/regulation_logo_1/FIX.gif" alt="FIX" />&nbsp;001&nbsp;/&nbsp;100
        &nbsp;(左)<br/><img src="/card/regulation_logo_1/FIX.gif" alt="FIX" />&nbsp;002&nbsp;/&nbsp;100&nbsp;(右)</div>
        <div class="author"><h4>イラストレーター</h4><a href="/card-search/index.php?regulation_illust=all&illust=Fixture">Fixture</a></div>'''
        result=parse_page(raw.encode())
        self.assertEqual(result['page_kind'],'numbered_parts')
        self.assertEqual([x['part_role'] for x in result['numbered_entries']],['左','右'])
        self.assertTrue(all(x['rarity'] is None for x in result['numbered_entries']))

    def test_legacy_schema_migration_and_reinitialization_preserve_view(self):
        card_metadata.import_evidence(self.db,[self.record]);core.init_db(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM active_card_metadata_evidence').fetchone()[0],1)


if __name__=='__main__':unittest.main()
