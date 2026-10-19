"""Offline integration tests. All Mercado Pago API calls are mocked."""
import hashlib, hmac, json, os, tempfile, threading, time, unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from test_online import mod
import urllib.request, urllib.error
import payment_reconciliation as rec

class PaymentsReviewTests(unittest.TestCase):
    def setUp(self):
        self.order={'id':'SV-261019-ABC123','price':49,'preference_id':'PREF_123'}
        self.payment={'id':123456789,'live_mode':True,'status':'approved',
                      'currency_id':'BRL','external_reference':self.order['id'],
                      'transaction_amount':49,'collector_id':999,'preference_id':'PREF_123'}

    def test_valid_read_only(self):
        self.assertEqual(rec.review_payment(self.payment,self.order,collector_id='999'),
                         'aprovado_validado_sem_baixa')

    def test_all_rejections(self):
        examples={
            'live_mode':(False,'transacao_nao_produtiva'),
            'status':('pending','pagamento_nao_aprovado'),
            'currency_id':('USD','moeda_divergente'),
            'external_reference':('SV-OUTRO','referencia_divergente'),
            'transaction_amount':(48,'valor_divergente'),
            'collector_id':(123,'vendedor_divergente'),
            'preference_id':('PREF_WRONG','preferencia_nao_comprovada'),
        }
        for k,(v,outcome) in examples.items():
            with self.subTest(k=k):
                self.assertEqual(rec.review_payment({**self.payment,k:v},self.order,collector_id='999'),outcome)
        self.assertEqual(rec.review_payment(self.payment,None,collector_id='999'),'pedido_nao_localizado')
        self.assertEqual(rec.review_payment(self.payment,self.order,collector_id=''),'id_vendedor_nao_configurado')
        self.assertEqual(rec.review_payment(self.payment,{**self.order,'preference_id':''},collector_id='999'),
                         'pedido_sem_preferencia_propria')
        self.assertEqual(rec.review_payment(None,self.order,collector_id='999'),'pagamento_nao_encontrado')
        self.assertEqual(rec.review_payment({**self.payment,'transaction_amount':'NaN'},self.order,collector_id='999'),'valor_divergente')

    def test_get_only_and_no_token_leak(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,n=-1): return json.dumps(self_payment).encode()
        self_payment=self.payment
        seen=[]
        def fake(req,timeout):
            seen.append((req.get_method(),req.full_url,req.get_header('Authorization')))
            return Response()
        with patch.dict(os.environ,{'MP_PRODUCTION_ACCESS_TOKEN':'PRODUCTION_PRIVATE_TEST'}),\
             patch.object(rec.urllib.request,'urlopen',side_effect=fake):
            response=rec.fetch_payment('123456789')
        self.assertEqual(response['id'],123456789)
        self.assertEqual(seen,[('GET','https://api.mercadopago.com/v1/payments/123456789','Bearer PRODUCTION_PRIVATE_TEST')])
        with self.assertRaises(ValueError):rec.fetch_payment('../preferences')

class ReconciliationHTTPTests(unittest.TestCase):
    def request(self,path,method='GET',body=None,headers=None):
        req=urllib.request.Request(self.base+path,method=method,data=body,headers=headers or {})
        try:
            with urllib.request.urlopen(req,timeout=4) as r: return r.status,r.read(),r.headers
        except urllib.error.HTTPError as e: return e.code,e.read(),e.headers
    @classmethod
    def setUpClass(cls):
        mod.ATTEMPTS.clear()
        cls.tmp=tempfile.TemporaryDirectory()
        mod.DATA=Path(cls.tmp.name);mod.UPLOADS=mod.DATA/'uploads';mod.DELIVERIES=mod.DATA/'entregas';mod.DB=mod.DATA/'data.sqlite'
        cls.env=patch.dict(os.environ,{'STAYVISION_ADMIN_USER':'stayowner',
            'STAYVISION_ADMIN_PASSWORD':'long-demo-strong-pass-EXAMPLE',
            'STAYVISION_PUBLIC_URL':'https://example.up.railway.app',
            'MP_TEST_ACCESS_TOKEN':'', 'MP_PRODUCTION_ACCESS_TOKEN':'PRODUCTION_TEST_TOKEN',
            'MP_PRODUCTION_COLLECTOR_ID':'999'})
        cls.env.start();mod.ensure_online_storage();mod.init_db();mod.initialize_admin()
        with mod.connection() as db:
            db.execute('''INSERT INTO orders(id,customer_token,created_at,updated_at,plan_code,plan_name,
                price,name,email,phone,property_type,city,notes,status,payment_status,preference_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                'SV-261019-ABC123','PRIVATE_TRACK','2026-10-19T00:00:00+00:00','2026-10-19T00:00:00+00:00',
                'photo','StayVision Photo',49,'Demo','test@example.test','0000000000',
                'Casa','Cidade','demo','recebido','nao_iniciado','PREF_123'))
        cls.web=ThreadingHTTPServer(('127.0.0.1',0),mod.Handler)
        cls.thread=threading.Thread(target=cls.web.serve_forever,daemon=True)
        cls.thread.start();cls.base='http://127.0.0.1:'+str(cls.web.server_address[1])
    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown();cls.web.server_close();cls.thread.join(5)
        cls.env.stop();cls.tmp.cleanup()

    def webhook(self, req_id, payment_id='123456789'):
        secret='EXAMPLE_SECRET_HMAC';ts=str(int(time.time()*1000))
        manifest=f'id:{payment_id};request-id:{req_id};ts:{ts};'
        digest=hmac.new(secret.encode(),manifest.encode(),hashlib.sha256).hexdigest()
        headers={'Content-Type':'application/json','X-Request-Id':req_id,'X-Signature':f'ts={ts},v1={digest}'}
        payload=json.dumps({'type':'payment','action':'payment.updated','data':{'id':payment_id}}).encode()
        with patch.dict(os.environ,{'MP_WEBHOOK_SECRET':secret}):
            return self.request('/api/mp/webhook?type=payment&data.id='+payment_id,'POST',payload,headers)

    def test_verified_lookup_does_not_mark_paid_and_is_idempotent(self):
        payment={'id':123456789,'live_mode':True,'status':'approved','currency_id':'BRL',
                 'external_reference':'SV-261019-ABC123','transaction_amount':'49.00',
                 'collector_id':999,'preference_id':'PREF_123'}
        with patch.object(mod,'fetch_payment',return_value=payment) as fetch:
            c,b,_=self.webhook('stage5-ok-first');self.assertEqual(c,200,b)
            c,b,_=self.webhook('stage5-ok-first');self.assertEqual(c,200,b)
            fetch.assert_called_once_with('123456789')
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',('SV-261019-ABC123',)).fetchone()[0], 'nao_iniciado')
            self.assertEqual(db.execute('SELECT result FROM mp_webhook_audit WHERE request_id=?',('stage5-ok-first',)).fetchone()[0], 'aprovado_validado_sem_baixa')
        c,b,_=self.request('/api/admin/webhook-status');self.assertEqual(c,401)

    def test_wrong_amount_not_applied(self):
        payment={'id':123456789,'live_mode':True,'status':'approved','currency_id':'BRL',
                 'external_reference':'SV-261019-ABC123','transaction_amount':12,'collector_id':999}
        with patch.object(mod,'fetch_payment',return_value=payment):
            c,b,_=self.webhook('stage5-bad-amount');self.assertEqual(c,200,b)
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT result FROM mp_webhook_audit WHERE request_id=?',('stage5-bad-amount',)).fetchone()[0],'valor_divergente')
            self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',('SV-261019-ABC123',)).fetchone()[0],'nao_iniciado')

    def test_nonexistent_payment_and_temporary_failure(self):
        with patch.object(mod,'fetch_payment',return_value=None):
            c,b,_=self.webhook('stage5-not-found');self.assertEqual(c,200,b)
        with patch.object(mod,'fetch_payment',side_effect=rec.PaymentLookupUnavailable('private detail')):
            c,b,_=self.webhook('stage5-temporary');self.assertEqual(c,503,b)
            self.assertNotIn(b'private detail',b)
        with mod.connection() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM mp_webhook_audit WHERE request_id=?',('stage5-temporary',)).fetchone())
            self.assertEqual(db.execute('SELECT result FROM mp_webhook_audit WHERE request_id=?',('stage5-not-found',)).fetchone()[0],'pagamento_nao_encontrado')

if __name__=='__main__':unittest.main(verbosity=2)
