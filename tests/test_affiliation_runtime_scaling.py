"""Populated effective-view regression, not a real-catalog measurement.

Synthetic raw + current official facets and a qualified synthetic correction
exercise the production SQL views. The 27 pin shapes are reused with explicitly
synthetic support; they do not establish new facts about the real targets.
"""
import copy
from contextlib import closing, contextmanager
import importlib.util
import json
from pathlib import Path
import random
import re
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import card_metadata, collector_character_affiliation as affiliation
from pokemon_index import collector_discovery, collector_journey, collector_recommendation, core, supported_catalog


def build_fixture(path, *, total=12000, metadata_count=600):
    from tests import test_source_corrections as correction_fixture
    from pokemon_index import source_corrections
    fixture=correction_fixture.SourceCorrectionTests()
    fixture.setUp()
    try:
        source_corrections.import_evidence(fixture.db,[fixture.correction])
        with closing(core.connect(path)) as db:
            fixture.db.backup(db)
    finally:fixture.tearDown()
    bindings=copy.deepcopy(affiliation._bindings());supports={};cards=[];facets=[];categories=[]
    for binding in bindings:
        identity=binding['identity'];cid=identity['card_id'];rights=binding['target_rights_reference']
        supports[cid]={'identity':identity,'scope':'synthetic effective-view performance fixture'}
        binding['supported_record_sha256']=supported_catalog.digest(supports[cid])
        cards.append(tuple(identity[k] for k in ['card_id','language','set_code','collector_number','variant','name','rarity','provenance'])+(rights,0,1,'{}'))
        categories.append((cid,'Pokemon',None,identity['provenance'],rights))
    names=sorted({binding['base_name_ja'] for binding in bindings});anchor_ids=[]
    for i in range(total):
        code=f'SYN{i//500:03}';number=f'{i%500+1:03}/500';cid=core.card_id('ja',code,number,'normal')
        name=names[i//2] if i<2*len(names) else f'Synthetic Pokemon {i}'
        dex=i//2+1 if i<2*len(names) else 500
        provenance=f'synthetic:effective-view:{i}';rights='synthetic:fixture-rights'
        cards.append((cid,'ja',code,number,'normal',name,None,provenance,rights,0,1,'{}'))
        artist='Fixture Artist' if i<10000 else 'Other Fixture Artist'
        facets.extend([(cid,'dex_id',str(dex),provenance,rights),(cid,'illustrator',artist,provenance,rights)])
        categories.append((cid,'Pokemon',None,provenance,rights))
        if i<2*len(names):anchor_ids.append(cid)
    with closing(core.connect(path)) as db:
        db.executemany('INSERT INTO card VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',cards)
        db.executemany('INSERT INTO card_facet VALUES(?,?,?,?,?)',facets)
        db.executemany('INSERT INTO card_classification VALUES(?,?,?,?,?)',categories)
        # Every first base-name anchor comes from an active official overlay,
        # while its second anchor retains raw source facets.
        overlay_ids=anchor_ids[::2]+[r[0] for r in cards[len(bindings)+len(anchor_ids):]][:max(0,metadata_count-len(names))]
        records=[]
        for i,cid in enumerate(overlay_ids):
            card=db.execute('SELECT * FROM card WHERE card_id=?',(cid,)).fetchone();native=str(100000+i)
            reference=dict(source='ptcg-database',native_id=native,name=card['name'],provenance=f'synthetic:reference:{native}')
            db.execute('INSERT INTO card_reference VALUES(?,?,?,?,?,?,?,?,?,?)',(
                reference['source'],native,card['set_code'],card['collector_number'],card['name'],None,'{}',reference['provenance'],'synthetic:fixture-rights',0))
            entry=dict(set_code=card['set_code'],collector_number=card['collector_number'],part_role=None,
                rarity='C',rarity_status='recognized_icon',rarity_icons=['ic_rare_c_c.gif'])
            dex=int(db.execute("SELECT value FROM card_facet WHERE card_id=? AND facet_type='dex_id'",(cid,)).fetchone()[0])
            row=dict(schema='pokemon.official-card-metadata.v1',revision=1,status='source_supported',card_id=cid,
                identity=supported_catalog.identity_snapshot(card),reference=reference,
                official=dict(url='https://www.pokemon-card.com/card-search/details.php/card/'+native,
                    page_sha256='a'*64,fetched_at='2026-10-01T00:00:00Z',name=card['name'],
                    numbered_entries=[entry],page_kind='single_number',illustrators=['Fixture Artist'],dex_id=dex,**entry),
                **{key:False for key in card_metadata.FALSE_CLAIMS})
            row['evidence_id']=card_metadata.event_id(row);records.append(row)
        db.commit();card_metadata.import_evidence(db,records)
    return dict(bindings=bindings,supports=supports,anchor_ids=anchor_ids,names=names,
                metadata_count=len(records),catalog_records=len(cards)+1)


@contextmanager
def synthetic_support(fixture, module=affiliation):
    original=supported_catalog.support_for_card
    def support(db,cid):
        if cid in fixture['supports']:
            return {'status':'supported_for_internal_review','evidence':fixture['supports'][cid]}
        return original(db,cid)
    with patch.object(module,'_bindings',return_value=fixture['bindings']), \
         patch.object(supported_catalog,'support_for_card',side_effect=support):
        yield


class EffectiveViewRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.path=Path(cls.tmp.name)/'effective.sqlite3'
        cls.fixture=build_fixture(cls.path)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_all_pins_use_full_current_raw_and_official_anchor_consensus(self):
        with closing(core.connect(self.path,readonly=True)) as db,synthetic_support(self.fixture):
            self.assertEqual(db.execute('SELECT count(*) FROM active_card_metadata_evidence').fetchone()[0],600)
            self.assertEqual(db.execute('SELECT count(*) FROM active_source_correction_evidence').fetchone()[0],1)
            out=affiliation.affiliations(db)
            self.assertEqual(len(out),27)
            for item in out.values():
                self.assertEqual(item['reason']['anchor_count'],2)
                self.assertFalse(item['reason']['source_asserted_dex_id'])
            self.assertIn('active_artist_facts',db.execute("SELECT sql FROM sqlite_master WHERE name='discovery_card_facet'").fetchone()[0])

    def test_populated_effective_view_proofs_match_without_per_name_rescans(self):
        spec=importlib.util.spec_from_file_location('unbatched_scaling_oracle',
            Path(__file__).with_name('fixtures')/'collector_character_affiliation_7382318.py')
        legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
        outputs=[];costs=[]
        for module in [legacy,affiliation]:
            with closing(core.connect(self.path,readonly=True)) as db,synthetic_support(self.fixture,module=module):
                statements=[];progress=[0]
                def tick():progress[0]+=1;return False
                db.set_trace_callback(statements.append);db.set_progress_handler(tick,1000)
                outputs.append(module.affiliations(db))
                costs.append((sum('discovery_card_facet' in sql for sql in statements),progress[0]))
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(supported_catalog.digest(outputs[0]),supported_catalog.digest(outputs[1]))
        self.assertEqual(costs[0][0],51)  # 27 target probes + 24 exact names
        self.assertEqual(costs[1][0],2)
        # VM work, rather than a flaky wall-clock SLA, catches accidental
        # repeated evaluation of populated source-bound metadata views.
        self.assertLess(costs[1][1]*5,costs[0][1])

    def test_clarification_only_profiles_never_load_affiliations(self):
        with closing(core.connect(self.path,readonly=True)) as db,patch.object(affiliation,'affiliations',side_effect=AssertionError('unneeded catalog derivation')):
            for profile in [{},{'subjective_notes':['cute']},{'excluded_dex_ids':[151]}]:
                out=collector_recommendation.recommend(db,'What should I collect next?',profile,{})
                self.assertEqual(out['scope']['task'],'collection_preferences_needed')
                self.assertEqual(out['cards'],[])
            result=collector_journey.replay(db,{'turns':[{'type':'ask','question':"I've completed my collection of Tomokazu Komiya artworks. What should I collect next?"}]},revision='a'*64)
            self.assertEqual(result['discovery']['task'],'collection_preferences_needed')
            self.assertFalse(result['purchase_ready']);self.assertFalse(result['public_display_allowed'])

    def test_later_positive_preferences_and_liked_examples_still_validate_affiliations(self):
        with closing(core.connect(self.path,readonly=True)) as db,synthetic_support(self.fixture),patch.object(affiliation,'affiliations',wraps=affiliation.affiliations) as derive:
            first=collector_recommendation.recommend(db,'What should I collect next?',{},{})
            self.assertEqual(derive.call_count,0)
            cid=self.fixture['bindings'][0]['card_id']
            liked=collector_recommendation.recommend(db,'What should I collect next?',{}, {cid:'like'})
            self.assertEqual(derive.call_count,1);self.assertTrue(liked['cards'])
            with patch.object(affiliation,'affiliations',side_effect=ValueError('validate current proof')):
                with self.assertRaisesRegex(ValueError,'current proof'):
                    collector_recommendation.recommend(db,'What should I collect next?',{'preferred_dex_ids':[1]}, {})
            self.assertEqual(first['cards'],[])

    def test_unapplied_notes_reuse_only_ranking_and_keep_uncached_output_equivalent(self):
        with closing(core.connect(self.path,readonly=True)) as db,synthetic_support(self.fixture):
            base={'preferred_illustrators':['Fixture Artist']};cache={'revision':'a'*64}
            args=dict(question='What should I collect next?',profile=base,feedback={},
                      preferences={'collecting':base})
            first=collector_recommendation.recommend(db,**args,pool_cache=cache);saved=copy.deepcopy(first)
            pool=cache['pool']
            for note in ['cute','quiet scenes']:
                profile=dict(base,subjective_notes=[note]);changed=dict(args,profile=profile,preferences={'collecting':profile})
                actual=collector_recommendation.recommend(db,**changed,pool_cache=cache)
                self.assertIs(cache['pool'],pool)
                self.assertEqual(actual,collector_recommendation.recommend(db,**changed))
                self.assertEqual(actual['recommendation']['unapplied_preferences'],[
                    {'value':note,'reason':'no_source_backed_style_labels'}])
            self.assertEqual(first,saved)

    def test_note_changes_still_withdraw_selected_target_and_comparison_authority(self):
        with closing(core.connect(self.path,readonly=True)) as db,synthetic_support(self.fixture):
            turns=[{'type':'ask','question':'What should I collect next?'},
                   {'type':'preferences','preferences':{'collecting':{'preferred_illustrators':['Fixture Artist']}}}]
            first=collector_journey.replay(db,{'turns':turns},revision='a'*64)
            ids=[card['card_id'] for card in first['candidate_cards']]
            selected=collector_journey.replay(db,{'turns':turns+[{'type':'select','card_id':ids[0]}]},revision='a'*64)
            self.assertIsNotNone(selected['target_intent'])
            notes={'type':'preferences','preferences':{'collecting':{'subjective_notes':['cute']}}}
            cleared=collector_journey.replay(db,{'turns':turns+[{'type':'select','card_id':ids[0]},notes]},revision='a'*64)
            self.assertIsNone(cleared['target_intent'])
            compared=turns+[{'type':'compare','left_card_id':ids[0],'right_card_id':ids[1]},notes,
                {'type':'choose_comparison','side':'left','card_id':ids[0]}]
            with self.assertRaisesRegex(ValueError,'active comparison|current comparison'):
                collector_journey.replay(db,{'turns':compared},revision='a'*64)


class LiteralMentionOptimizationTests(unittest.TestCase):
    def test_substring_shortcut_matches_original_boundary_regex(self):
        def original(text,term):
            term=collector_discovery._norm(term)
            if re.fullmatch(r"[a-z0-9 '\-\.]+",term):
                return bool(re.search(r'(?<![a-z0-9])'+re.escape(term)+r'(?![a-z0-9])',text))
            return term in text
        cases=[('mewtwo','Mew'),('mew ex','Mew'),('mew-ex','Mew'),
            ('ミュウツー','ミュウ'),('a.b','A.B'),('aXb','a.b'),('x25x','25'),
            ('ミュウex','EX'),('', ''),('anything',''),('pikachu','Ｐｉｋａｃｈｕ'),
            ('mr. mime cards','Mr. Mime'),("farfetch'd", "Farfetch’d")]
        rng=random.Random(7382318)
        alphabet="mew25abc -.'ミュウéß"
        for _ in range(2000):
            term=''.join(rng.choice(alphabet) for _ in range(rng.randrange(1,12)))
            text=''.join(rng.choice(alphabet) for _ in range(rng.randrange(0,25)))
            cases.extend([(text,term),(text+term+text,term)])
        for text,term in cases:
            self.assertEqual(collector_discovery._mentioned(text,term),original(text,term),(text,term))

    def test_impossible_catalog_names_never_compile_boundary_regex(self):
        with patch.object(collector_discovery.re,'search',side_effect=AssertionError('impossible match compiled')):
            for i in range(1000):
                self.assertFalse(collector_discovery._mentioned('cards by fixture artist',f'synthetic pokemon {i}'))


if __name__=='__main__':unittest.main()
