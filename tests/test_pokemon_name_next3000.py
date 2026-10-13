"""Reject changed batch authority and incomplete variant groups."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import build_pokemon_name_next3000 as compiler
from pokemon_index import catalog_locale


class Next3000PacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1] / compiler.DIRECTORY
        cls.packet_raw = (root / 'basis-qualification.json').read_bytes()
        cls.review_raw = (root / 'record-binding-review.json').read_bytes()
        cls.packet = json.loads(cls.packet_raw)
        cls.review = json.loads(cls.review_raw)

    def test_exact_frozen_packet_and_current_aliases(self):
        packet, rows = compiler.checked_packet(self.packet_raw, self.review_raw)
        self.assertEqual(len(rows), 3000)
        self.assertEqual(packet['current_approved_pokemon_full_name_concepts'], 596)
        self.assertEqual({w['identity']['language'] for w in rows}, {'en'})

    def check_changed(self, packet=None, review=None):
        raw = catalog_locale.encoded(packet or self.packet).encode()
        reviewed = catalog_locale.encoded(review or self.review).encode()
        # Rebind synthetic fixture hashes to exercise semantic guards rather than
        # merely the outer byte seal. These patches never qualify real data.
        with patch.object(compiler, 'PACKET_SHA', compiler.signature(raw)), patch.object(compiler, 'REVIEW_SHA', compiler.signature(reviewed)):
            altered_review = json.loads(reviewed)
            altered_review['proposal_sha256'] = compiler.signature(raw)
            reviewed = catalog_locale.encoded(altered_review).encode()
            with patch.object(compiler, 'REVIEW_SHA', compiler.signature(reviewed)):
                with self.assertRaises(ValueError):
                    compiler.checked_packet(raw, reviewed)

    def test_prior_baseline_is_not_current(self):
        packet = copy.deepcopy(self.packet); packet['input_database_sha256'] = '4' * 64
        self.check_changed(packet=packet)

    def test_cross_language_printing_is_not_selected_identity(self):
        packet = copy.deepcopy(self.packet); packet['english_witnesses'][0]['identity']['language'] = 'ja'
        self.check_changed(packet=packet)

    def test_foil_stamp_variant_cannot_silently_change_id(self):
        packet = copy.deepcopy(self.packet); packet['english_witnesses'][0]['identity']['variant'] += '_stamp'
        self.check_changed(packet=packet)

    def test_conflicted_or_missing_current_alias_abstains(self):
        for field, value in [('unresolved_conflicts', ['source number conflict']), ('name_alias', None)]:
            with self.subTest(field=field):
                packet = copy.deepcopy(self.packet); packet['english_witnesses'][0][field] = value
                self.check_changed(packet=packet)

    def test_metadata_does_not_approve_display_or_purchase(self):
        for field in catalog_locale.FALSE_CLAIMS:
            with self.subTest(field=field):
                packet = copy.deepcopy(self.packet); packet['english_witnesses'][0][field] = True
                self.check_changed(packet=packet)

    def test_independent_review_must_cover_exact_records(self):
        for field, value in [('approved_record_bindings', 2999), ('selected_card_ids_sha256', '0' * 64),
                             ('uncertain_card_ids', ['en:ambiguous']), ('purchase_allowed', True)]:
            with self.subTest(field=field):
                review = copy.deepcopy(self.review); review[field] = value
                self.check_changed(review=review)

    def test_packet_hash_drift_rejected(self):
        with self.assertRaises(ValueError):
            compiler.checked_packet(self.packet_raw + b' ', self.review_raw)


class CompleteGroupTests(unittest.TestCase):
    class DB:
        def __init__(self, siblings):
            self.siblings = siblings

        def execute(self, sql):
            return self.siblings

    def test_repeated_number_requires_every_eligible_foil_variant(self):
        a = dict(card_id='en:SYN:001/010:normal', language='en', set_code='SYN', collector_number='001/010', name='Synthetic', category='Pokemon')
        b = {**a, 'card_id': 'en:SYN:001/010:reverse'}
        with patch.object(compiler.variant_dimension_hold, 'held', return_value=False):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                compiler.complete_groups(self.DB([a, b]), [{'identity': a}], set())
            compiler.complete_groups(self.DB([a, b]), [{'identity': a}, {'identity': b}], set())

    def test_same_number_different_name_or_held_promo_is_ambiguous(self):
        a = dict(card_id='en:SYN:001:normal', language='en', set_code='SYN', collector_number='001', name='Synthetic', category='Pokemon')
        b = {**a, 'card_id': 'en:SYN:001:stamp', 'name': 'Other synthetic promo'}
        with patch.object(compiler.variant_dimension_hold, 'held', return_value=False):
            with self.assertRaises(ValueError):
                compiler.complete_groups(self.DB([a, b]), [{'identity': a}, {'identity': b}], set())
        with patch.object(compiler.variant_dimension_hold, 'held', return_value=True):
            with self.assertRaises(ValueError):
                compiler.complete_groups(self.DB([a]), [{'identity': a}], set())


if __name__ == '__main__':
    unittest.main()
