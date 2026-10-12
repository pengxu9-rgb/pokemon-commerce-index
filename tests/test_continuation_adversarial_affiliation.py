"""Independent hard-constraint/currentness probes for the 21 added source pins."""
import unittest

from pokemon_index import collector_character_affiliation as affiliation
from pokemon_index import collector_recommendation as recommendation
import test_character_affiliation_gap_evidence as fixture


class ContinuationAffiliationReview(unittest.TestCase):
    def setUp(self):
        self.db, self.receipt = fixture.source_fixture()

    def tearDown(self):
        self.db.close()

    def test_every_new_species_hard_exclusion_overrides_release_and_liked_origin(self):
        for dex in {t['expected_derived_dex_id'] for t in self.receipt['targets']}:
            excluded = {t['card_id'] for t in self.receipt['targets'] if t['expected_derived_dex_id'] == dex}
            profile = {'preferred_releases': [{'language': 'ja', 'set_code': 'SV4A'}],
                       'excluded_dex_ids': [dex]}
            with self.subTest(dex=dex):
                result = recommendation.recommend(self.db, 'What should I collect next?', profile,
                    {cid: 'like' for cid in excluded}, scope={'language': 'ja', 'set_code': 'SV4A'}, limit=50)
                self.assertFalse(excluded.intersection(c['card_id'] for c in result['cards']))
                self.assertFalse(result['scope']['public_display_allowed'])
                self.assertEqual(result['scope']['prices'], [])

    def test_unknown_after_anchor_rights_drift_cannot_reenter_through_release_preference(self):
        target = self.receipt['targets'][0]
        expected = {t['card_id'] for t in self.receipt['targets']
                    if t['base_name_ja'] == target['base_name_ja']}
        cache = {'revision': 'a'*64}
        profile = {'preferred_releases': [{'language': 'ja', 'set_code': 'SV4A'}],
                   'excluded_dex_ids': [target['expected_derived_dex_id']]}
        before = recommendation.recommend(self.db, 'What should I collect next?', profile, {},
            scope={'set_code': 'SV4A'}, limit=50, pool_cache=cache)
        self.assertFalse(expected.intersection(c['card_id'] for c in before['cards']))
        self.db.execute('UPDATE card_facet SET rights_reference=? WHERE card_id IN '
                        '(SELECT card_id FROM card WHERE name=?)',
                        ('stale:rights', target['base_name_ja']))
        after = recommendation.recommend(self.db, 'What should I collect next?', profile, {},
            scope={'set_code': 'SV4A'}, limit=50, pool_cache=cache)
        self.assertFalse(expected.intersection(c['card_id'] for c in after['cards']))
        self.assertEqual(after['scope']['coverage']['exclusion_unknown_membership_withheld'], len(expected))
        self.assertFalse(expected.intersection(affiliation.affiliations(self.db)))

    def test_current_conflict_withdraws_all_new_targets_for_each_base_name(self):
        initial = set(affiliation.affiliations(self.db))
        for name in {t['base_name_ja'] for t in self.receipt['targets']}:
            affected = {t['card_id'] for t in self.receipt['targets'] if t['base_name_ja'] == name}
            anchor = self.db.execute('SELECT f.* FROM card_facet f JOIN card c ON c.card_id=f.card_id '
                                    "WHERE c.name=? AND f.facet_type='dex_id' LIMIT 1", (name,)).fetchone()
            self.db.execute('SAVEPOINT review_conflict')
            try:
                self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',
                    (anchor['card_id'], 'dex_id', '1025', anchor['provenance'], anchor['rights_reference']))
                self.assertEqual(set(affiliation.affiliations(self.db)), initial-affected, name)
            finally:
                self.db.execute('ROLLBACK TO review_conflict')
                self.db.execute('RELEASE review_conflict')

    def test_target_support_and_source_drift_each_withdraw_exact_pin(self):
        initial = set(affiliation.affiliations(self.db))
        for cid in initial:
            for field in ['provenance', 'name']:
                self.db.execute('SAVEPOINT review_target')
                try:
                    self.db.execute('UPDATE card SET '+field+'=? WHERE card_id=?', ('changed', cid))
                    self.assertEqual(set(affiliation.affiliations(self.db)), initial-{cid})
                finally:
                    self.db.execute('ROLLBACK TO review_target')
                    self.db.execute('RELEASE review_target')


if __name__ == '__main__':
    unittest.main()
