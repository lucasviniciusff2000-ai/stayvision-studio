"""Stage 10: authenticated reconciliation of already-paid Pix; offline and no charges."""
import json
import os
import unittest
from unittest.mock import patch

from test_checkout_stage6 import CheckoutHttp, OID, PREF, GOOD, URL
from test_online import mod

ENV={
    'STAYVISION_PUBLIC_URL':'https://sample.up.railway.app',
    'MP_PRODUCTION_COLLECTOR_ID':'999',
    'MP_PRODUCTION_ACCESS_TOKEN':'OFFLINE-NOT-A-REAL-KEY',
    'STAYVISION_MP_AUTO_CONFIRM':'1',
    'STAYVISION_MP_CHECKOUT_MODE':'locked',
    'STAYVISION_MP_PUBLIC_LAUNCH':'',
}

class ReconcileExistingPayment(unittest.TestCase):
    setUpClass=classmethod(CheckoutHttp.setUpClass.__func__)
    tearDownClass=classmethod(CheckoutHttp.tearDownClass.__func__)
    def setUp(self):
        CheckoutHttp.setUp(self)
        mod.ATTEMPTS.pop(('login','127.0.0.1'),None)
        mod.ATTEMPTS.pop(('admin-manual-reconciliation','127.0.0.1'),None)
        self.admin_cookie=self.auth()
    req=CheckoutHttp.req
    auth=CheckoutHttp.auth

    def install_registry(self):
        with mod.connection() as db:
            db.execute('''INSERT INTO mp_checkout_registry
              (order_id,preference_id,checkout_url,idempotency_key,stage,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?)''',
              (OID,PREF,URL,'s'*40,'ready','2026-10-19T00:00:00+00:00','2026-10-19T00:00:00+00:00'))
            db.execute('UPDATE orders SET preference_id=?,payment_status=? WHERE id=?',(PREF,'pendente',OID))

    def call_reconcile(self,body=None,headers=None):
        h={'Content-Type':'application/json','Origin':ENV['STAYVISION_PUBLIC_URL'],'Cookie':self.admin_cookie}
        h.update(headers or {})
        payload=body if body is not None else {'id':OID,'payment_id':'123456789'}
        return self.req('/api/admin/verify-payment','POST',json.dumps(payload).encode(),h)

    def status(self):
        with mod.connection() as db:
            rec=db.execute('SELECT payment_status FROM orders WHERE id=?',(OID,)).fetchone()
            registry=db.execute('SELECT payment_id FROM mp_checkout_registry WHERE order_id=?',(OID,)).fetchone()
            return rec['payment_status'],registry['payment_id'] if registry else None

    def test_must_authenticate_and_match_origin(self):
        self.install_registry()
        with patch.dict(os.environ,ENV),patch.object(mod,'fetch_payment') as fetch:
            code,_=self.req('/api/admin/verify-payment','POST',json.dumps({'id':OID,'payment_id':'123456789'}).encode(),
                            {'Content-Type':'application/json','Origin':ENV['STAYVISION_PUBLIC_URL']})
            self.assertEqual(code,401)
            code,_=self.call_reconcile(headers={'Origin':'https://malicious.example'})
            self.assertEqual(code,403)
            self.assertEqual(self.status(),('pendente',None))
            fetch.assert_not_called()

    def test_registration_required_and_auto_confirm_required(self):
        with patch.dict(os.environ,ENV),patch.object(mod,'fetch_payment') as fetch:
            code,_=self.call_reconcile()
            self.assertEqual(code,409)
            fetch.assert_not_called()
            self.install_registry()
            with patch.dict(os.environ,{'STAYVISION_MP_AUTO_CONFIRM':'0'}):
                code,resp=self.call_reconcile()
                self.assertEqual(code,409,resp)
                self.assertIn('STAYVISION_MP_AUTO_CONFIRM',resp['error'])
            fetch.assert_not_called()
            self.assertEqual(self.status(),('pendente',None))

    def test_rejects_payment_from_wrong_order_amount_seller_or_environment(self):
        self.install_registry()
        wrongs=[
            {**GOOD,'external_reference':'SV-261019-OTHER'},
            {**GOOD,'transaction_amount':50},
            {**GOOD,'collector_id':888},
            {**GOOD,'live_mode':False},
            {**GOOD,'currency_id':'USD'},
            {**GOOD,'preference_id':'INVALID-PREFERENCE'},
            {**GOOD,'status':'pending'},
            None,
        ]
        with patch.dict(os.environ,ENV),patch.object(mod,'create_preference') as create:
            for result in wrongs:
                with self.subTest(payment=result):
                    with patch.object(mod,'fetch_payment',return_value=result):
                        code,resp=self.call_reconcile()
                    self.assertEqual(code,409,resp)
                    self.assertEqual(self.status(),('pendente',None))
            create.assert_not_called()

    def test_approved_pix_is_linked_only_once_without_charges(self):
        self.install_registry()
        with patch.dict(os.environ,ENV),patch.object(mod,'fetch_payment',return_value=GOOD) as fetch,\
             patch.object(mod,'create_preference') as create:
            code,res=self.call_reconcile()
            self.assertEqual(code,200,res)
            self.assertTrue(res['updated'])
            self.assertEqual(self.status(),('pago','123456789'))
            code,res=self.call_reconcile()
            self.assertEqual(code,200,res)
            self.assertFalse(res['updated'] is None)
            self.assertEqual(self.status(),('pago','123456789'))
            code,_=self.call_reconcile(body={'id':OID,'payment_id':'987654321'})
            self.assertEqual(code,409)
            self.assertEqual(self.status(),('pago','123456789'))
            create.assert_not_called()
            self.assertEqual(fetch.call_count,2)

    def test_read_only_observe_does_not_modify_even_if_approved(self):
        self.install_registry()
        with patch.dict(os.environ,ENV),patch.object(mod,'fetch_payment',return_value=GOOD):
            code,res=self.req('/api/admin/checkout-observe?id='+OID+'&payment_id=123456789',headers={'Cookie':self.admin_cookie})
            self.assertEqual(code,200,res)
            self.assertFalse(res['updated'])
            self.assertEqual(self.status(),('pendente',None))

if __name__=='__main__': unittest.main()
