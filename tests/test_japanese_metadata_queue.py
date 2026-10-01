import json
import tempfile
import unittest
from pathlib import Path
from pokemon_index import core
from scripts.prepare_japanese_metadata_queue import prepare


class JapaneseQueueTests(unittest.TestCase):
    def test_queue_excludes_covered_supported_multiversion_and_conflicting_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'baseline.sqlite3';db=core.connect(path);core.init_db(db)
            seeds=[];refs=[]
            for i in range(1,7):
                number=f'{i:03d}/100'
                seeds.append(dict(language='ja',set_code='FIX',collector_number=number,
                    variant='normal',name='ピカチュウ',provenance='fixture',rights_reference='fixture'))
                refs.append(dict(source='ptcg-database',source_jp_id=str(i),set_code='FIX',
                    collector_number=number,name='ピカチュウ' if i!=6 else 'ミュウ',
                    provenance='fixture',rights_reference='fixture'))
            core.import_cards(db,seeds);core.import_card_references(db,refs)
            db.execute("INSERT INTO card_metadata_evidence VALUES ('existing','ja:FIX:002/100:normal',1,'{}')")
            db.execute("INSERT INTO supported_card VALUES ('ja:FIX:003/100:normal','{}','fixture','catalog_discovery_and_listing_review')")
            core.import_cards(db,[dict(seeds[3],variant='holo')])
            core.import_card_references(db,[dict(refs[4],source_jp_id='50')])
            db.commit();db.close();manifest=root/'manifest.json';manifest.write_text('{}')
            output=root/'queue.jsonl';r=prepare(path,['FIX'],manifest,output)
            rows=[json.loads(l) for l in output.read_text().splitlines()]
            self.assertEqual([x['collector_number'] for x in rows],['001/100'])
            self.assertEqual(r['queued_set_number_groups'],1)
            self.assertEqual(set(r['exclusions']),{'already_official_metadata','original_supported_cohort',
                'multiple_source_versions','missing_or_multiple_references','reference_identity_conflict'})
            self.assertFalse(rows[0]['automatic_offer_join_allowed'])
            held=[json.loads(l) for l in output.with_suffix('.holds.jsonl').read_text().splitlines()]
            variant=next(r for r in held if r['reason']=='multiple_source_versions')
            self.assertEqual({r['variant'] for r in variant['catalog_records']},{'normal','holo'})
            name_conflict=next(r for r in held if r['reason']=='reference_identity_conflict')
            self.assertEqual(name_conflict['catalog_records'][0]['name'],'ピカチュウ')
            self.assertEqual(name_conflict['references'][0]['name'],'ミュウ')
            self.assertTrue(all(not r['automatic_offer_join_allowed'] for r in held))
            with self.assertRaises(FileExistsError):prepare(path,['FIX'],manifest,output)

    def test_release_cohort_cannot_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'queue.jsonl'
            with self.assertRaisesRegex(ValueError,'duplicate requested release'):
                prepare(Path('unused'),['FIX','FIX'],Path('unused'),p)
