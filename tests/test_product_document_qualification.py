import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_index import catalog_locale
from scripts import qualify_international_product_documents as compiler


def blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def header(code='DS', names="ja: 'ドラゴンセレクション', ko: '드래곤 컬렉션'", release="'2012-01-27'"):
    date='' if release is None else ', releaseDate: '+release
    return ("const set: Set = {id: '"+code+"', name: {"+names+
            "}, serie: serie, cardCount: {official: 20}"+date+"}\nexport default set").encode()


class ProductDocumentQualificationTests(unittest.TestCase):
    TIME='2026-10-11T12:01:43Z'

    def setUp(self):
        self.documents=[compiler.document_record(path,blob(header(code)),header(code),'a'*40,b'test-only license',self.TIME)
                        for code,path in compiler.PATHS.items()]
        self.plan=dict(inspected_at=self.TIME,subjects=[],requests=[],snapshot={'database_sha256':'b'*64},
                       catalogue_inventory={'source_records':70006},related_unqualified_family_observation={})
        for code,native in compiler.ANCHORS.items():
            number={'SMH':'001/131','DS':'001/020','SC':'001/020','LL':'001/040'}[code]
            subject=dict(priority='exact_caption_anchor',set_code=code,collector_number=number,
                card_id=f'ja:{code}:{number}:unverified',candidate_id='candidate:'+code,language='ja',
                publisher_card_url='https://www.pokemon-card.com/card-search/details.php/card/'+native,
                caption_evidence_id='caption:'+code,request_ids=['request:'+code],status='held',
                release_date=None,physical_distribution_region=None,release_binding_verified=False,
                source={'provider':'ptcg-database','native_id':f'data_jp/{code}/{native}.json','sha256':'c'*64},
                original_hold_reasons=['physical_printing_family_unresolved'],
                **{k:False for k in catalog_locale.FALSE_CLAIMS})
            binding={k:subject[k] for k in ('card_id','candidate_id','language','set_code','collector_number')}
            binding.update(caption_status='publisher_caption_checked',publisher_link=None,declared_caption='test-only '+code)
            self.plan['subjects'].append(subject)
            self.plan['requests'].append(dict(request_id='request:'+code,kind='product_release_document',
                document_url=None,cache_status='not_in_authorized_cache',subject_bindings=[binding]))

    def test_multilingual_scalar_date_has_no_language_region_or_printing_binding(self):
        row=self.documents[0]
        self.assertEqual(row['facts']['localized_names'],{'ja':'ドラゴンセレクション','ko':'드래곤 컬렉션'})
        self.assertEqual(row['facts']['declared_date'],dict(kind='shared_scalar_provider_date',value='2012-01-27'))
        self.assertIsNone(row['physical_distribution_region']);self.assertIsNone(row['retrieved_at'])
        self.assertFalse(row['release_binding_verified'])
        self.assertIsNone(row['confidence']['localized_initial_release_date'])
        for key in catalog_locale.FALSE_CLAIMS:self.assertFalse(row[key])

    def test_single_japanese_name_still_does_not_prove_physical_region(self):
        raw=header('LL',"ja: '強化パック ロストリンク'","'2010-04-16'")
        row=compiler.document_record('data-asia/L/LL.ts',blob(raw),raw,'a'*40,b'fixture',self.TIME)
        self.assertEqual(row['facts']['localized_names'],{'ja':'強化パック ロストリンク'})
        self.assertIsNone(row['physical_distribution_region']);self.assertFalse(row['physical_printing_verified'])

    def test_localized_date_map_never_inherits_missing_language(self):
        facts=compiler.parse_header(header(release="{ja: '2012-01-27'}"))
        self.assertEqual(facts['declared_date'],dict(kind='localized_provider_dates',values={'ja':'2012-01-27'}))
        self.assertNotIn('ko',facts['declared_date']['values'])
        with self.assertRaisesRegex(ValueError,'date language'):
            compiler.parse_header(header(release="{en: '2012-01-27'}"))

    def test_missing_date_remains_explicitly_unknown(self):
        self.assertEqual(compiler.parse_header(header(release=None))['declared_date'],dict(kind='provider_date_not_declared'))

    def test_malformed_or_dynamic_dates_fail_closed(self):
        for release in ['undefined','null','2012',"'2012-02-30'","'2012-01'","'2012-01-27' + suffix","{ja: ''}"]:
            with self.subTest(release=release),self.assertRaises(ValueError):compiler.parse_header(header(release=release))

    def test_duplicate_and_unsupported_localized_fields_fail_closed(self):
        for names in ["ja: 'first', ja: 'second'","ja: ''","ja: translated","ja: 'first', ...others",'']:
            with self.subTest(names=names),self.assertRaises(ValueError):compiler.parse_header(header(names=names))

    def test_top_level_duplicate_properties_and_nonliteral_suffixes_fail_closed(self):
        original=header()
        for raw in [original.replace(b"id: 'DS'",b"id: 'DS', id: 'SC'"),
                    original.replace(b"name: {",b"releaseDate: '2000-01-01', name: {"),
                    original.replace(b"id: 'DS'",b"id: 'DS' + other"),
                    original.replace(b'official: 20',b'official: 20, official: 40')]:
            with self.assertRaises(ValueError):compiler.parse_header(raw)

    def test_comments_and_nested_names_cannot_override_header(self):
        raw=header().replace(b"id: 'DS'",b"/* id: 'FAKE', } */ id: 'DS', nested: {name: {ja: 'wrong'}, releaseDate: '1999-01-01'}")
        facts=compiler.parse_header(raw)
        self.assertEqual(facts['provider_set_id'],'DS');self.assertEqual(facts['localized_names']['ja'],'ドラゴンセレクション')
        self.assertEqual(facts['declared_date']['value'],'2012-01-27')

    def test_missing_id_name_count_or_duplicate_objects_abstain(self):
        original=header()
        for raw in [original.replace(b"id: 'DS',",b''),original.replace(b'name:',b'other:'),
                    original.replace(b'official: 20',b'total: 20'),original+b'\n'+header()]:
            with self.assertRaises(ValueError):compiler.parse_header(raw)

    def test_quoted_templates_nested_or_unexported_declarations_are_not_headers(self):
        example=header().split(b'\nexport')[0]
        for raw in [b'const example = "'+example+b'"; export default example;',
                    b'const example = `'+example+b'`; export default example;',
                    b'function helper() { '+example+b'; return set; } export default helper;',
                    example+b'; export default other;',b'"unclosed '+example,b'/* unclosed '+example,
                    b'function helper() { '+header()]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):compiler.parse_header(raw)

    def test_new_authorized_cached_smh_target_still_held_with_accurate_conflict(self):
        plan=copy.deepcopy(self.plan)
        plan['requests'][0]['cache_status']='cached_needs_separate_review'
        rows=compiler.qualify_anchors(plan,self.documents)
        row=next(r for r in rows if r['set_code']=='SMH')
        self.assertIn('exact_news_target_cached_but_not_qualified',row['unresolved_conflicts'])
        self.assertNotIn('exact_news_target_not_in_authorized_cache',row['unresolved_conflicts'])
        self.assertFalse(row['exact_publisher_document']['qualified']);self.assertIsNone(row['release_date'])

    def test_four_outcomes_keep_exact_ids_and_all_holds_without_alias_or_date_transfer(self):
        original=copy.deepcopy(self.plan);rows=compiler.qualify_anchors(self.plan,self.documents)
        self.assertEqual(rows,compiler.qualify_anchors(self.plan,self.documents));self.assertEqual(self.plan,original)
        self.assertEqual({r['card_id'] for r in rows},{r['card_id'] for r in self.plan['subjects']})
        self.assertEqual(len({r['qualification_id'] for r in rows}),4)
        self.assertEqual(sum(r['qualified_provider_document_id'] is not None for r in rows),3)
        for row in rows:
            self.assertEqual(row['status'],'held_anchor_binding_unqualified')
            self.assertIsNone(row['release_date']);self.assertIsNone(row['physical_distribution_region'])
            self.assertFalse(row['exact_publisher_document']['qualified'])
            for key in catalog_locale.FALSE_CLAIMS:self.assertFalse(row[key])

    def test_repeated_numbers_and_shared_names_never_merge_provider_documents_or_anchors(self):
        documents=copy.deepcopy(self.documents)
        for doc in documents:doc['facts']['localized_names']={'ja':'same artwork promo foil stamp name'}
        rows=compiler.qualify_anchors(self.plan,documents)
        self.assertEqual(len(rows),4);self.assertEqual(len({r['card_id'] for r in rows}),4)
        self.assertEqual(len({r['qualified_provider_document_id'] for r in rows if r['qualified_provider_document_id']}),3)

    def test_missing_duplicate_or_foreign_anchors_and_variant_siblings_abstain(self):
        bad=copy.deepcopy(self.plan);bad['subjects'].pop()
        with self.assertRaises(ValueError):compiler.qualify_anchors(bad,self.documents)
        for field,value in [('language','en'),('collector_number','002/020'),('card_id','ja:DS:001/020:foil-stamp'),
                            ('publisher_card_url','https://merchant.invalid/35030')]:
            bad=copy.deepcopy(self.plan);bad['subjects'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):compiler.qualify_anchors(bad,self.documents)
        with self.assertRaises(ValueError):compiler.qualify_anchors(self.plan,self.documents+[self.documents[0]])

    def test_forged_permissions_dates_regions_and_caption_coordinates_abstain(self):
        for field,value in [('purchase_allowed',True),('release_date','2012-01-27'),('physical_distribution_region','JP')]:
            bad=copy.deepcopy(self.plan);bad['subjects'][0][field]=value
            with self.assertRaises(ValueError):compiler.qualify_anchors(bad,self.documents)
        for field,value in [('caption_status','provider_declaration_only'),('language','en'),('collector_number','002/020')]:
            bad=copy.deepcopy(self.plan);bad['requests'][0]['subject_bindings'][0][field]=value
            with self.assertRaises(ValueError):compiler.qualify_anchors(bad,self.documents)

    def test_duplicate_requests_and_ambiguous_caption_bindings_abstain(self):
        bad=copy.deepcopy(self.plan);bad['requests'].append(bad['requests'][0])
        with self.assertRaises(ValueError):compiler.qualify_anchors(bad,self.documents)
        bad=copy.deepcopy(self.plan);bad['requests'][0]['subject_bindings']*=2
        with self.assertRaises(ValueError):compiler.qualify_anchors(bad,self.documents)

    def test_source_blob_and_path_escape_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=Path(directory);path=repo/'header.ts';raw=header();path.write_bytes(raw)
            self.assertEqual(compiler.checked_source(repo,'header.ts',blob(raw)),raw)
            path.write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError,'pinned Git blob'):compiler.checked_source(repo,'header.ts',blob(raw))
            with self.assertRaisesRegex(ValueError,'escapes'):compiler.checked_source(repo,'../escape.ts',blob(raw))
            path.unlink();path.symlink_to(repo.parent/'outside.ts')
            with self.assertRaisesRegex(ValueError,'escapes'):compiler.checked_source(repo,'header.ts',blob(raw))

    def test_offline_git_command_disables_origin_and_lazy_fetch_without_mutating_config(self):
        output='100644 blob '+'a'*40+'\tLICENSE\n'
        with patch.object(compiler.subprocess,'check_output',side_effect=['origin\n',output]) as call:
            self.assertEqual(compiler.git_tree(Path('/fixture'),['LICENSE']),{'LICENSE':'a'*40})
            args,kwargs=call.call_args_list[1]
            self.assertIn('remote.origin.url=/dev/null',args[0]);self.assertIn('remote.origin.promisor=false',args[0])
            self.assertIn(compiler.REVISION,args[0]);self.assertEqual(kwargs['env']['GIT_NO_LAZY_FETCH'],'1')
            self.assertEqual(kwargs['env']['GIT_TERMINAL_PROMPT'],'0')
        with patch.object(compiler.subprocess,'check_output',return_value='origin\nextra\n') as call:
            with self.assertRaisesRegex(ValueError,'origin remote'):compiler.git_tree(Path('/fixture'),['LICENSE'])
            self.assertEqual(call.call_count,1)

    def test_git_symlink_nonblob_and_duplicate_entries_abstain(self):
        for output in ['120000 blob '+'a'*40+'\tLICENSE\n','040000 tree '+'a'*40+'\tLICENSE\n',
                       ('100644 blob '+'a'*40+'\tLICENSE\n')*2]:
            with patch.object(compiler.subprocess,'check_output',side_effect=['origin\n',output]):
                with self.assertRaises(ValueError):compiler.git_tree(Path('/fixture'),['LICENSE'])

    def fixture_build(self,directory):
        root=Path(directory);repo=root/'provider';repo.mkdir();(root/'catalog').mkdir()
        license_raw=b'test-only reviewed metadata license'
        (repo/'LICENSE').write_bytes(license_raw);(root/'catalog/TCGDEX-LICENSE').write_bytes(license_raw)
        pin={'LICENSE':blob(license_raw)}
        for code,path in compiler.PATHS.items():
            target=repo/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(header(code))
            pin[path]=blob(target.read_bytes())
        return root,repo,pin

    def test_build_is_repeatable_and_rejects_license_drift_and_new_card_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root,repo,pin=self.fixture_build(directory)
            with patch.object(compiler.readiness,'build',return_value=self.plan),patch.object(compiler,'git_tree',side_effect=[pin,{},pin,{}]):
                first=compiler.build(root/'db',root,root/'cache',repo,self.TIME)
                self.assertEqual(first,compiler.build(root/'db',root,root/'cache',repo,self.TIME))
                self.assertEqual(first[2]['qualified_cross_provider_anchor_bindings'],0)
            with patch.object(compiler.readiness,'build',return_value=self.plan),patch.object(compiler,'git_tree',side_effect=[pin,{'new.ts':'d'*40}]):
                with self.assertRaisesRegex(ValueError,'card entries'):compiler.build(root/'db',root,root/'cache',repo,self.TIME)
            (root/'catalog/TCGDEX-LICENSE').write_bytes(b'changed')
            with patch.object(compiler.readiness,'build',return_value=self.plan),patch.object(compiler,'git_tree',return_value=pin):
                with self.assertRaisesRegex(ValueError,'license differs'):compiler.build(root/'db',root,root/'cache',repo,self.TIME)

    def test_input_database_or_cache_drift_during_inspection_abstains(self):
        with tempfile.TemporaryDirectory() as directory:
            root,repo,pin=self.fixture_build(directory)
            changed=copy.deepcopy(self.plan);changed['snapshot']['database_sha256']='d'*64
            with patch.object(compiler.readiness,'build',side_effect=[self.plan,changed]),patch.object(compiler,'git_tree',side_effect=[pin,{}]):
                with self.assertRaisesRegex(ValueError,'inputs changed'):compiler.build(root/'db',root,root/'cache',repo,self.TIME)
            original=compiler.document_record
            def mutate(*args):
                result=original(*args);(repo/args[0]).write_bytes(b'modified');return result
            with patch.object(compiler.readiness,'build',return_value=self.plan),patch.object(compiler,'git_tree',side_effect=[pin,{}]),patch.object(compiler,'document_record',side_effect=mutate):
                with self.assertRaisesRegex(ValueError,'pinned Git blob'):compiler.build(root/'db',root,root/'cache',repo,self.TIME)

    def test_cli_refuses_overwrite_and_emits_hash_bound_metadata_only(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'qualified';rows=compiler.qualify_anchors(self.plan,self.documents)
            args=['qualifier','--db','offline.sqlite3','--cache','offline-cache','--source-repo','offline-provider',
                  '--output-dir',str(output),'--inspected-at',self.TIME]
            result=(self.documents,rows,{'verified_provider_documents':3,'anchor_outcomes':4,
                    'qualified_exact_publisher_product_documents':0,'qualified_cross_provider_anchor_bindings':0,'new_identities':0},
                    {compiler.PATHS['DS']:header()},b'test-only license')
            with patch.object(sys,'argv',args),patch.object(compiler,'build',return_value=result) as build:
                compiler.main()
                report=json.loads((output/'coverage-report.json').read_text())
                for path,sha in report['file_hashes'].items():self.assertEqual(hashlib.sha256((output/path).read_bytes()).hexdigest(),sha)
                with self.assertRaises(FileExistsError):compiler.main()
                self.assertEqual(build.call_count,1)


if __name__=='__main__':unittest.main()
