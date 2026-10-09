import copy
from datetime import UTC,datetime,timedelta
import unittest

from backend.app.detection.policy import Outcome
from backend.app.detection.projection import decision_for,material_fingerprint


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,9,12,tzinfo=UTC)
        self.purchase={'workspace_id':'ws_a','purchase_id':'p_1','customer_id':'c_1','product_id':'digital_pass',
            'provider_customer_id':'c_1','connection_id':'sim_ws_a','expected_amount_minor':2500,'currency':'usd'}
        self.scope={'account_id':'sim_acct_ws_a','environment':'simulated'}
        window={'started_at':self.now.isoformat(),'finished_at':self.now.isoformat(),'complete':True}
        self.facts={'scope':self.scope|{'workspace_id':'ws_a','connection_id':'sim_ws_a'},
            'registered_attempts':['pi_1'],'payments':[{'payment_intent_id':'pi_1','status':'succeeded',
                'amount_received_minor':2500,'currency':'usd','reversal_generation':0}],
            'refunds':[],'disputes':[],'access':{key:self.purchase[key] for key in ('workspace_id','purchase_id','customer_id','product_id')},
            'windows':{name:window.copy() for name in ('payment','reversal','access')},
            'payment_complete':True,'reversal_complete':True,'access_complete':True,'financial_complete':False}
        self.facts['access'].update(status='inactive',revision=0,ever_activated=False)
        self.clocks={'pi_1':self.now-timedelta(seconds=120)}

    def decision(self):
        return decision_for(self.purchase,['pi_1'],self.facts,self.clocks,self.scope,self.now)

    def test_complete_bundle_integrates_policy_without_finance_gate(self):
        self.assertEqual(self.decision().outcome,Outcome.ELIGIBLE)
        self.clocks={}
        self.assertEqual(self.decision().outcome,Outcome.AWAITING_EVIDENCE)
        self.clocks={'pi_1':self.now}
        self.assertEqual(self.decision().outcome,Outcome.PENDING)

    def test_extra_attempt_and_scope_are_not_trusted(self):
        self.facts['payments'].append(self.facts['payments'][0]|{'payment_intent_id':'pi_foreign'})
        self.assertEqual(self.decision().reasons,('attempt_coverage_mismatch',))
        self.facts['payments'].pop()
        self.facts['scope']['account_id']='other_account'
        self.assertEqual(self.decision().outcome,Outcome.AWAITING_EVIDENCE)

    def test_incomplete_history_is_not_an_empty_success(self):
        self.facts['reversal_complete']=False
        self.assertEqual(self.decision().outcome,Outcome.AWAITING_EVIDENCE)

    def test_reversal_on_active_access_requires_review(self):
        self.facts['access'].update(status='active',ever_activated=True,revision=1)
        self.facts['refunds']=[{'id':'re_1','status':'failed'}]
        self.assertEqual(self.decision().outcome,Outcome.MANUAL_REVIEW)

    def test_dismissal_fingerprint_ignores_read_time_but_tracks_material_change(self):
        before=material_fingerprint(self.facts)
        self.facts['windows']['payment']['finished_at']=(self.now+timedelta(seconds=5)).isoformat()
        self.facts['payments'][0]['reversal_generation']=2
        self.assertEqual(before,material_fingerprint(self.facts))
        changed=copy.deepcopy(self.facts)
        changed['access']['revision']=1
        self.assertNotEqual(before,material_fingerprint(changed))
        changed=copy.deepcopy(self.facts)
        changed['refunds']=[{'id':'re_1','status':'pending'}]
        self.assertNotEqual(before,material_fingerprint(changed))
