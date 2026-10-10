"""The benchmark must reject reassuring states with incomplete or wrong facts."""
import copy
import unittest

from scripts.benchmark_investigation import matches


class InvestigationOracleTests(unittest.TestCase):
    def setUp(self):
        self.facts = {'payment_complete': True, 'reversal_complete': True, 'access_complete': True,
                      'payments': [{'status': 'succeeded', 'currency': 'usd', 'amount_received_minor': 2500}],
                      'access': {'status': 'active', 'revision': 1}, 'refunds': [], 'disputes': []}

    def test_incomplete_or_wrong_money_never_counts_as_correct_normal_fulfillment(self):
        self.assertTrue(matches(self.facts, 'normal'))
        for key in ('payment_complete', 'reversal_complete', 'access_complete'):
            with self.subTest(key=key):
                self.assertFalse(matches(self.facts | {key: False}, 'normal'))
        for changed in ({'currency': 'eur'}, {'amount_received_minor': 2499}, {'status': 'failed'}):
            facts = copy.deepcopy(self.facts)
            facts['payments'][0].update(changed)
            self.assertFalse(matches(facts, 'normal'))

    def test_reversal_or_second_transition_cannot_pass_normal_or_missing_case(self):
        self.assertFalse(matches(self.facts | {'refunds': [{'id': 'refund'}]}, 'normal'))
        self.assertFalse(matches(self.facts | {'disputes': [{'id': 'dispute'}]}, 'normal'))
        self.assertFalse(matches(self.facts | {'access': {'status': 'active', 'revision': 2}}, 'normal'))
        self.assertFalse(matches(self.facts, 'missing'))

    def test_failed_payment_requires_no_received_money_and_no_access(self):
        facts = copy.deepcopy(self.facts)
        facts['payments'][0].update(status='failed', amount_received_minor=0)
        facts['access'] = {'status': 'inactive', 'revision': 0}
        self.assertTrue(matches(facts, 'failed'))
        facts['payments'][0]['amount_received_minor'] = 2500
        self.assertFalse(matches(facts, 'failed'))

    def test_two_successful_attempts_cannot_pass_single_purchase_oracle(self):
        self.assertFalse(matches(self.facts | {'payments': self.facts['payments'] * 2}, 'normal'))
