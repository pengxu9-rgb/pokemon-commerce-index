"""Pool tiers retain native scorer semantics without allocating unused reasons."""
from contextlib import closing
import copy
import hashlib
import itertools
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_journey, collector_recommendation as rec
from pokemon_index.collector_runtime import CatalogReadModel
from scripts.rehearse_collector_recommendations import SUITE, create_fixture


class RecommendationRankingWorkTests(unittest.TestCase):
    def test_tier_counts_equal_full_evidence_scorer_at_typed_and_duplicate_boundaries(self):
        row={'card_id':'ja:FIX:001/100:holo','language':'ja','set_code':'FIX','provenance':'source:a'}
        facets=[{'facet_type':kind,'value':value,'provenance':'source:'+str(i),
                 'rights_reference':'rights:'+str(i)} for i,(kind,value) in enumerate([
                     ('dex_id','25'),('dex_id','25'),('illustrator','Ａlpha'),
                     ('illustrator','Alpha'),('dex_id',25),('dex_id',b'25'),
                     ('dex_id',None),('illustrator','アルファ\x00'),('other','25')])]
        choices=[{'dex_id':set(dex),'illustrator':set(artists)} for dex,artists in
                 itertools.product([(),('25',),('151',),('25','151')],
                                   [(),('Alpha',),('Ａlpha','アルファ\x00')])]
        before=copy.deepcopy(facets)
        for desired,liked,affiliation,release in itertools.product(choices,choices,
                [None,{'dex_id':25},{'dex_id':151}],
                [[],[{'language':'ja','set_code':'FIX'}],[{'language':'en','set_code':'FIX'}]]):
            affiliations={} if affiliation is None else {row['card_id']:affiliation}
            # The native reason builder needs a complete proof only for an
            # unmatched affiliation; use the same existing proof constructor.
            with patch.object(rec,'_affiliation_reason',return_value={'proof':'test-only'}):
                score=rec._score(row,facets,desired,liked,release,affiliations)
            self.assertEqual(rec._ranking_axes(row,facets,desired,liked,release,affiliations),
                             (len(score['explicit_match_axes']),len(score['liked_example_match_axes'])))
        self.assertEqual(facets,before)

    def test_all_frozen_prefixes_equal_full_scorer_pool_tiers(self):
        suite=json.loads(SUITE.read_text())
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'catalog.sqlite3';create_fixture(path,suite)
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            with closing(core.connect(path,readonly=True)) as db:model=CatalogReadModel(db)
            def old_tiers(row,facets,desired,liked,releases,affiliations):
                score=rec._score(row,facets,desired,liked,releases,affiliations)
                return len(score['explicit_match_axes']),len(score['liked_example_match_axes'])
            for journey in suite['journeys']:
                turns=[]
                for step in journey['steps']:
                    turns.append(step['action']);payload={'turns':copy.deepcopy(turns),'limit':suite['limit']}
                    results=[]
                    for control in (True,False):
                        with closing(core.connect(path,readonly=True)) as db,model.request(db,strict_readonly=True):
                            def run():
                                try:return ('result',collector_journey.replay(db,payload,revision='a'*64))
                                except ValueError as exc:return ('error',str(exc))
                            if control:
                                with patch.object(rec,'_ranking_axes',side_effect=old_tiers):results.append(run())
                            else:results.append(run())
                    with self.subTest(journey=journey['id'],turn=len(turns)):self.assertEqual(*results)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_snapshot_rows_are_request_local_and_native_rows_keep_dict_contract(self):
        suite=json.loads(SUITE.read_text())
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'catalog.sqlite3';create_fixture(path,suite)
            with closing(core.connect(path,readonly=True)) as db:
                ids=[r[0] for r in db.execute('SELECT card_id FROM card ORDER BY card_id')]
                native=list(rec._facet_batches(db,ids))
                self.assertTrue(all(type(r) is dict for batch in native for rows in batch.values() for r in rows))
                model=CatalogReadModel(db)
            with closing(core.connect(path,readonly=True)) as db,model.request(db,strict_readonly=True):
                first=list(rec._facet_batches(db,ids))
                self.assertTrue(all(type(r) is sqlite3.Row for batch in first for rows in batch.values() for r in rows))
                expected=[{k:[dict(r) for r in rows] for k,rows in batch.items()} for batch in first]
                first[0][ids[0]].clear()
            with closing(core.connect(path,readonly=True)) as db,model.request(db,strict_readonly=True):
                self.assertEqual([{k:[dict(r) for r in rows] for k,rows in batch.items()}
                                  for batch in rec._facet_batches(db,ids)],expected)


if __name__=='__main__':unittest.main()
