"""Stage 8.2 tests. All Mercado Pago requests mocked. No secrets or real charges."""
import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import seller_identity
from test_seller_stage8 import FakeHTTP
from test_checkout_stage6 import CheckoutHttp, OID
from test_online import mod


class FullIdIdentityTest(TestCase):
    def test_full_id_only_on_explicit_read_only_call(self):
        account_id='12345678501'
        with patch.dict(os.environ,{'MP_PRODUCTION_ACCESS_TOKEN':'PRIVATE_TOKEN',
                                      'MP_PRODUCTION_COLLECTOR_ID':'99992305'}), \
             patch.object(seller_identity.urllib.request,'urlopen',return_value=FakeHTTP({
                 'id':int(account_id),'email':'secret@example.test','nickname':'private'})) as network:
            masked=seller_identity.check_seller_identity()
            explicit=seller_identity.check_seller_identity(show_full_id=True)
        self.assertFalse(masked['verified'])
        self.assertNotIn('token_owner_id_full',masked)
        self.assertEqual(masked['token_owner_id_suffix'],'8501')
        self.assertEqual(explicit['token_owner_id_full'],account_id)
        self.assertFalse(explicit['verified'])
        self.assertNotIn('PRIVATE_TOKEN',json.dumps(explicit))
        self.assertNotIn('secret@example.test',json.dumps(explicit))
        self.assertFalse(explicit['preference_created'])
        self.assertFalse(explicit['payment_created'])
        self.assertEqual(network.call_count,2)
        self.assertTrue(all(call.args[0].get_method()=='GET' for call in network.call_args_list))

    def test_html_has_explicit_reveal_and_hide(self):
        static=Path(__file__).resolve().parent/'static'
        page=(static/'painel.html').read_text()
        js=(static/'painel.js').read_text()
        self.assertIn('seller-reveal-id-btn',page)
        self.assertIn('id="seller-full-id-area" hidden',page)
        self.assertIn('/api/admin/seller-identity-full',js)
        self.assertIn("$('#seller-full-id').value=''",js)
        self.assertIn("field.value=id;area.hidden=false",js)


class FullIdEndpointTest(CheckoutHttp):
    def test_auth_required_and_no_checkout_writes(self):
        unauth_code,unauth_body=self.req('/api/admin/seller-identity-full')
        self.assertEqual(unauth_code,401)
        self.assertNotIn('token_owner_id_full',unauth_body)
        headers={'Cookie':self.auth()}
        mod.ATTEMPTS.pop(('admin-seller-identity-full','127.0.0.1'),None)
        report={'verified':False,'status':'vendedor_divergente','configured_id_suffix':'2305',
                'token_owner_id_suffix':'8501','token_owner_id_full':'12345678501',
                'read_only':True,'preference_created':False,'payment_created':False,
                'checkout_enabled':False}
        with patch.object(mod,'check_seller_identity',return_value=report) as identity, \
             patch.object(mod,'create_preference') as create, \
             patch.object(mod,'fetch_payment') as payment:
            code,result=self.req('/api/admin/seller-identity-full',headers=headers)
            self.assertEqual(code,200,result)
            self.assertEqual(result['token_owner_id_full'],'12345678501')
            identity.assert_called_once_with(show_full_id=True)
            create.assert_not_called()
            payment.assert_not_called()
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mp_checkout_registry').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',(OID,)).fetchone()[0],'nao_iniciado')

    def test_rate_limit_limits_sensitive_id_reveal(self):
        headers={'Cookie':self.auth()}
        mod.ATTEMPTS.pop(('admin-seller-identity-full','127.0.0.1'),None)
        with patch.object(mod,'check_seller_identity',return_value={'token_owner_id_full':'1234'}) as checker:
            for _ in range(3):
                code,_=self.req('/api/admin/seller-identity-full',headers=headers)
                self.assertEqual(code,200)
            code,result=self.req('/api/admin/seller-identity-full',headers=headers)
            self.assertEqual(code,429,result)
            self.assertEqual(checker.call_count,3)
