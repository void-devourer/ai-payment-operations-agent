import hashlib
import hmac
import json
import unittest

from backend.app.evidence import retry_after
from backend.app.ingestion import parse_event,verify_signature


class IngressContractTests(unittest.TestCase):
    def event(self,**changes):
        return {"id":"evt_test","object":"event","account":"sim_acct_ws_a","livemode":False,
                "api_version":"simulator.v1","type":"payment_intent.succeeded","created":1000,
                "data":{"object":{"id":"sim_pi_test"}},**changes}

    def test_signature_uses_exact_bytes_and_accepts_rotated_signatures(self):
        raw=json.dumps(self.event()).encode()
        signature=hmac.new(b"test-key",b"1000."+raw,hashlib.sha256).hexdigest()
        verify_signature(raw,f"t=1000,v1=wrong,v1={signature}","test-key",now=1000)
        for body,header,key,now in ((raw+b" ",f"t=1000,v1={signature}","test-key",1000),
                                   (raw,f"t=1000,v1={signature}","wrong-key",1000),
                                   (raw,f"t=1000,v1={signature}","test-key",1301),
                                   (raw,f"t=1000,v1={signature}","test-key",699),
                                   (raw,f"t=1000,t=1000,v1={signature}","test-key",1000)):
            with self.subTest(header=header,now=now),self.assertRaises(ValueError):
                verify_signature(body,header,key,now)

    def test_scope_and_environment_are_strict(self):
        for changes in ({"livemode":True},{"livemode":0},{"account":"sim_acct_ws_b"},{"created":True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                parse_event(json.dumps(self.event(**changes)),"ws_a")

    def test_unsupported_version_is_quarantined_without_parsing_resource(self):
        _,state,intent=parse_event(json.dumps(self.event(api_version="future.v2",data=[])),"ws_a")
        self.assertEqual((state,intent),("quarantined",None))

    def test_unknown_type_is_recorded_as_ignored(self):
        self.assertEqual(parse_event(json.dumps(self.event(type="unhandled.event")),"ws_a")[1],"ignored")

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self):
        for raw in ('{"id":"one","id":"two"}','{"value":NaN}'):
            with self.assertRaises(ValueError):
                parse_event(raw,"ws_a")

    def test_reversal_routes_to_registered_intent_not_metadata(self):
        event=self.event(type="charge.refunded",data={"object":{"id":"refund_a","payment_intent":"sim_pi_real","metadata":{"purchase_id":"wrong"}}})
        self.assertEqual(parse_event(json.dumps(event),"ws_a")[2],"sim_pi_real")

    def test_retry_guidance_is_bounded(self):
        self.assertEqual(retry_after("9999"),300)
        self.assertEqual(retry_after("-1"),1)
        self.assertIsNone(retry_after("not a date"))
        self.assertIsNone(retry_after("nan"))
