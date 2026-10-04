"""Independent mixed-view proof/currentness checks after the 738 CI failure."""
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from pokemon_index import collector_character_affiliation as affiliation, collector_recommendation as recommendation, core
import test_affiliation_runtime_scaling as fixture


class EffectiveAffiliationReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'effective.sqlite3'
        self.fixture = fixture.build_fixture(self.path, total=160, metadata_count=64)
        self.db = core.connect(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def derive(self):
        with fixture.synthetic_support(self.fixture):
            return affiliation.affiliations(self.db)

    def test_mixed_official_and_raw_proofs_are_complete_and_group_local(self):
        first = self.derive()
        self.assertEqual(len(first), 27)
        for value in first.values():
            self.assertEqual(value['reason']['anchor_count'], 2)
        name = self.fixture['names'][0]
        affected = {b['card_id'] for b in self.fixture['bindings'] if b['base_name_ja'] == name}
        # Withdraw all source-current rights for one exact name, leaving other
        # names' official and raw evidence intact in the same batched statement.
        self.db.execute('UPDATE card_classification SET rights_reference=? WHERE card_id IN '
                        '(SELECT card_id FROM card WHERE name=?)', ('stale:rights', name))
        second = self.derive()
        self.assertEqual(set(second), set(first)-affected)
        self.assertEqual(second, {cid: value for cid, value in first.items() if cid not in affected})

    def test_stale_official_overlay_falls_back_to_current_raw_with_same_species(self):
        first = self.derive()
        name = self.fixture['names'][0]
        target = next(cid for cid, value in first.items() if value['reason']['base_name_ja'] == name)
        anchor = first[target]['reason']['anchor_evidence'][0]
        self.assertNotEqual(anchor['provenance'], self.db.execute('SELECT provenance FROM card WHERE card_id=?',
                            (anchor['card_id'],)).fetchone()[0])
        self.db.execute('UPDATE card_reference SET provenance=? WHERE set_code=(SELECT set_code FROM card WHERE card_id=?) '
                        'AND collector_number=(SELECT collector_number FROM card WHERE card_id=?)',
                        ('stale:reference', anchor['card_id'], anchor['card_id']))
        second = self.derive()[target]
        self.assertEqual(second['dex_id'], first[target]['dex_id'])
        self.assertEqual(second['reason']['anchor_count'], 2)
        current = self.db.execute('SELECT provenance,rights_reference FROM card WHERE card_id=?', (anchor['card_id'],)).fetchone()
        self.assertEqual(second['reason']['anchor_evidence'][0]['provenance'], current['provenance'])
        self.assertEqual(second['reason']['anchor_evidence'][0]['rights_reference'], current['rights_reference'])
        self.assertNotEqual(second['reason']['anchor_evidence_sha256'], first[target]['reason']['anchor_evidence_sha256'])

    def test_current_conflict_in_one_name_never_borrows_other_group_consensus(self):
        first = self.derive()
        name = self.fixture['names'][0]
        affected = {cid for cid, value in first.items() if value['reason']['base_name_ja'] == name}
        raw = self.db.execute("SELECT f.* FROM card_facet f JOIN card c ON c.card_id=f.card_id WHERE c.name=? "
                              "AND f.facet_type='dex_id' ORDER BY c.card_id DESC LIMIT 1", (name,)).fetchone()
        self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',
                        (raw['card_id'], 'dex_id', '999', raw['provenance'], raw['rights_reference']))
        self.assertEqual(set(self.derive()), set(first)-affected)

    def test_direct_current_target_facet_removes_only_exact_target(self):
        first = self.derive()
        target = self.fixture['bindings'][0]
        self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',
                        (target['card_id'], 'dex_id', '999', target['source_ref'], target['target_rights_reference']))
        second = self.derive()
        self.assertEqual(second, {cid: value for cid, value in first.items() if cid != target['card_id']})

    def test_unapplied_notes_never_hide_evidence_changes_in_reused_pool(self):
        first_affiliations = self.derive()
        cid, proof = next(iter(first_affiliations.items()))
        profile = {'preferred_dex_ids': [proof['dex_id']], 'subjective_notes': ['cozy']}
        cache = {'revision': 'a'*64}
        with fixture.synthetic_support(self.fixture):
            first = recommendation.recommend(self.db, 'Recommend Japanese cards', profile, {}, pool_cache=cache)
            pool = cache['pool']
            self.assertIn(cid, [c['card_id'] for c in first['cards']])
            profile['subjective_notes'] = ['peaceful']
            same = recommendation.recommend(self.db, 'Recommend Japanese cards', profile, {}, pool_cache=cache)
            self.assertIs(cache['pool'], pool)
            self.assertEqual(same['recommendation']['unapplied_preferences'][0]['value'], 'peaceful')
            self.assertEqual(first['recommendation']['unapplied_preferences'][0]['value'], 'cozy')
            self.db.execute('UPDATE card_classification SET rights_reference=? WHERE card_id IN '
                            '(SELECT card_id FROM card WHERE name=?)',
                            ('stale:rights', proof['reason']['base_name_ja']))
            after = recommendation.recommend(self.db, 'Recommend Japanese cards', profile, {}, pool_cache=cache)
            self.assertIsNot(cache['pool'], pool)
            self.assertNotIn(cid, [c['card_id'] for c in after['cards']])
            self.assertEqual(after, recommendation.recommend(self.db, 'Recommend Japanese cards', profile, {}))


if __name__ == '__main__':
    unittest.main()
