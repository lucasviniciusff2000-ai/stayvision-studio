"""Fully offline Stage 6 tests: no Mercado Pago API calls or real charges."""
import json
import hashlib
import hmac
import time
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import checkout_production as checkout
from test_online import mod

OID='SV-261019-ABC123'
PREF='TEST-PREFERENCE-001'
URL='https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=test-pref'
GOOD={'id':123456789,'live_mode':True,'status':'approved','currency_id':'BRL',
      'external_reference':OID,'transaction_amount':49,'collector_id':999,'preference_id':PREF}

class CheckoutFunctions(unittest.TestCase):
    def order(self):
        return {'id':OID,'plan_code':'photo','price':49,'payment_status':'nao_iniciado'}
    def test_default_locked_and_no_live_calls(self):
        with patch.dict(os.environ,{'STAYVISION_MP_CHECKOUT_MODE':'locked','STAYVISION_MP_ALLOWED_ORDER_ID':OID,
                'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST',
                'MP_PRODUCTION_COLLECTOR_ID':'999','MP_WEBHOOK_SECRET':'fake-not-secret',
                'MP_PRODUCTION_ACCESS_TOKEN':'DUMMY','STAYVISION_PUBLIC_URL':'https://sample.up.railway.app'}):
            self.assertFalse(checkout.gate(OID))
            with patch.object(checkout.urllib.request,'urlopen') as mocked:
                with self.assertRaises(checkout.CheckoutError): checkout.create_preference(self.order(),idempotency_key='a'*40)
                mocked.assert_not_called()
    def test_whitelist_and_authorization_both_required(self):
        base={'STAYVISION_MP_CHECKOUT_MODE':'restricted','STAYVISION_MP_ALLOWED_ORDER_ID':OID,
             'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST',
             'MP_PRODUCTION_COLLECTOR_ID':'999','MP_WEBHOOK_SECRET':'fake-not-secret',
             'MP_PRODUCTION_ACCESS_TOKEN':'DUMMY','STAYVISION_PUBLIC_URL':'https://sample.up.railway.app'}
        with patch.dict(os.environ,base):
            self.assertTrue(checkout.gate(OID))
            self.assertFalse(checkout.gate('SV-261019-OTHER'))
            with patch.dict(os.environ,{'STAYVISION_MP_REAL_TEST_AUTHORIZATION':''}): self.assertFalse(checkout.gate(OID))
            with patch.dict(os.environ,{'STAYVISION_PUBLIC_URL':'http://localhost:8080'}): self.assertFalse(checkout.gate(OID))
            with patch.dict(os.environ,{'MP_PRODUCTION_COLLECTOR_ID':'INVALID'}): self.assertFalse(checkout.gate(OID))
    def test_payload_no_personal_data_and_correct_price(self):
        full={**self.order(),'name':'private person','email':'person@example.test','customer_token':'private-token'}
        payload=checkout.build_preference(full,'https://sample.up.railway.app')
        self.assertEqual(payload['external_reference'],OID)
        self.assertEqual(payload['items'][0]['unit_price'],49.0)
        self.assertEqual(payload['back_urls']['success'],'https://sample.up.railway.app/retorno?status=success')
        self.assertNotIn('private-token',json.dumps(payload))
        self.assertNotIn('person@example.test',json.dumps(payload))
        for changes in ({'price':50},{'plan_code':'video'},{'payment_status':'pago'}):
            with self.assertRaises(checkout.CheckoutError): checkout.build_preference({**full,**changes},'https://sample.up.railway.app')
    def test_preference_post_mocked_to_mp_only(self):
        class MockResponse:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,n=-1): return json.dumps({'id':PREF,'init_point':URL}).encode()
        seen=[]
        def fake_urlopen(req,timeout):
            seen.append(req)
            return MockResponse()
        env={'STAYVISION_MP_CHECKOUT_MODE':'restricted','STAYVISION_MP_ALLOWED_ORDER_ID':OID,
             'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST',
             'MP_PRODUCTION_COLLECTOR_ID':'999','MP_WEBHOOK_SECRET':'fake-secret',
             'MP_PRODUCTION_ACCESS_TOKEN':'DUMMY-TOKEN','STAYVISION_PUBLIC_URL':'https://sample.up.railway.app'}
        with patch.dict(os.environ,env),patch('checkout_production.require_seller_identity',return_value=True),patch.object(checkout.urllib.request,'urlopen',side_effect=fake_urlopen):
            output=checkout.create_preference(self.order(),idempotency_key='a'*40)
        self.assertEqual(output['preference_id'],PREF)
        self.assertEqual(len(seen),1)
        self.assertEqual(seen[0].get_method(),'POST')
        self.assertEqual(seen[0].full_url,'https://api.mercadopago.com/checkout/preferences')
        self.assertNotIn(b'DUMMY-TOKEN',seen[0].data)
        payload=json.loads(seen[0].data)
        self.assertEqual(payload['items'][0]['unit_price'],49)
        self.assertNotIn('payer',payload)

    def test_checkout_url_allowlist(self):
        self.assertTrue(checkout.trusted_checkout_url(URL))
        self.assertFalse(checkout.trusted_checkout_url('https://mercadopago.com.br.attacker.test/pay'))
        self.assertFalse(checkout.trusted_checkout_url('https://sandbox.mercadopago.com.br/check'))
        self.assertFalse(checkout.trusted_checkout_url('javascript:alert(1)'))

class CheckoutHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mod.ATTEMPTS.clear()
        cls.temp=tempfile.TemporaryDirectory()
        mod.DATA=Path(cls.temp.name);mod.UPLOADS=mod.DATA/'uploads';mod.DELIVERIES=mod.DATA/'entregas';mod.DB=mod.DATA/'stayvision.sqlite'
        cls.env=patch.dict(os.environ,{
            'STAYVISION_ADMIN_USER':'owner','STAYVISION_ADMIN_PASSWORD':'demo-password-strong-123',
            'STAYVISION_PUBLIC_URL':'https://sample.up.railway.app',
            'MP_PRODUCTION_ACCESS_TOKEN':'TEST-TOKEN-NOT-REAL',
            'MP_PRODUCTION_COLLECTOR_ID':'999','MP_WEBHOOK_SECRET':'DUMMY-WEBHOOK-SECRET',
            'STAYVISION_MP_CHECKOUT_MODE':'locked','STAYVISION_MP_ALLOWED_ORDER_ID':'',
            'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'','STAYVISION_MP_AUTO_CONFIRM':'0',
        })
        cls.env.start();mod.ensure_online_storage();mod.init_db();mod.initialize_admin()
        with mod.connection() as db:
            db.execute('''INSERT INTO orders(id,customer_token,created_at,updated_at,plan_code,plan_name,
                 price,name,email,phone,property_type,city,notes,status,payment_status)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (OID,'LONG_PRIVATE_TRACKING_TOKEN_ABC1234567890','2026-10-19T00:00:00+00:00','2026-10-19T00:00:00+00:00',
                 'photo','StayVision Photo',49,'Test Person','test@example.test','0000000000',
                 'Casa','Cidade','demo','recebido','nao_iniciado'))
        cls.web=ThreadingHTTPServer(('127.0.0.1',0),mod.Handler)
        cls.thread=threading.Thread(target=cls.web.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.web.server_address[1])
    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown();cls.web.server_close();cls.thread.join(5);cls.env.stop();cls.temp.cleanup()
    def setUp(self):
        mod.ATTEMPTS.pop(('admin-checkout','127.0.0.1'),None)
        with mod.connection() as db:
            db.execute('DELETE FROM mp_checkout_registry')
            db.execute("UPDATE orders SET payment_status='nao_iniciado',preference_id='',payment_url='' WHERE id=?",(OID,))
    def req(self,path,method='GET',body=None,headers=None):
        request=urllib.request.Request(self.url+path,data=body,method=method,headers=headers or {})
        try:
            with urllib.request.urlopen(request,timeout=5) as response: return response.status,json.loads(response.read())
        except urllib.error.HTTPError as err:
            return err.code,json.loads(err.read())
    def auth(self):
        reqbody=json.dumps({'username':'owner','password':'demo-password-strong-123'}).encode()
        request=urllib.request.Request(self.url+'/api/admin/login',data=reqbody,method='POST',headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as resp:
            return resp.headers['Set-Cookie'].split(';')[0]
    def test_preview_read_only_admin_required(self):
        code,_=self.req('/api/admin/checkout-preview?id='+OID);self.assertEqual(code,401)
        headers={'Cookie':self.auth()}
        with patch.object(mod,'create_preference') as call:
            code,obj=self.req('/api/admin/checkout-preview?id='+OID,headers=headers)
            self.assertEqual(code,200,obj)
            self.assertTrue(obj['dry_run']);self.assertFalse(obj['charge_created']);self.assertTrue(obj['checkout_locked'])
            call.assert_not_called()
        code,obj=self.req('/api/admin/checkout-readiness',headers=headers)
        self.assertEqual(code,200);self.assertFalse(obj['checkout_real_enabled'])
        code,obj=self.req('/api/health');self.assertEqual(code,200);self.assertFalse(obj['payments'])
    def test_locked_issue_never_creates_charge(self):
        headers={'Cookie':self.auth(),'Content-Type':'application/json'}
        with patch.object(mod,'create_preference') as call:
            code,obj=self.req('/api/admin/checkout-create',method='POST',body=json.dumps({'id':OID}).encode(),headers=headers)
            self.assertEqual(code,403,obj);call.assert_not_called()
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mp_checkout_registry').fetchone()[0],0)
    def test_whitelist_dry_issuance_with_mock_and_idempotency(self):
        admin={'Cookie':self.auth(),'Content-Type':'application/json',
               'Origin':'https://sample.up.railway.app',
               'X-StayVision-Checkout-Intent':'single-real-test'}
        flags={'STAYVISION_MP_CHECKOUT_MODE':'restricted','STAYVISION_MP_ALLOWED_ORDER_ID':OID,
             'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST'}
        def fake_post(order,*,idempotency_key):
            self.assertEqual(order['id'],OID)
            self.assertEqual(len(idempotency_key),40)
            return {'preference_id':PREF,'checkout_url':URL}
        with patch.dict(os.environ,flags),patch.object(mod,'require_seller_identity',return_value=True),patch.object(mod,'create_preference',side_effect=fake_post) as post:
            code,obj=self.req('/api/admin/checkout-create','POST',json.dumps({'id':OID,'confirmation':'AUTORIZO PIX REAL '+OID+' R$49'}).encode(),admin)
            self.assertEqual(code,200,obj);self.assertTrue(obj['created'])
            code,obj=self.req('/api/admin/checkout-create','POST',json.dumps({'id':OID,'confirmation':'AUTORIZO PIX REAL '+OID+' R$49'}).encode(),admin)
            self.assertEqual(code,200,obj);self.assertFalse(obj['created']);post.assert_called_once()
        with mod.connection() as db:
            row=db.execute('SELECT * FROM orders WHERE id=?',(OID,)).fetchone()
            self.assertEqual(row['preference_id'],PREF);self.assertEqual(row['payment_status'],'pendente')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mp_checkout_registry').fetchone()[0],1)
        code,obj=self.req('/api/client/order?token=LONG_PRIVATE_TRACKING_TOKEN_ABC1234567890')
        self.assertEqual(code,200)
        self.assertFalse(obj['checkout_available'])
        self.assertEqual(obj['order']['payment_url'],'')
    def test_failed_creation_never_retries_unconfirmed_network_call(self):
        admin={'Cookie':self.auth(),'Content-Type':'application/json',
               'Origin':'https://sample.up.railway.app',
               'X-StayVision-Checkout-Intent':'single-real-test'}
        flags={'STAYVISION_MP_CHECKOUT_MODE':'restricted','STAYVISION_MP_ALLOWED_ORDER_ID':OID,
               'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST'}
        with patch.dict(os.environ,flags),patch.object(mod,'require_seller_identity',return_value=True),patch.object(mod,'create_preference',side_effect=checkout.CheckoutError('Rede indisponível')) as post:
            code,obj=self.req('/api/admin/checkout-create','POST',json.dumps({'id':OID,'confirmation':'AUTORIZO PIX REAL '+OID+' R$49'}).encode(),admin)
            self.assertEqual(code,409,obj)
            code,obj=self.req('/api/admin/checkout-create','POST',json.dumps({'id':OID,'confirmation':'AUTORIZO PIX REAL '+OID+' R$49'}).encode(),admin)
            self.assertEqual(code,409,obj)
            post.assert_called_once()
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT stage FROM mp_checkout_registry WHERE order_id=?',(OID,)).fetchone()[0],'creating')

    def test_signed_webhook_does_not_settle_without_explicit_flags(self):
        with mod.connection() as db:
            db.execute('INSERT INTO mp_checkout_registry(order_id,preference_id,checkout_url,idempotency_key,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                (OID,PREF,URL,'a'*40,'ready','2026-10-19T00:00:00+00:00','2026-10-19T00:00:00+00:00'))
            db.execute("UPDATE orders SET preference_id=?,payment_status='pendente' WHERE id=?",(PREF,OID))
        pid='123456789'
        request_id='stage6-hook-signature-'+str(time.monotonic_ns())
        stamp=str(int(time.time()*1000))
        secret='SAMPLE-WEBHOOK-SECRET'
        manifest=f'id:{pid};request-id:{request_id};ts:{stamp};'
        digest=hmac.new(secret.encode(),manifest.encode(),hashlib.sha256).hexdigest()
        payload=json.dumps({'type':'payment','action':'payment.updated','data':{'id':pid}}).encode()
        headers={'Content-Type':'application/json','X-Request-Id':request_id,
                 'X-Signature':f'ts={stamp},v1={digest}'}
        with patch.dict(os.environ,{'MP_WEBHOOK_SECRET':secret,'STAYVISION_MP_AUTO_CONFIRM':'0'}),            patch.object(mod,'fetch_payment',return_value=GOOD):
            code,obj=self.req('/api/mp/webhook?type=payment&data.id='+pid,'POST',payload,headers)
            self.assertEqual(code,200,obj)
            self.assertFalse(obj['payment_updated'])
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',(OID,)).fetchone()[0],'pendente')
        self.assertFalse(mod.settle_payment_approved(GOOD))

    def test_settlement_validations_and_duplicate(self):
        with mod.connection() as db:
            db.execute('INSERT INTO mp_checkout_registry(order_id,preference_id,checkout_url,idempotency_key,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                (OID,PREF,URL,'b'*40,'ready','2026-10-19T00:00:00+00:00','2026-10-19T00:00:00+00:00'))
            db.execute("UPDATE orders SET preference_id=?,payment_status='pendente' WHERE id=?",(PREF,OID))
        valid={**GOOD}
        with patch.dict(os.environ,{'STAYVISION_MP_CHECKOUT_MODE':'restricted',
             'STAYVISION_MP_ALLOWED_ORDER_ID':OID,
             'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST',
             'STAYVISION_MP_AUTO_CONFIRM':'0'}):
            self.assertFalse(mod.settle_payment_approved(valid))
        with patch.dict(os.environ,{'STAYVISION_MP_CHECKOUT_MODE':'restricted',
             'STAYVISION_MP_ALLOWED_ORDER_ID':OID,
             'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST',
             'STAYVISION_MP_AUTO_CONFIRM':'1'}):
            for k,val in [('transaction_amount',48),('currency_id','USD'),('collector_id',987),
                          ('preference_id','SPOOF'),('external_reference','SV-OTHER'),('status','pending'),('live_mode',False)]:
                with self.subTest(k=k):self.assertFalse(mod.settle_payment_approved({**valid,k:val}))
            with mod.connection() as db:
                self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',(OID,)).fetchone()[0],'pendente')
            self.assertTrue(mod.settle_payment_approved(valid))
            self.assertTrue(mod.settle_payment_approved(valid))
            self.assertFalse(mod.settle_payment_approved({**valid,'id':111222333}))
            with mod.connection() as db:
                self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',(OID,)).fetchone()[0],'pago')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM mp_checkout_registry WHERE payment_id=?',('123456789',)).fetchone()[0],1)
        code,obj=self.req('/api/health');self.assertFalse(obj['payments'])

if __name__=='__main__':unittest.main()
