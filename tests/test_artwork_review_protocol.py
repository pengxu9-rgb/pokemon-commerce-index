import copy,json,tempfile,unittest
from pathlib import Path
from scripts.review_collector_artwork import bind_protocol,parse,MODEL


class ArtworkReviewProtocolTests(unittest.TestCase):
    def test_resume_requires_exact_frozen_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'protocol.json'
            original=dict(queue_sha256='a'*64,prompt_template_sha256='b'*64,
                          runtime_files_sha256={'runner':'c'*64},model=MODEL,project='fixture')
            first=bind_protocol(p,original)
            self.assertEqual(bind_protocol(p,copy.deepcopy(original)),first)
            for field in original:
                changed=copy.deepcopy(original);changed[field]='changed'
                with self.assertRaisesRegex(ValueError,'protocol changed'):bind_protocol(p,changed)
            self.assertEqual(json.loads(p.read_text()),original)

    def test_duplicate_species_and_truncated_response_are_rejected(self):
        finding=dict(identity_match='match',read_name='fixture',read_number='001/100',
                     depictions=[dict(dex_id=25,name='Pikachu',role='subject',detail='visible')],uncertainties='')
        def response(f):
            return dict(modelVersion=MODEL,candidates=[dict(finishReason='STOP',content={'parts':[{'text':json.dumps(f)}]})])
        self.assertEqual(parse(response(finding))[0],finding)
        duplicate=copy.deepcopy(finding);duplicate['depictions']*=2
        with self.assertRaisesRegex(ValueError,'invalid depiction'):parse(response(duplicate))
        truncated=response(finding);truncated['candidates'][0]['finishReason']='MAX_TOKENS'
        with self.assertRaisesRegex(ValueError,'incomplete'):parse(truncated)

if __name__=='__main__':unittest.main()
