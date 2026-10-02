import sqlite3
import unittest

from scripts.audit_catalog_graph_quality import release_completeness


class ReleaseGapAuditTests(unittest.TestCase):
    def test_named_promo_with_unknown_date_is_not_a_missing_name(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        self.addCleanup(db.close)
        db.executescript('''CREATE TABLE card(language TEXT,set_code TEXT);
            CREATE TABLE catalog_set_localized(language TEXT,set_code TEXT,name TEXT,release_date TEXT);
            INSERT INTO card VALUES ('ja','PROMO'),('ja','PROMO'),('ja','UNKNOWN'),('en','KNOWN');
            INSERT INTO catalog_set_localized VALUES ('ja','PROMO','Promo series',NULL),
                ('ja','UNKNOWN','  ',NULL),('en','KNOWN','Known release','2020-01-01');''')
        result=release_completeness(db)
        self.assertEqual(result['release_gap_records'],3)
        self.assertEqual(result['release_missing_name_records'],1)
        self.assertEqual(result['release_missing_date_records'],3)
        self.assertEqual(result['release_missing_name_groups'],1)
        self.assertEqual(result['release_missing_date_groups'],2)
        self.assertEqual(result['release_gaps'][0]['set_code'],'PROMO')
        self.assertEqual(result['release_gaps'][0]['missing_name'],0)


if __name__=='__main__':unittest.main()
