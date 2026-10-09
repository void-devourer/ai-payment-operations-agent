from datetime import UTC,datetime,timedelta
import unittest

from backend.app.cases import present


class CaseFreshnessTests(unittest.TestCase):
    def row(self):
        now=datetime.now(UTC)
        return {'outcome':'eligible','reasons':['paid_access_missing'],'is_current':True,
            'windows':{name:{'complete':True,'started_at':(now-timedelta(seconds=2)).isoformat(),
                'finished_at':now.isoformat()} for name in ('payment','reversal','access')}}

    def test_freshness_expires_from_oldest_read_not_render_time(self):
        row=self.row()
        row['windows']['payment']['started_at']=(datetime.now(UTC)-timedelta(seconds=45)).isoformat()
        result=present(row)
        self.assertTrue(result['evidence_fresh'])
        self.assertLess(datetime.fromisoformat(result['fresh_until'])-datetime.now(UTC),timedelta(seconds=16))
        row['windows']['payment']['started_at']=(datetime.now(UTC)-timedelta(seconds=61)).isoformat()
        self.assertEqual(present(row)['current_outcome'],'awaiting_evidence')

    def test_superseded_and_incomplete_never_present_as_eligible(self):
        row=self.row()
        row['is_current']=False
        self.assertFalse(present(row)['evidence_fresh'])
        row['is_current']=True
        row['windows']['reversal']['complete']=False
        self.assertEqual(present(row)['current_reasons'],['stale_or_incomplete_observation'])
