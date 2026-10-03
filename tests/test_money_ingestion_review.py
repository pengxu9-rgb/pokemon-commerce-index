"""Independent amount-contract regressions; no live merchant or payment calls."""
import sqlite3
import unittest
from pokemon_index import core

class MoneyIngestionReview(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.db.row_factory=sqlite3.Row
        core.init_db(self.db)
        core.register_source(self.db, dict(source='fixture',rights_reference='synthetic',
            ingest_allowed=True,display_allowed=False,price_statistics_allowed=True,
            retention_days=365,listing_ttl_hours=24))
    def tearDown(self): self.db.close()
    def observation(self, amount):
        return dict(source='fixture',native_id='item',title='unresolved card',
            url='https://example.test/item',observed_at='2026-10-03T12:00:00Z',
            status='on_sale',currency='JPY',price_minor=amount,evidence_ref='synthetic:observation')
    def sale(self, amount):
        return dict(source='fixture',native_id='item',settled_at='2026-10-03T13:00:00Z',
            paid_minor=amount,currency='JPY',evidence_ref='synthetic:settlement')
    def test_observation_rejects_coercion_before_persistence(self):
        for amount in (True,False,1.9,-0.5,'12',float('nan'),2**63):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError): core.import_observations(self.db,[self.observation(amount)])
                self.assertEqual(self.db.execute('SELECT count(*) FROM observation').fetchone()[0],0)
    def test_settlement_rejects_coercion_before_persistence(self):
        core.import_observations(self.db,[self.observation(None)])
        for amount in (True,False,1.9,-0.5,'12',float('nan'),2**63):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError): core.import_verified_sales(self.db,[self.sale(amount)])
                self.assertEqual(self.db.execute('SELECT count(*) FROM verified_sale').fetchone()[0],0)
    def test_valid_integer_and_unknown_observation_remain_supported(self):
        core.import_observations(self.db,[self.observation(None)])
        self.assertIsNone(self.db.execute('SELECT price_minor FROM observation').fetchone()[0])
        core.import_verified_sales(self.db,[self.sale(1250)])
        self.assertEqual(self.db.execute('SELECT paid_minor FROM verified_sale').fetchone()[0],1250)
