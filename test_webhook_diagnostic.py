"""Live HTTP local tests of read-only Mercado Pago webhook diagnostic."""
import hashlib
import hmac
import json
import os
import time
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from test_online import ServerTests, mod


class WebhookDiagnosticTests(unittest.TestCase):
    request = ServerTests.request

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        mod.DATA=Path(cls.tmp.name)
        mod.UPLOADS=mod.DATA/'uploads'
        mod.DELIVERIES=mod.DATA/'entregas'
        mod.DB=mod.DATA/'data.sqlite'
        cls.env=patch.dict(os.environ, {
            'STAYVISION_ADMIN_USER':'stayowner',
            'STAYVISION_ADMIN_PASSWORD':'long-demo-strong-pass-EXAMPLE',
            'STAYVISION_PUBLIC_URL':'https://example.up.railway.app',
            'MP_TEST_ACCESS_TOKEN':'',
            'MP_PRODUCTION_ACCESS_TOKEN':''
        })
        cls.env.start()
        mod.ensure_online_storage();mod.init_db();mod.initialize_admin()
        cls.web=ThreadingHTTPServer(('127.0.0.1',0),mod.Handler)
        cls.thread=threading.Thread(target=cls.web.serve_forever,daemon=True)
        cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.web.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown();cls.web.server_close();cls.thread.join(5)
        cls.env.stop();cls.tmp.cleanup()

    def webhook(self, payment_id='123456789', action='payment.updated', request_id='webhook-test-1',
                secret='STAYVISION-HMAC-TEST-NOT-REAL', change_header=False,
                mismatch_body=False, sign=True, origin=None):
        ts = str(int(time.time() * 1000))
        manifest = f'id:{payment_id};request-id:{request_id};ts:{ts};'
        digest = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
        if change_header: digest = '0'*64
        headers = {'Content-Type': 'application/json', 'X-Request-Id': request_id,
                   'X-Signature': f'ts={ts},v1={digest}'}
        if origin is not None: headers['Origin'] = origin
        payload = json.dumps({'type': 'payment', 'action': action,
                    'data': {'id': '23456' if mismatch_body else payment_id},
                    'live_mode': True}).encode()
        route = '/api/mp/webhook?type=payment&data.id='+payment_id
        with patch.dict(os.environ, {'MP_WEBHOOK_SECRET': secret}):
            return self.request(route, method='POST', body=payload, headers=headers)

    def test_signed_event_stored_once_without_approving_any_order(self):
        with mod.connection() as db:
            before = db.execute('SELECT COUNT(*) FROM mp_webhook_audit').fetchone()[0]
            paid_before = db.execute("SELECT COUNT(*) FROM orders WHERE payment_status='pago'").fetchone()[0]
        c,b,_ = self.webhook(payment_id='123456789',request_id='stage4valid1')
        self.assertEqual(c,200,b)
        self.assertFalse(json.loads(b)['payment_updated'])
        c,b,_ = self.webhook(payment_id='123456789',request_id='stage4valid1')
        self.assertEqual(c,200,b)
        with mod.connection() as db:
            after=db.execute('SELECT COUNT(*) FROM mp_webhook_audit').fetchone()[0]
            paid_after = db.execute("SELECT COUNT(*) FROM orders WHERE payment_status='pago'").fetchone()[0]
        self.assertEqual(after,before+1)
        self.assertEqual(paid_after,paid_before)

    def test_invalid_signature_not_recorded(self):
        with mod.connection() as db: before=db.execute('SELECT COUNT(*) FROM mp_webhook_audit').fetchone()[0]
        c,b,_=self.webhook(request_id='forged-webhook-99',change_header=True)
        self.assertEqual(c,401,b)
        c,b,_=self.webhook(request_id='x-mismatch-id',mismatch_body=True)
        self.assertEqual(c,400,b)
        c,b,_=self.webhook(request_id='browser-webhook',origin='https://attacker.invalid')
        self.assertEqual(c,403,b)
        with mod.connection() as db: after=db.execute('SELECT COUNT(*) FROM mp_webhook_audit').fetchone()[0]
        self.assertEqual(after,before)

    def test_admin_read_access_requires_login_and_reports_only_metadata(self):
        c,b,_=self.request('/api/admin/webhook-status');self.assertEqual(c,401)
        login=json.dumps({'username':'stayowner','password':'long-demo-strong-pass-EXAMPLE'}).encode()
        c,b,h=self.request('/api/admin/login',method='POST',body=login,headers={'Content-Type':'application/json'})
        self.assertEqual(c,200)
        cookie=h['Set-Cookie'].split(';')[0]
        c,b,_=self.request('/api/admin/webhook-status',headers={'Cookie':cookie})
        self.assertEqual(c,200,b)
        info=json.loads(b)
        self.assertFalse(info['checkout_enabled'])
        self.assertFalse(info['orders_approved_from_webhooks'])
        self.assertNotIn('payment_id',str(info))
        self.assertIn('events_received',info)
        self.assertNotIn('STAYVISION-HMAC-TEST-NOT-REAL',str(info))

if __name__=='__main__': unittest.main(verbosity=2)
