import copy
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale, product_text
from scripts import build_anchor_qualification_fields as compiler
from scripts import qualify_international_product_documents as documents


class AnchorQualificationFieldTests(unittest.TestCase):
    TIME='2026-10-11T13:13:17Z'

    def setUp(self):
        self.outcome=dict(set_code='SC',collector_number='001/020',card_id='ja:SC:001/020:unverified',
            candidate_id='candidate:SC',caption_evidence_id='caption:SC',qualification_id='qualification:SC',
            language='ja',status='held_anchor_binding_unqualified',release_date=None,physical_distribution_region=None,
            anchor_source={'sha256':'a'*64},unresolved_conflicts=['physical_variant_not_verified'],
            **{k:False for k in product_text.FLAGS})
        self.publisher=dict(native_id='28616',url='https://www.pokemon-card.com/card-search/details.php/card/28616',
            language='ja',sha256='b'*64,retrieved_at='2026-10-02T00:38:44Z',physical_distribution_region=None)
        self.caption=dict(card_id=self.outcome['card_id'],candidate_id=self.outcome['candidate_id'],
            evidence_id=self.outcome['caption_evidence_id'],publisher=self.publisher,test_only=False,
            **{k:False for k in product_text.FLAGS})
        self.source=dict(jp_id=28616,url=self.publisher['url'],name='ツタージャ',number='001',set_total='020',
            set_name='SC',author=['Eske Yoshinob'],pokedex_number=495,rarity='rare_c_c',
            sources=[dict(name='ポケモンカードゲームBW コンセプトパック「シャイニーコレクション」',link=None)])
        self.receipt=dict(provider='ptcg-database',revision=compiler.REVISION,native_id='data_jp/SC/28616.json',sha256='a'*64)
        self.observed=dict(name='ツタージャ',illustrators=['Eske Yoshinob'],dex_id=495,
            numbered_entries=[dict(set_code='SC',collector_number='001/020',rarity_icons=['ic_rare_c_c.gif'],rarity='C',rarity_status='recognized_icon')])
        self.products=[dict(name=self.source['sources'][0]['name'],publisher_link=None,link_kind='unlinked_text')]

    def record(self,**changes):
        values=dict(outcome=self.outcome,caption=self.caption,source=self.source,source_receipt=self.receipt,
                    observed=self.observed,products=self.products,inspected_at=self.TIME)
        values.update(changes);return compiler.record(**values)

    def test_exact_unicode_artist_dex_and_icon_fields_qualify_without_binding_or_permission(self):
        row=self.record()
        self.assertEqual(row['qualified_literal_fields'],['name','coordinate','illustrators','pokedex_number','product_caption','rarity_identifier'])
        self.assertEqual(row['checks']['pokedex_number']['provider_value'],495)
        self.assertEqual(row['status'],'qualified_literal_fields_anchor_still_held')
        self.assertIn('not_independent_physical_review',row['source_dependence'])
        self.assertIsNone(row['release_date']);self.assertIsNone(row['physical_distribution_region'])
        self.assertIsNone(row['confidence']['product_release_binding'])
        for flag in product_text.FLAGS:self.assertFalse(row[flag])

    def test_requalification_is_idempotent_and_does_not_modify_inputs(self):
        before=copy.deepcopy((self.outcome,self.caption,self.source,self.receipt,self.observed,self.products))
        first=self.record();self.assertEqual(first,self.record())
        self.assertEqual(before,(self.outcome,self.caption,self.source,self.receipt,self.observed,self.products))
        self.assertEqual(first['evidence_id'],'anchor-qualification-fields:'+catalog_locale.digest({k:v for k,v in first.items() if k!='evidence_id'}))

    def test_missing_fields_are_unreported_not_inferred(self):
        source=copy.deepcopy(self.source)
        for key in ('author','pokedex_number','rarity'):source.pop(key)
        observed=copy.deepcopy(self.observed);observed.update(illustrators=[],dex_id=None)
        observed['numbered_entries'][0].update(rarity_icons=[],rarity=None,rarity_status='no_rarity_icon')
        row=self.record(source=source,observed=observed)
        for key in ('illustrators','pokedex_number','rarity_identifier'):
            self.assertEqual(row['checks'][key]['status'],'both_unreported');self.assertNotIn(key,row['qualified_literal_fields'])

    def test_legacy_rarity_literal_match_never_guesses_semantics_or_finish(self):
        source=copy.deepcopy(self.source);source['rarity']='rare_c'
        observed=copy.deepcopy(self.observed);observed['numbered_entries'][0].update(rarity_icons=['ic_rare_c.gif'],rarity=None,rarity_status='unrecognized_icon')
        row=self.record(source=source,observed=observed)
        self.assertEqual(row['checks']['rarity_identifier']['status'],'literal_match')
        self.assertIsNone(row['publisher_rarity_interpretation']['normalized_value'])
        self.assertIn('rarity_icon_semantics_unqualified',row['unresolved_conflicts']);self.assertFalse(row['physical_printing_verified'])

    def test_artist_and_dex_conflicts_remain_explicit_and_unqualified(self):
        source=copy.deepcopy(self.source);source.update(author=['Other Artist'],pokedex_number=1)
        row=self.record(source=source)
        for key in ('illustrators','pokedex_number'):
            self.assertEqual(row['checks'][key]['status'],'conflict');self.assertNotIn(key,row['qualified_literal_fields'])
            self.assertIn('field_'+key+'_conflict',row['unresolved_conflicts'])

    def test_shared_artists_dex_and_repeated_numbers_cannot_override_wrong_set(self):
        source=copy.deepcopy(self.source);source['set_name']='DS'
        row=self.record(source=source)
        self.assertEqual(row['status'],'held_coordinate_conflict');self.assertEqual(row['qualified_literal_fields'],[])
        self.assertFalse(row['physical_printing_verified']);self.assertFalse(row['release_binding_verified'])

    def test_multiple_promo_coordinates_and_missing_denominators_abstain(self):
        observed=copy.deepcopy(self.observed)
        observed['numbered_entries'].append({**observed['numbered_entries'][0],'set_code':'SV-P'})
        self.assertEqual(self.record(observed=observed)['qualified_literal_fields'],[])
        for value in [None,'','000','unknown','20+']:
            source=copy.deepcopy(self.source);source['set_total']=value
            with self.subTest(value=value):self.assertEqual(self.record(source=source)['qualified_literal_fields'],[])

    def test_mismatched_native_ids_or_source_urls_hold_even_if_metadata_matches(self):
        for key,value in [('jp_id',True),('jp_id',99999),('url','https://merchant.invalid/product')]:
            source=copy.deepcopy(self.source);source[key]=value
            self.assertEqual(self.record(source=source)['qualified_literal_fields'],[])

    def test_foreign_source_namespaces_and_revisions_cannot_collide(self):
        for key,value in [('provider','tcgdex'),('revision','c'*40),('native_id','data_jp/DS/28616.json'),('sha256','d'*64)]:
            receipt=copy.deepcopy(self.receipt);receipt[key]=value
            with self.assertRaisesRegex(ValueError,'namespace or pinned snapshot'):self.record(source_receipt=receipt)

    def test_foreign_language_foil_or_stamp_variants_cannot_inherit_evidence(self):
        for key,value in [('language','en'),('card_id','ja:SC:001/020:foil-stamp'),('release_date','2013-02-01'),('purchase_allowed',True)]:
            outcome=copy.deepcopy(self.outcome);outcome[key]=value
            with self.assertRaises(ValueError):self.record(outcome=outcome)
        caption=copy.deepcopy(self.caption);caption['image_display_allowed']=True
        with self.assertRaises(ValueError):self.record(caption=caption)

    def test_missing_duplicate_or_unsupported_provider_literals_fail_closed(self):
        for key,value in [('author',['Eske Yoshinob','Eske Yoshinob']),('author','Eske Yoshinob'),('pokedex_number',True),('pokedex_number',0),('rarity','foil-like'),('sources',[])]:
            source=copy.deepcopy(self.source);source[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.record(source=source)
        with self.assertRaisesRegex(ValueError,'duplicate source JSON field'):
            json.loads('{"jp_id":28616,"jp_id":27836}',object_pairs_hook=compiler.unique_object)

    def test_caption_links_and_text_are_comparisons_never_promotion_targets(self):
        source=copy.deepcopy(self.source);source['sources'][0]['name']='ポケモンカードゲーム 別のプロモ'
        row=self.record(source=source)
        self.assertEqual(row['checks']['product_caption']['status'],'conflict')
        self.assertNotIn('product_caption',row['qualified_literal_fields']);self.assertFalse(row['release_binding_verified'])
        source['sources'][0]['link']='https://merchant.invalid/product'
        with self.assertRaises(ValueError):self.record(source=source)

    def test_missing_publisher_artist_is_not_copied_from_provider(self):
        observed=copy.deepcopy(self.observed);observed['illustrators']=[]
        row=self.record(observed=observed)
        self.assertEqual(row['checks']['illustrators']['status'],'publisher_unreported')
        self.assertNotIn('illustrators',row['qualified_literal_fields'])

    def test_offline_git_helper_requires_full_pin_and_preserves_tcgdex_default(self):
        with patch.object(documents.subprocess,'check_output',side_effect=['origin\n','']) as call:
            documents.git_tree(Path('/fixture'),[],revision=compiler.REVISION)
            self.assertIn(compiler.REVISION,call.call_args_list[1].args[0])
            self.assertEqual(call.call_args_list[1].kwargs['env']['GIT_NO_LAZY_FETCH'],'1')
        with patch.object(documents.subprocess,'check_output') as call:
            with self.assertRaisesRegex(ValueError,'full pinned revision'):documents.git_tree(Path('/fixture'),[],revision='main')
            call.assert_not_called()

    def test_cli_writes_hash_bound_evidence_and_refuses_output_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'fields';args=['fields','--db','offline','--cache','cached','--tcgdex-repo','pinned-tcgdex',
                '--ptcg-repo','pinned-ptcg','--output-dir',str(output),'--inspected-at',self.TIME]
            result=([self.record()],dict(field_evidence_records=1,qualified_literal_field_subjects=1,new_identities=0,new_release_dates=0),b'test-only licence')
            with patch.object(sys,'argv',args),patch.object(compiler,'build',return_value=result) as build:
                compiler.main();report=json.loads((output/'coverage-report.json').read_text())
                for filename,sha in report['file_hashes'].items():self.assertEqual(hashlib.sha256((output/filename).read_bytes()).hexdigest(),sha)
                with self.assertRaises(FileExistsError):compiler.main()
                self.assertEqual(build.call_count,1)

    def build_fixture(self,folder):
        root=Path(folder);prior=root/'catalog/international-product-documents-v1';prior.mkdir(parents=True)
        cache=root/'cache';cache.mkdir();provider=root/'ptcg';provider.mkdir()
        raw=json.dumps(self.source,ensure_ascii=False).encode();sha=hashlib.sha256(raw).hexdigest()
        source_path='data_jp/SC/28616.json';target=provider/source_path;target.parent.mkdir(parents=True);target.write_bytes(raw)
        license_raw=b'test-only license';(provider/'LICENSE').write_bytes(license_raw);(root/'catalog/PTCG-DATABASE-LICENSE').write_bytes(license_raw)
        blob=lambda raw:hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        pins={'LICENSE':blob(license_raw),source_path:blob(raw)}
        for code,native in documents.ANCHORS.items():
            pins.setdefault(f'data_jp/{code}/{native}.json','e'*40)
        outcome=copy.deepcopy(self.outcome);outcome['anchor_source']['sha256']=sha
        docs=[dict(inspected_at=self.TIME)];outcomes=[outcome]
        (prior/'provider-documents.jsonl').write_text(json.dumps(docs[0])+'\n');(prior/'anchor-outcomes.jsonl').write_text(json.dumps(outcome)+'\n')
        base_report=dict(catalogue_inventory={'source_records':1},snapshot={'database_sha256':'d'*64})
        (prior/'coverage-report.json').write_text(json.dumps({**base_report,'file_hashes':{}}))
        body=b'test-only authorized HTML';(cache/'card-SC.html').write_bytes(body)
        caption=copy.deepcopy(self.caption);caption['publisher']['sha256']=hashlib.sha256(body).hexdigest()
        receipt=dict(url=caption['publisher']['url'],sha256=caption['publisher']['sha256'],fetched_at=caption['publisher']['retrieved_at'])
        (cache/'card-SC.receipt.json').write_text(json.dumps(receipt))
        db=root/'db.sqlite3';sqlite3.connect(db).close()
        return root,cache,provider,db,(docs,outcomes,base_report,{},b'test-only license'),pins,caption,target

    def test_final_guard_rejects_late_source_mutation_during_prior_revalidation(self):
        with tempfile.TemporaryDirectory() as folder:
            root,cache,provider,db,fresh,pins,caption,target=self.build_fixture(folder)
            count=0
            def revalidate(*args):
                nonlocal count
                count+=1
                if count==2:target.write_bytes(b'changed')
                return fresh
            with patch.object(documents,'build',side_effect=revalidate),patch.object(documents,'git_tree',return_value=pins),\
                    patch.object(compiler.product_text,'records',return_value=[caption]),patch.object(compiler.product_text,'validate'),\
                    patch.object(compiler,'parse_page',return_value=self.observed),patch.object(compiler,'extract',return_value=self.products):
                # Mutate only during the second (otherwise identical) catalogue
                # revalidation; the supplement must check its own files afterward.
                with self.assertRaisesRegex(ValueError,'supplement inputs changed'):
                    compiler.build(db,root,cache,root/'tcgdex',provider,self.TIME)

    def test_stale_prior_outcome_abstains_before_new_field_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root,cache,provider,db,fresh,pins,caption,target=self.build_fixture(folder)
            different=copy.deepcopy(fresh);different[1][0]['candidate_id']='changed'
            with patch.object(documents,'build',return_value=different),patch.object(documents,'git_tree') as tree:
                with self.assertRaisesRegex(ValueError,'prior qualification is stale'):
                    compiler.build(db,root,cache,root/'tcgdex',provider,self.TIME)
                tree.assert_not_called()


if __name__=='__main__':unittest.main()
