"""Audit bounded localization growth, exact history preservation and no SKU merges."""
import argparse
import hashlib
import json
import re
import shutil
import tempfile
import unicodedata
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from pokemon_index import catalog_locale, catalog_question_resolver_v2, core
from scripts.audit_international_coverage import coverage, facts
from scripts.build_international_coverage_expansion import ENGLISH_COMPARISONS, MAX_JAPANESE, MAX_EXPANDED_JAPANESE, SETS, RetrievalScope, translated_query

PRIOR_MANIFEST = 'catalog-build-manifest-international-product-text-v1.json'
MANIFEST = 'catalog-build-manifest-international-coverage-expansion-v1.json'
LOCALES = 'catalog/international-coverage-expansion-v1/locales.jsonl'
APPEND_TABLES = {'catalog_locale_evidence', 'catalog_source_mapping'}
GENERATED_COLUMNS = {'card_relationship_assertion': 'asserted_at', 'card_identity_exception': 'applied_at',
                     'card_rarity_correction': 'applied_at', 'card_number_conflict_rule': 'applied_at'}


@dataclass(frozen=True)
class AuditProfile:
    prior_manifest: str
    manifest: str
    locales: str
    prior_inputs: int
    scope: RetrievalScope | None = None
    allow_bound_name_resolution_growth: bool = False

    def __post_init__(self):
        for value in (self.prior_manifest, self.manifest, self.locales):
            if (not isinstance(value, str) or not value or Path(value).is_absolute()
                    or '..' in Path(value).parts):
                raise ValueError('audit profile requires repository-relative paths')
        if (type(self.prior_inputs) is not int or self.prior_inputs < 65
                or self.scope is not None and not isinstance(self.scope, RetrievalScope)
                or type(self.allow_bound_name_resolution_growth) is not bool):
            raise ValueError('invalid audit profile count/scope')


def profile_or_default(profile):
    if profile is not None and not isinstance(profile, AuditProfile):
        raise ValueError('explicit profile must be a validated AuditProfile')
    return profile if profile is not None else AuditProfile(PRIOR_MANIFEST, MANIFEST, LOCALES, 68)


def tables(db):
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    if any(not re.fullmatch(r'[a-z_][a-z0-9_]*', name) for name in names):
        raise ValueError('unsupported table name')
    return names


def records(db, table):
    return [tuple(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]


def installed(db, rows):
    """Check SQL bindings as well as JSON; search alone cannot prove context scope."""
    if len({row['evidence_id'] for row in rows}) != len(rows):
        raise ValueError('duplicate evidence in batch')
    for row in rows:
        mapping, cid = catalog_locale.validate(db, row)
        evidence = db.execute('SELECT evidence_id,card_id,record_json FROM catalog_locale_evidence WHERE evidence_id=?',
                              (row['evidence_id'],)).fetchone()
        if not evidence or tuple(evidence) != (row['evidence_id'], cid, catalog_locale.encoded(row)):
            raise ValueError('installed evidence SQL binding differs from batch')
        found = db.execute('''SELECT card_id FROM catalog_source_mapping WHERE provider=? AND language=?
            AND region=? AND release_id=? AND native_id=? AND source_variant=?''', mapping).fetchone()
        if not found or found[0] != cid:
            raise ValueError('installed source mapping differs from batch')
    return True


def bounded(rows, *, scope=None):
    if scope is not None and not isinstance(scope, RetrievalScope):
        raise ValueError('explicit scope must be a validated RetrievalScope')
    if len({row['identity']['card_id'] for row in rows}) != len(rows):
        raise ValueError('duplicate printing ID in bounded batch')
    counts = Counter(row['identity']['language'] for row in rows)
    scopes = {row['identity']['set_code'] for row in rows if row['identity']['language'] == 'ja'}
    japanese_limit = MAX_EXPANDED_JAPANESE if scope and scope.expanded_batch else MAX_JAPANESE
    english = scope.english_records if scope else ENGLISH_COMPARISONS
    if (set(counts) != {'ja', 'en'} or not 1 <= counts['ja'] <= japanese_limit
            or counts['en'] != english):
        raise ValueError('bounded expansion scope differs')
    if scope is None:
        if not 3 <= len(scopes) <= 5 or not scopes.issubset(SETS):
            raise ValueError('bounded expansion scope differs')
    elif counts['ja'] != scope.japanese_records or scopes != set(scope.sets):
        raise ValueError('explicit bounded expansion scope differs')


def preserved(before, after, additions):
    if tables(before) != tables(after):
        raise ValueError('schema table inventory changed')
    if records(before, 'sqlite_sequence') != records(after, 'sqlite_sequence'):
        raise ValueError('historical sequences changed')
    checks = {}
    for table in tables(before):
        old = records(before, table); new = records(after, table)
        if table in APPEND_TABLES:
            checks[table] = new[:len(old)] == old and len(new) == len(old) + additions
        else:
            checks[table] = old == new
    if not all(checks.values()):
        raise ValueError('historical records changed: ' + ','.join(k for k, v in checks.items() if not v))
    return checks


def bound_name_resolution(before, after, row, name, old, new):
    """Allow only gains enabled by exact current per-record name evidence."""
    card = row['identity']
    if (old['resolution']['status'] != 'not_attempted'
            or old['reason'] != 'reviewed_name_record_binding_required'
            or old['resolution']['candidate_ids']
            or new['resolution']['status'] not in {'unique','multiple_candidates','not_attempted'}):
        return False
    if new['resolution']['status'] == 'not_attempted':
        return new['reason'] == 'reviewed_name_record_binding_required' and not new['resolution']['candidate_ids']
    aliases = new.get('name_aliases', [])
    if not aliases or any(a['category'] != 'Pokemon' or a.get('requires_card_binding') is not True for a in aliases):
        return False
    for cid in new['resolution']['candidate_ids']:
        candidate = after.execute('SELECT c.*,cl.category FROM card c JOIN card_classification cl USING(card_id) WHERE c.card_id=?',(cid,)).fetchone()
        if (not candidate or candidate['language'] != card['language'] or candidate['set_code'] != card['set_code']
                or candidate['collector_number'] != card['collector_number'] or candidate['category'] != 'Pokemon'
                or catalog_question_resolver_v2.full_name_key(candidate['name']) != catalog_question_resolver_v2.full_name_key(card['name'])
                or not catalog_locale.has_current_alias(after,cid,aliases)):
            return False
    return card['card_id'] in new['resolution']['candidate_ids']


def append(before_path, output, root, *, profile=None):
    """Apply only the new locale input to a copy; keep all historical timestamps."""
    if output.exists():
        raise FileExistsError('incremental snapshot already exists')
    settings = profile_or_default(profile)
    locale_bytes = (root / settings.locales).read_bytes()
    rows = [json.loads(line) for line in locale_bytes.splitlines()]
    bounded(rows, scope=settings.scope)
    before_signature = hashlib.sha256(before_path.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        temporary = Path(directory) / 'append.sqlite3'
        shutil.copyfile(before_path, temporary)
        with closing(core.connect(temporary)) as db:
            result = catalog_locale.import_evidence(db, rows)
            if result != dict(inserted=len(rows), unchanged=0, quarantined=0):
                raise ValueError('batch must append distinct current bindings: ' + str(result))
            installed(db, rows)
        with closing(core.connect(before_path, readonly=True)) as before, closing(core.connect(temporary, readonly=True)) as after:
            preserved(before, after, len(rows))
        if hashlib.sha256(before_path.read_bytes()).hexdigest() != before_signature:
            raise ValueError('prior snapshot changed during append')
        if (root / settings.locales).read_bytes() != locale_bytes:
            raise ValueError('locale input changed during append')
        # Exclusive creation avoids replacing another session's output.
        with output.open('xb') as handle:
            handle.write(temporary.read_bytes())
    return result


def run(before_path, after_path, rebuilt_path, root, *, profile=None):
    settings = profile_or_default(profile)
    paths = (before_path, after_path, rebuilt_path)
    signatures = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    original = json.loads((root / 'catalog-build-manifest-source-binding-v1.json').read_text())
    prior = json.loads((root / settings.prior_manifest).read_text())
    manifest_bytes = (root / settings.manifest).read_bytes(); manifest = json.loads(manifest_bytes)
    if (len(original['steps']) != 65 or len(prior['steps']) != settings.prior_inputs
            or len(manifest['steps']) != settings.prior_inputs + 1
            or manifest['steps'][:-1] != prior['steps'] or prior['steps'][:65] != original['steps']
            or manifest['expected'] != prior['expected']
            or manifest['steps'][-1]['operation'] != 'import-catalog-locales'
            or manifest['steps'][-1]['path'] != settings.locales):
        raise ValueError('ordered original/prior prefix or expected inventory changed')
    for step in manifest['steps']:
        if hashlib.sha256((root / step['path']).read_bytes()).hexdigest() != step['sha256']:
            raise ValueError('manifest input hash differs')
    rows = [json.loads(line) for line in (root / settings.locales).read_text().splitlines()]
    bounded(rows, scope=settings.scope)
    with closing(core.connect(before_path, readonly=True)) as before, closing(core.connect(after_path, readonly=True)) as after, closing(core.connect(rebuilt_path, readonly=True)) as rebuilt:
        history = preserved(before, after, len(rows))
        installed(after, rows); installed(rebuilt, rows)
        rebuild_checks = {}; generated_timestamps = {}
        if tables(after) != tables(rebuilt):
            raise ValueError('rebuild schema inventory differs')
        for table in tables(after):
            left = records(after, table); right = records(rebuilt, table)
            if table in GENERATED_COLUMNS:
                columns = [r[1] for r in after.execute('PRAGMA table_info(' + table + ')')]
                column = GENERATED_COLUMNS[table]; index = columns.index(column)
                generated_timestamps[table] = dict(column=column, changed=sum(a[index] != b[index] for a, b in zip(left, right)))
                left = [r[:index] + r[index+1:] for r in left]
                right = [r[:index] + r[index+1:] for r in right]
            rebuild_checks[table] = left == right
        if not all(rebuild_checks.values()):
            raise ValueError('independent rebuild differs outside four named generated timestamp columns')
        before_coverage = coverage(before); after_coverage = coverage(after)
        if {k: v for k, v in before_coverage.items() if k != 'localized_bindings'} != {k: v for k, v in after_coverage.items() if k != 'localized_bindings'}:
            raise ValueError('coverage/eligibility changed outside localization bindings')
        queries = []
        for row in rows:
            card = row['identity']; alias = row['name_aliases'][0]
            query = translated_query(card, alias)
            search = lambda db, q, **kwargs: core.catalog_search_internal(db, q, set_code=card['set_code'], limit=100, **kwargs)
            target = lambda result: card['card_id'] in {c['card_id'] for c in result['cards']}
            b = search(before, query); a = search(after, query)
            native = search(after, f"{card['name']} {card['language']} {card['set_code']} {card['collector_number']}")
            wide = ''.join(chr(ord(char) + 0xfee0) if 0x21 <= ord(char) <= 0x7e else char for char in query)
            unicode_found = target(search(after, unicodedata.normalize('NFD', wide)))
            other_language = 'en' if card['language'] == 'ja' else 'ja'
            wrong_language_excludes = not target(search(after, query, language=other_language))
            name = alias['name_en' if card['language'] == 'ja' else 'name_ja']
            old_lookup = catalog_question_resolver_v2.resolve_question(before, facts(row, name))
            new_lookup = catalog_question_resolver_v2.resolve_question(after, facts(row, name))
            old_resolution = old_lookup['resolution']; new_resolution = new_lookup['resolution']
            unchanged_resolution = (old_resolution['status'], old_resolution['candidate_ids']) == (new_resolution['status'], new_resolution['candidate_ids'])
            checks = dict(before_missing=not target(b), after_found=target(a), native_found=target(native),
                unicode_found=unicode_found, wrong_language_excludes_target=wrong_language_excludes,
                resolver_identity_result_unchanged=unchanged_resolution)
            if settings.allow_bound_name_resolution_growth:
                checks.pop('resolver_identity_result_unchanged')
                checks['resolver_current_record_name_scope_preserved'] = bound_name_resolution(before,after,row,name,old_lookup,new_lookup)
            if not all(checks.values()):
                raise ValueError('retrieval/identity regression: ' + card['card_id'] + ' ' + str(checks))
            queries.append(dict(card_id=card['card_id'], language=card['language'], query=query,
                before_total=b['total'], after_total=a['total'], **checks,
                resolver_status=new_resolution['status'], resolver_candidate_ids=new_resolution['candidate_ids']))
            if settings.allow_bound_name_resolution_growth:
                queries[-1].update(resolver_before=old_resolution,resolver_reason=new_lookup['reason'])
        # Also test the unfiltered internal entry point on ten diverse records.
        unfiltered = []
        for row in rows[::max(1, len(rows)//10)][:10]:
            query = translated_query(row['identity'], row['name_aliases'][0])
            cid = row['identity']['card_id']
            found = cid in {c['card_id'] for c in core.catalog_search_internal(after, query, limit=100)['cards']}
            if not found:
                raise ValueError('unfiltered retrieval lost exact target')
            unfiltered.append(dict(card_id=cid, query=query, after_found=True))
        report = dict(schema='pokemon.international-coverage-expansion-audit.v1',
            original_manifest_inputs=65, manifest_inputs_before=settings.prior_inputs, manifest_inputs_after=settings.prior_inputs + 1,
            preserved_ordered_prefix=True, manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            database_sha256=signatures, before=before_coverage, after=after_coverage,
            new_localized_bindings=len(rows), batch_by_set=dict(Counter(r['identity']['language'] + ':' + r['identity']['set_code'] for r in rows)),
            queries=queries, unfiltered_queries=unfiltered, translated_gaps_closed=len(queries),
            historical_tables_preserved=history, rebuild_tables_equal=rebuild_checks,
            rebuild_generated_timestamp_differences=generated_timestamps,
            rebuild_timestamp_scope='Only legacy builder-generated asserted_at/applied_at on four explicitly named tables excluded from independent rebuild comparison; incremental snapshot preserves all historical columns.',
            source_mappings_after=after.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0],
            exact_installed_evidence_and_mapping_bindings=True,
            held_candidates_after=after.execute('SELECT count(*) FROM catalog_coverage_candidate').fetchone()[0],
            quarantine_after=after.execute('SELECT count(*) FROM catalog_identity_quarantine').fetchone()[0],
            scope='existing-record retrieval; no new identities, dates, counterpart relationships, images, offers or permissions')
        if settings.scope is not None:
            report['batch_scope'] = dict(name=settings.scope.name, sets=list(settings.scope.sets),
                japanese_records=settings.scope.japanese_records, english_records=settings.scope.english_records)
            if settings.scope.expanded_batch:report['batch_scope']['expanded_batch']=True
        if settings.allow_bound_name_resolution_growth:
            report['resolver_status_counts'] = dict(Counter(q['resolver_status'] for q in queries))
            report['resolver_hold_reasons'] = dict(Counter(q['resolver_reason'] for q in queries if q['resolver_status']=='not_attempted'))
            report['resolver_scope'] = 'Only already reviewed full names enabled by exact current record bindings; no new concept or printing identity.'
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory) / 'reimport.sqlite3'; shutil.copyfile(after_path, scratch)
        with closing(core.connect(scratch)) as db:
            old = {table: records(db, table) for table in tables(db)}
            result = catalog_locale.import_evidence(db, rows)
            if result != dict(inserted=0, unchanged=len(rows), quarantined=0) or any(records(db, table) != values for table, values in old.items()):
                raise ValueError('idempotent reimport changed records')
            report['idempotent_reimport'] = result
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != signatures[str(path)] for path in paths):
        raise ValueError('audited snapshots changed')
    if (root / settings.manifest).read_bytes() != manifest_bytes:
        raise ValueError('manifest changed during audit')
    for step in manifest['steps']:
        if hashlib.sha256((root / step['path']).read_bytes()).hexdigest() != step['sha256']:
            raise ValueError('manifest input changed during audit')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--rebuilt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.before, args.after, args.rebuilt, Path.cwd())
    with args.output.open('x') as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('new_localized_bindings', 'translated_gaps_closed', 'idempotent_reimport')}))


if __name__ == '__main__':
    main()
