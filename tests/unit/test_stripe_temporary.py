from datetime import UTC,datetime,timedelta
import unittest
from unittest.mock import Mock

from scripts.check_stripe_temporary import temporary_profile


class TemporaryProfileTests(unittest.TestCase):
    def profile(self,*,key=None,expiry=None):
        path=Mock()
        path.read_text.return_value=('[default]\naccount_id="acct_fixture123"\n'
            f'test_mode_api_key="{key or "rkcs_"+"test_"+"x"*24}"\n'
            f'sandbox_expires_at="{expiry or (datetime.now(UTC)+timedelta(days=2)).date().isoformat()}"\n')
        return path

    def test_expired_and_live_profiles_are_rejected(self):
        for expiry in ((datetime.now(UTC)-timedelta(days=1)).date().isoformat(),datetime.now(UTC).date().isoformat()):
            with self.assertRaises(ValueError):
                temporary_profile(self.profile(expiry=expiry))
        for key in ('rkcs_'+'live_'+'x'*24,'sk_'+'test_'+'x'*24):
            with self.assertRaises(ValueError):
                temporary_profile(self.profile(key=key))

    def test_fresh_anonymous_test_profile_is_explicitly_supported(self):
        profile,expiry=temporary_profile(self.profile())
        self.assertEqual(profile['account_id'],'acct_fixture123')
        self.assertGreater(expiry,datetime.now(UTC).date())
