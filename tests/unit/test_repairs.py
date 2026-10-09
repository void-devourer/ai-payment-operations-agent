"""Reject wrong identities and malformed receipts before treating a grant as known."""

import unittest
from pydantic import ValidationError
from backend.app.repairs import canonical_digest, ProposalDecision, valid_receipt


class RepairContracts(unittest.TestCase):
    def setUp(self):
        self.payload = {'operation_id': 'op_a', 'workspace_id': 'ws_a', 'purchase_id': 'p_a',
                        'customer_id': 'c_a', 'product_id': 'digital_pass', 'expected_revision': 0}
        self.receipt = {key: self.payload[key] for key in ('operation_id','workspace_id','purchase_id','customer_id','product_id')}
        self.receipt.update(result='granted', revision=1, payload_digest=canonical_digest(self.payload))

    def test_digest_is_canonical_and_includes_preconditions(self):
        self.assertEqual(canonical_digest(self.payload), canonical_digest(dict(reversed(list(self.payload.items())))))
        self.assertNotEqual(canonical_digest(self.payload), canonical_digest(self.payload | {'expected_revision': 1}))

    def test_receipt_matches_exact_operation_payload_and_revision(self):
        self.assertTrue(valid_receipt(self.receipt, self.payload))
        for key in ('operation_id','workspace_id','purchase_id','customer_id','product_id','payload_digest'):
            with self.subTest(field=key):
                self.assertFalse(valid_receipt(self.receipt | {key: 'different'}, self.payload))
        for revision in (0, 2, True, -1, '1', None):
            self.assertFalse(valid_receipt(self.receipt | {'revision': revision}, self.payload))

    def test_unknown_receipt_shapes_and_results_never_establish_outcome(self):
        for value in (None, [], 'granted', {}, self.receipt | {'result': 'success'}):
            self.assertFalse(valid_receipt(value, self.payload))

    def test_bound_precondition_receipt_is_valid_but_not_a_grant(self):
        self.assertTrue(valid_receipt(self.receipt | {'result': 'access_precondition_conflict', 'revision': 4}, self.payload))

    def test_decision_forbids_extra_target_fields(self):
        with self.assertRaises(ValidationError):
            ProposalDecision(payload_digest='a'*64, decision='approve', reason='Reviewed', purchase_id='different')
        with self.assertRaises(ValidationError):
            ProposalDecision(payload_digest='a'*64, decision='execute', reason='Reviewed')
