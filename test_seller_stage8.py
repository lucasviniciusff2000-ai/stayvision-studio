"""Offline Etapa 8 tests. No outgoing Mercado Pago or Mercado Libre network requests."""
import json
import os
import urllib.error
import unittest
from unittest.mock import patch

import seller_identity
import checkout_production as checkout
from test_checkout_stage6 import CheckoutHttp, OID
from test_online import mod


class FakeHTTP:
    def __init__(self, payload): self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,n=-1): return json.dumps(self.payload).encode()


class IdentityUnit(unittest.TestCase):
    def test_matched_response_only_GET_without_secret_exposure(self):
        seen=[]
        def fake(req, timeout):
            seen.append(req)
            return FakeHTTP({'id':123456789,'nickname':'PRIVATE_PROFILE','email':'private@example.test'})
        env={'MP_PRODUCTION_ACCESS_TOKEN':'TOKEN-SENSITIVE-STAGE8','MP_PRODUCTION_COLLECTOR_ID':'123456789'}
        with patch.dict(os.environ,env), patch.object(seller_identity.urllib.request,'urlopen',side_effect=fake):
            report=seller_identity.check_seller_identity()
            self.assertTrue(seller_identity.require_seller_identity())
        self.assertTrue(report['verified']);self.assertTrue(report['read_only'])
        self.assertEqual(report['configured_id_suffix'],'6789')
        self.assertFalse(report['payment_created']);self.assertFalse(report['preference_created'])
        self.assertEqual(len(seen),2)
        self.assertTrue(all(req.get_method()=='GET' for req in seen))
        self.assertTrue(all(req.full_url=='https://api.mercadolibre.com/users/me' for req in seen))
        self.assertTrue(all(req.get_header('Authorization')=='Bearer TOKEN-SENSITIVE-STAGE8' for req in seen))
        self.assertNotIn('TOKEN-SENSITIVE-STAGE8',json.dumps(report))
        self.assertNotIn('private@example.test',json.dumps(report))

    def test_mismatch_denied(self):
        with patch.dict(os.environ,{'MP_PRODUCTION_ACCESS_TOKEN':'fake','MP_PRODUCTION_COLLECTOR_ID':'111'}), \
             patch.object(seller_identity.urllib.request,'urlopen',return_value=FakeHTTP({'id':222})):
            report=seller_identity.check_seller_identity()
            self.assertFalse(report['verified'])
            self.assertEqual(report['status'],'vendedor_divergente')
            with self.assertRaises(seller_identity.SellerIdentityError):seller_identity.require_seller_identity()

    def test_missing_config_never_contacts_api(self):
        with patch.dict(os.environ,{'MP_PRODUCTION_ACCESS_TOKEN':'','MP_PRODUCTION_COLLECTOR_ID':''}), \
             patch.object(seller_identity.urllib.request,'urlopen') as call:
            with self.assertRaises(seller_identity.SellerIdentityError): seller_identity.check_seller_identity()
            call.assert_not_called()

    def test_http_or_malformed_fails_closed(self):
        with patch.dict(os.environ,{'MP_PRODUCTION_ACCESS_TOKEN':'fake','MP_PRODUCTION_COLLECTOR_ID':'123'}):
            with patch.object(seller_identity.urllib.request,'urlopen',side_effect=urllib.error.HTTPError('',403,'Forbidden',None,None)):
                with self.assertRaises(seller_identity.SellerIdentityError): seller_identity.check_seller_identity()
            for obj in ({'id':'not-number'},['123'],{}):
                with patch.object(seller_identity.urllib.request,'urlopen',return_value=FakeHTTP(obj)):
                    with self.assertRaises(seller_identity.SellerIdentityError): seller_identity.check_seller_identity()

    def test_direct_preference_requires_identity_even_when_gate_open(self):
        env={'STAYVISION_MP_CHECKOUT_MODE':'restricted','STAYVISION_MP_ALLOWED_ORDER_ID':OID,
             'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST',
             'MP_PRODUCTION_COLLECTOR_ID':'999','MP_WEBHOOK_SECRET':'fake-webhook',
             'MP_PRODUCTION_ACCESS_TOKEN':'fake-token','STAYVISION_PUBLIC_URL':'https://sample.up.railway.app'}
        order={'id':OID,'plan_code':'photo','price':49,'payment_status':'nao_iniciado'}
        with patch.dict(os.environ,env),patch.object(checkout,'require_seller_identity',side_effect=seller_identity.SellerIdentityError('divergente')), \
             patch.object(checkout.urllib.request,'urlopen') as network:
            with self.assertRaises(checkout.CheckoutError): checkout.create_preference(order,idempotency_key='a'*40)
            network.assert_not_called()


class IdentityHTTP(unittest.TestCase):
    setUpClass=classmethod(CheckoutHttp.setUpClass.__func__)
    tearDownClass=classmethod(CheckoutHttp.tearDownClass.__func__)
    setUp=CheckoutHttp.setUp
    auth=CheckoutHttp.auth
    req=CheckoutHttp.req

    def test_endpoint_private_and_readonly(self):
        code,_=self.req('/api/admin/seller-identity')
        self.assertEqual(code,401)
        admin={'Cookie':self.auth()}
        with patch.object(mod,'check_seller_identity',return_value={
                'verified':True,'status':'vendedor_confirmado',
                'read_only':True,'preference_created':False,'payment_created':False}) as fn:
            code,payload=self.req('/api/admin/seller-identity',headers=admin)
            self.assertEqual(code,200)
            self.assertTrue(payload['verified'])
            self.assertFalse(payload['payment_created'])
            fn.assert_called_once()
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mp_checkout_registry').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',(OID,)).fetchone()[0],'nao_iniciado')

    def test_wrong_seller_cannot_insert_pending_attempt(self):
        admin={'Cookie':self.auth(),'Content-Type':'application/json',
               'Origin':'https://sample.up.railway.app',
               'X-StayVision-Checkout-Intent':'single-real-test'}
        flags={'STAYVISION_MP_CHECKOUT_MODE':'restricted','STAYVISION_MP_ALLOWED_ORDER_ID':OID,
             'STAYVISION_MP_REAL_TEST_AUTHORIZATION':'EXPLICIT_SINGLE_ORDER_TEST'}
        with patch.dict(os.environ,flags),patch.object(mod,'require_seller_identity',side_effect=seller_identity.SellerIdentityError('ID incorreto')), \
             patch.object(mod,'create_preference') as create:
            code,result=self.req('/api/admin/checkout-create','POST',json.dumps({
                'id':OID,'confirmation':'AUTORIZO PIX REAL '+OID+' R$49'}).encode(),admin)
            self.assertEqual(code,409,result)
            self.assertIn('ID incorreto',result['error'])
            create.assert_not_called()
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mp_checkout_registry').fetchone()[0],0)

    def test_default_locked_even_with_matching_identity(self):
        admin={'Cookie':self.auth(),'Content-Type':'application/json',
               'Origin':'https://sample.up.railway.app',
               'X-StayVision-Checkout-Intent':'single-real-test'}
        with patch.dict(os.environ,{'STAYVISION_MP_CHECKOUT_MODE':'locked'}), \
             patch.object(mod,'require_seller_identity') as identity,patch.object(mod,'create_preference') as post:
            code,result=self.req('/api/admin/checkout-create','POST',json.dumps({
                'id':OID,'confirmation':'AUTORIZO PIX REAL '+OID+' R$49'}).encode(),admin)
            self.assertEqual(code,403,result)
            identity.assert_not_called();post.assert_not_called()
