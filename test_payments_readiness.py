"""Offline tests for Mercado Pago production READ-ONLY integration (zero external calls)."""
import hashlib
import hmac
import importlib.util
import json
import os
import time
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('payments_readiness',os.path.join(os.path.dirname(__file__),'payments_readiness.py'))
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class FakeResponse:
    def __init__(self, payload):self.payload=json.dumps(payload).encode()
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self,n=-1):return self.payload[:n]

class PaymentReadinessTests(unittest.TestCase):
    def test_no_token(self):
        with patch.dict(os.environ, {'MP_PRODUCTION_ACCESS_TOKEN':''}):
            with self.assertRaises(mod.ReadinessError):mod.pix_production_report()

    def test_pix_on_get_only_token_never_exposed(self):
        token='SECRET_THIS_MUST_NOT_APPEAR_IN_RESULTS'
        seen=[]
        def fake_call(req,timeout):
            seen.append((req.get_method(),req.full_url,req.get_header('Authorization')))
            return FakeResponse([{'id':'pix','name':'Pix','payment_type_id':'bank_transfer'}, {'id':'visa','name':'Visa'}])
        with patch.dict(os.environ, {'MP_PRODUCTION_ACCESS_TOKEN':token}),patch.object(mod.urllib.request,'urlopen',side_effect=fake_call):
            report=mod.pix_production_report()
            self.assertEqual(seen, [('GET','https://api.mercadopago.com/v1/payment_methods','Bearer '+token)])
            self.assertTrue(report['pix_listed'])
            self.assertFalse(report['checkout_enabled'])
            self.assertFalse(report['charges_created'])
            self.assertNotIn(token,json.dumps(report))

    def test_pix_missing_and_unexpected_payload(self):
        with patch.dict(os.environ, {'MP_PRODUCTION_ACCESS_TOKEN':'SECRET'}),patch.object(mod.urllib.request,'urlopen',return_value=FakeResponse([{'id':'visa'}])):
            self.assertFalse(mod.pix_production_report()['pix_listed'])
        with patch.dict(os.environ, {'MP_PRODUCTION_ACCESS_TOKEN':'SECRET'}),patch.object(mod.urllib.request,'urlopen',return_value=FakeResponse({'oops':'object'})):
            with self.assertRaises(mod.ReadinessError):mod.pix_production_report()

    def test_webhook_signature_validation_only(self):
        now=time.time();ts=str(int(now*1000));req_id='abc-def';pid='12345678';secret='SHARED_TEST_SECRET'
        template=f'id:{pid};request-id:{req_id};ts:{ts};'
        signature=hmac.new(secret.encode(),template.encode(),hashlib.sha256).hexdigest()
        header='ts='+ts+',v1='+signature
        self.assertTrue(mod.valid_webhook_signature(secret,header,req_id,pid,now_timestamp=now))
        self.assertFalse(mod.valid_webhook_signature(secret,header,req_id,'12345679',now_timestamp=now))
        self.assertFalse(mod.valid_webhook_signature(secret,header,'tampered',pid,now_timestamp=now))
        self.assertFalse(mod.valid_webhook_signature(secret,header,req_id,pid,now_timestamp=now+600))
        self.assertFalse(mod.valid_webhook_signature(secret,'not valid',req_id,pid,now_timestamp=now))

    def test_never_approve_wrong_amount_currency_or_test_transaction(self):
        order={'id':'SV-12345','price':49}
        payment={'id':12345678,'status':'approved','live_mode':True,'currency_id':'BRL',
                 'external_reference':order['id'],'transaction_amount':49,'collector_id':987}
        self.assertEqual(mod.verified_payment_fields(payment,order,collector_id=987)['payment_status'],'pago')
        for changed in ({'transaction_amount':48},{'currency_id':'USD'},{'live_mode':False},
                        {'external_reference':'OTHER'},{'status':'pending'},{'collector_id':99}):
            other={**payment,**changed}
            self.assertIsNone(mod.verified_payment_fields(other,order,collector_id=987),other)

    def test_readiness_always_reports_checkout_disabled_even_if_env_flag_on(self):
        with patch.dict(os.environ, {'MP_PRODUCTION_ACCESS_TOKEN':'SECRET',
                                      'MP_WEBHOOK_SECRET':'SECRET',
                                      'STAYVISION_PUBLIC_URL':'https://example.up.railway.app',
                                      'STAYVISION_LIVE_PAYMENTS_ENABLED':'1'}):
            status=mod.config_report()
            self.assertTrue(status['production_token_configured'])
            self.assertTrue(status['webhook_secret_configured'])
            self.assertTrue(status['public_https_url_configured'])
            self.assertFalse(status['real_charges_possible'])
            self.assertFalse(status['checkout_enabled'])
            self.assertNotIn('SECRET',json.dumps(status))

if __name__=='__main__':unittest.main(verbosity=2)
