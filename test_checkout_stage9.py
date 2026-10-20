"""Stage 9: public checkout feature tests OFFLINE. No real credentials or network calls."""
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch

import checkout_production as checkout
from test_checkout_stage6 import CheckoutHttp, OID, PREF, URL, GOOD
from test_online import mod

BASE_ENV={
 'STAYVISION_MP_CHECKOUT_MODE':'public',
 'STAYVISION_MP_PUBLIC_LAUNCH':'I_AUTHORIZE_PUBLIC_SALES',
 'STAYVISION_MP_AUTO_CONFIRM':'1',
 'STAYVISION_PUBLIC_URL':'https://sample.up.railway.app',
 'MP_PRODUCTION_ACCESS_TOKEN':'OFFLINE-ONLY',
 'MP_PRODUCTION_COLLECTOR_ID':'999',
 'MP_WEBHOOK_SECRET':'OFFLINE-SECRET',
}

class PublicCheckoutUnit(unittest.TestCase):
    def test_double_approval_and_autoconfirm_required(self):
        with patch.dict(os.environ,BASE_ENV):
            self.assertTrue(checkout.public_sales_ready())
            self.assertTrue(checkout.gate(OID))
            for key,value in [('STAYVISION_MP_CHECKOUT_MODE','locked'),
                              ('STAYVISION_MP_PUBLIC_LAUNCH',''),
                              ('STAYVISION_MP_AUTO_CONFIRM','0'),
                              ('MP_WEBHOOK_SECRET',''),
                              ('STAYVISION_PUBLIC_URL','http://example.com')]:
                with self.subTest(key=key),patch.dict(os.environ,{key:value}):
                    self.assertFalse(checkout.public_sales_ready())
                    self.assertFalse(checkout.gate(OID))

    def test_all_three_products_and_no_buyer_details(self):
        with patch.dict(os.environ,BASE_ENV):
            for plan,amount in [('photo',49),('video',197),('partner',697)]:
                with self.subTest(plan=plan):
                    body=checkout.build_preference({'id':OID,'plan_code':plan,'price':amount,
                            'payment_status':'nao_iniciado','name':'Buyer Secret',
                            'customer_token':'Hidden Tracking Token',
                            'email':'secret@example.test'},BASE_ENV['STAYVISION_PUBLIC_URL'])
                    self.assertEqual(body['items'][0]['unit_price'],float(amount))
                    self.assertEqual(body['external_reference'],OID)
                    self.assertEqual(body['items'][0]['id'],plan)
                    self.assertNotIn('secret@example.test',json.dumps(body))
                    self.assertNotIn('Hidden Tracking Token',json.dumps(body))
                    self.assertNotIn('subscription',json.dumps(body).lower())
            for bad in ({'price':0},{'price':-10},{'plan_code':'unknown'},
                        {'payment_status':'pago'}):
                with self.subTest(bad=bad),self.assertRaises(checkout.CheckoutError):
                    checkout.build_preference({'id':OID,'plan_code':'photo','price':49,
                                                'payment_status':'nao_iniciado',**bad},BASE_ENV['STAYVISION_PUBLIC_URL'])

    def test_restricted_keeps_photo_only_even_if_public_launch_value_present(self):
        with patch.dict(os.environ,{**BASE_ENV,'STAYVISION_MP_CHECKOUT_MODE':'restricted',
                         'STAYVISION_MP_ALLOWED_ORDER_ID':OID,
                         'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST'}):
            self.assertFalse(checkout.public_sales_ready())
            self.assertTrue(checkout.gate(OID))
            with self.assertRaises(checkout.CheckoutError):
                checkout.build_preference({'id':OID,'plan_code':'video','price':197,
                    'payment_status':'nao_iniciado'},BASE_ENV['STAYVISION_PUBLIC_URL'])

class PublicCheckoutHTTP(unittest.TestCase):
    setUpClass=classmethod(CheckoutHttp.setUpClass.__func__)
    tearDownClass=classmethod(CheckoutHttp.tearDownClass.__func__)
    setUp=CheckoutHttp.setUp
    req=CheckoutHttp.req
    auth=CheckoutHttp.auth

    def headers(self):
        return {'Origin':BASE_ENV['STAYVISION_PUBLIC_URL'],'Content-Type':'application/json'}

    def test_public_remains_closed_until_both_flags(self):
        with patch.dict(os.environ,{**BASE_ENV,'STAYVISION_MP_PUBLIC_LAUNCH':''}):
            code,config=self.req('/api/public/config')
            self.assertEqual(code,200)
            self.assertFalse(config['sales_enabled'])
            code,_=self.req('/api/client/checkout','POST',b'{}',self.headers())
            self.assertEqual(code,403)
        with patch.dict(os.environ,BASE_ENV):
            code,config=self.req('/api/public/config')
            self.assertTrue(config['sales_enabled'])
            self.assertEqual(config['payment_environment'],'producao')

    def test_checkout_token_origin_and_idempotency(self):
        mod.ATTEMPTS.pop(('client-checkout','127.0.0.1'),None)
        body=json.dumps({'token':'LONG_PRIVATE_TRACKING_TOKEN_ABC1234567890'}).encode()
        h=self.headers()
        with patch.dict(os.environ,BASE_ENV),patch.object(mod,'require_seller_identity',return_value=True), \
             patch.object(mod,'create_preference',return_value={'preference_id':PREF,'checkout_url':URL}) as create:
            code,_=self.req('/api/client/checkout','POST',body,{**h,'Origin':'https://hacker.invalid'})
            self.assertEqual(code,403)
            code,_=self.req('/api/client/checkout','POST',b'{"token":"WRONG"}',h)
            self.assertEqual(code,403)
            code,resp=self.req('/api/client/checkout','POST',body,h)
            self.assertEqual(code,200,resp)
            self.assertFalse(resp['reused'])
            self.assertEqual(resp['url'],URL)
            code,again=self.req('/api/client/checkout','POST',body,h)
            self.assertEqual(code,200,again)
            self.assertTrue(again['reused'])
            create.assert_called_once()
        with mod.connection() as db:
            row=db.execute('SELECT payment_status,preference_id FROM orders WHERE id=?',(OID,)).fetchone()
            self.assertEqual(row['payment_status'],'pendente')
            self.assertEqual(row['preference_id'],PREF)

    def test_chargeback_refund_disables_paid_access_if_fully_verified(self):
        with mod.connection() as db:
            db.execute('INSERT INTO mp_checkout_registry(order_id,preference_id,checkout_url,payment_id,idempotency_key,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                       (OID,PREF,URL,'123456789','e'*40,'ready','2026-10-19T00:00:00+00:00','2026-10-19T00:00:00+00:00'))
            db.execute("UPDATE orders SET preference_id=?,payment_status='pago' WHERE id=?",(PREF,OID))
        with patch.dict(os.environ,{**BASE_ENV,'STAYVISION_MP_CHECKOUT_MODE':'locked'}):
            self.assertFalse(mod.settle_payment_reversal({**GOOD,'status':'pending'}))
            self.assertFalse(mod.settle_payment_reversal({**GOOD,'status':'refunded','collector_id':123}))
            self.assertFalse(mod.settle_payment_reversal({**GOOD,'status':'refunded','preference_id':'wrong'}))
            self.assertFalse(mod.settle_payment_reversal({**GOOD,'status':'refunded','transaction_amount':48}))
            self.assertTrue(mod.settle_payment_reversal({**GOOD,'status':'refunded'}))
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',(OID,)).fetchone()[0],'estornado')

    def test_webhook_marks_paid_after_sales_pause_if_payment_fully_verified(self):
        with mod.connection() as db:
            db.execute('INSERT INTO mp_checkout_registry(order_id,preference_id,checkout_url,idempotency_key,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                       (OID,PREF,URL,'d'*40,'ready','2026-10-19T00:00:00+00:00','2026-10-19T00:00:00+00:00'))
            db.execute("UPDATE orders SET preference_id=?,payment_status='pendente' WHERE id=?",(PREF,OID))
        # Even if sales were paused after generating the checkout, the already-issued payment must be reconciled.
        pid='123456789'
        reqid='stage9-'+str(time.monotonic_ns())
        ts=str(int(time.time()*1000))
        sig=hmac.new(BASE_ENV['MP_WEBHOOK_SECRET'].encode(),f'id:{pid};request-id:{reqid};ts:{ts};'.encode(),hashlib.sha256).hexdigest()
        payload=json.dumps({'type':'payment','action':'payment.updated','data':{'id':pid}}).encode()
        h={'X-Request-Id':reqid,'X-Signature':f'ts={ts},v1={sig}','Content-Type':'application/json'}
        with patch.dict(os.environ,{**BASE_ENV,'STAYVISION_MP_CHECKOUT_MODE':'locked'}), \
             patch.object(mod,'fetch_payment',return_value=GOOD):
            code,resp=self.req('/api/mp/webhook?type=payment&data.id='+pid,'POST',payload,h)
            self.assertEqual(code,200,resp)
            self.assertTrue(resp['payment_updated'])
            code,dup=self.req('/api/mp/webhook?type=payment&data.id='+pid,'POST',payload,h)
            self.assertEqual(code,200,dup)
            self.assertTrue(dup['already_recorded'])
        with mod.connection() as db:
            row=db.execute('SELECT payment_status FROM orders WHERE id=?',(OID,)).fetchone()
            self.assertEqual(row['payment_status'],'pago')
            registered=db.execute('SELECT payment_id FROM mp_checkout_registry WHERE order_id=?',(OID,)).fetchone()
            self.assertEqual(registered['payment_id'],pid)

if __name__=='__main__': unittest.main()
