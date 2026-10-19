"""Offline security tests of stage 7 endpoints; never contact real Mercado Pago."""
import os
import json
import unittest
from unittest.mock import patch
from test_checkout_stage6 import CheckoutHttp, OID, PREF, GOOD
from test_online import mod

class Stage7Permission(unittest.TestCase):
    setUpClass=classmethod(CheckoutHttp.setUpClass.__func__)
    tearDownClass=classmethod(CheckoutHttp.tearDownClass.__func__)
    setUp=CheckoutHttp.setUp
    auth=CheckoutHttp.auth
    req=CheckoutHttp.req
    # Reuse server fixtures, but don't inherit tests: new suite reuses helper methods only.
    def test_wrong_origin_cannot_create(self):
        admin={'Cookie':self.auth(),'Content-Type':'application/json',
               'Origin':'https://attacker.test','X-StayVision-Checkout-Intent':'single-real-test'}
        flags={'STAYVISION_MP_CHECKOUT_MODE':'restricted','STAYVISION_MP_ALLOWED_ORDER_ID':OID,
               'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST'}
        with patch.dict(os.environ,flags),patch.object(mod,'create_preference') as create:
            code,_=self.req('/api/admin/checkout-create','POST',json.dumps({'id':OID,'confirmation':'AUTORIZO PIX REAL '+OID+' R$49'}).encode(),admin)
            self.assertEqual(code,403);create.assert_not_called()

    def test_missing_phrase_or_custom_header_cannot_create(self):
        admin={'Cookie':self.auth(),'Content-Type':'application/json','Origin':'https://sample.up.railway.app'}
        flags={'STAYVISION_MP_CHECKOUT_MODE':'restricted','STAYVISION_MP_ALLOWED_ORDER_ID':OID,
               'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST'}
        with patch.dict(os.environ,flags),patch.object(mod,'create_preference') as create:
            code,_=self.req('/api/admin/checkout-create','POST',json.dumps({'id':OID,'confirmation':'AUTORIZO PIX REAL '+OID+' R$49'}).encode(),admin)
            self.assertEqual(code,403)
            admin['X-StayVision-Checkout-Intent']='single-real-test'
            code,_=self.req('/api/admin/checkout-create','POST',json.dumps({'id':OID,'confirmation':'SIM'}).encode(),admin)
            self.assertEqual(code,403);create.assert_not_called()

    def test_unregistered_payment_cannot_be_inspected(self):
        admin={'Cookie':self.auth()}
        with patch.object(mod,'fetch_payment') as fn:
            status,result=self.req('/api/admin/checkout-observe?id='+OID+'&payment_id=123456789',headers=admin)
            self.assertEqual(status,409,result)
            fn.assert_not_called()

    def test_registered_payment_inspection_is_readonly(self):
        from test_checkout_stage6 import URL
        with mod.connection() as db:
            db.execute('INSERT INTO mp_checkout_registry(order_id,preference_id,checkout_url,idempotency_key,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                (OID,PREF,URL,'c'*40,'ready','2026-10-19T00:00:00+00:00','2026-10-19T00:00:00+00:00'))
            db.execute('UPDATE orders SET preference_id=?,payment_status=? WHERE id=?',(PREF,'pendente',OID))
        admin={'Cookie':self.auth()}
        with patch.object(mod,'fetch_payment',return_value=GOOD) as fn:
            status,result=self.req('/api/admin/checkout-observe?id='+OID+'&payment_id=123456789',headers=admin)
            self.assertEqual(status,200,result)
            self.assertEqual(result['result'],'aprovado_validado_sem_baixa')
            self.assertFalse(result['updated'])
            fn.assert_called_once_with('123456789')
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',(OID,)).fetchone()[0],'pendente')
        status,_=self.req('/api/admin/checkout-observe?id='+OID+'&payment_id=123456789')
        self.assertEqual(status,401)

# Avoid inheriting the 7 stage6 tests a second time when discovering stage7.
for name in list(Stage7Permission.__dict__):
    pass
