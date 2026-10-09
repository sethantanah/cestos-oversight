import unittest,uuid
from datetime import UTC,datetime,timedelta
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app.services.auth import AuthService
class SessionDuration(unittest.TestCase):
 def service(self):
  service=AuthService.__new__(AuthService);service.settings=SimpleNamespace(login_session_hours=72,access_token_expire_minutes=15);service.session=SimpleNamespace(add=Mock());service.metadata={};return service
 def test_new_session_lasts_three_days(self):
  service=self.service();now=datetime.now(UTC)
  with patch('app.services.auth.create_access_token',return_value='access') as access:
   service.issue_tokens(SimpleNamespace(id=uuid.uuid4(),organization_id=uuid.uuid4(),token_version=0))
  saved=service.session.add.call_args.args[0]
  self.assertAlmostEqual((saved.expires_at-now).total_seconds(),72*3600,delta=2)
  self.assertEqual(access.call_args.kwargs['expires_at'],saved.expires_at)
 def test_renewal_keeps_deadline_and_caps_final_access_token(self):
  service=self.service();deadline=datetime.now(UTC)+timedelta(seconds=45)
  with patch('app.services.auth.create_access_token',return_value='access') as access:
   response=service.issue_tokens(SimpleNamespace(id=uuid.uuid4(),organization_id=uuid.uuid4(),token_version=0),deadline)
  self.assertEqual(service.session.add.call_args.args[0].expires_at,deadline)
  self.assertEqual(access.call_args.kwargs['expires_at'],deadline)
  self.assertLessEqual(response.expires_in,45)
