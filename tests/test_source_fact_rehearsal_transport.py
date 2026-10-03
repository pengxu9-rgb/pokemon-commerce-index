import io,json,unittest
from http.client import IncompleteRead
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request
from scripts import rehearse_source_image_facts as rehearsal

class Response(io.BytesIO):
    status=200

class RehearsalTransportTests(unittest.TestCase):
    def test_truncated_body_retries_same_request_and_retains_error_without_token(self):
        request=Request('https://example.invalid/catalog-card',headers={'Authorization':'Bearer private-fixture'})
        errors=[]
        with patch.object(rehearsal,'urlopen',side_effect=[IncompleteRead(b'partial',9),Response(b'{"ok":true}')]) as open_request:
            self.assertEqual(rehearsal.fetch_json(request,errors,'/catalog-card'),(200,{'ok':True}))
        self.assertEqual(open_request.call_count,2)
        self.assertTrue(all(call.args[0] is request for call in open_request.call_args_list))
        self.assertEqual(errors,[dict(route='/catalog-card',attempt=1,error_type='IncompleteRead')])
        self.assertNotIn('private-fixture',json.dumps(errors))

    def test_repeated_truncation_stops_after_three_attempts(self):
        errors=[]
        with patch.object(rehearsal,'urlopen',side_effect=IncompleteRead(b'partial',9)) as opening:
            with self.assertRaises(IncompleteRead):rehearsal.fetch_json(Request('https://example.invalid/'),errors,'/catalog-card')
        self.assertEqual(opening.call_count,3);self.assertEqual([e['attempt'] for e in errors],[1,2,3])

    def test_validation_http_failure_is_not_retried_or_hidden(self):
        errors=[];failure=HTTPError('https://example.invalid/',400,'bad input',{},io.BytesIO(b'{"error":"invalid"}'))
        with patch.object(rehearsal,'urlopen',side_effect=failure) as opening:
            self.assertEqual(rehearsal.fetch_json(Request('https://example.invalid/'),errors,'/card-comparison'),(400,{'error':'invalid'}))
        self.assertEqual(opening.call_count,1);self.assertEqual(errors,[])
