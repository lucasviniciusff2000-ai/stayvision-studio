import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('online',HERE/'server_online.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        mod.DATA=Path(cls.tmp.name);mod.UPLOADS=mod.DATA/'uploads';mod.DELIVERIES=mod.DATA/'entregas';mod.DB=mod.DATA/'data.sqlite'
        cls.env=patch.dict(os.environ,{
            'STAYVISION_ADMIN_USER':'stayowner',
            'STAYVISION_ADMIN_PASSWORD':'long-demo-strong-pass-EXAMPLE',
            'STAYVISION_PUBLIC_URL':'https://example.up.railway.app',
            'MP_TEST_ACCESS_TOKEN':'',
            'MP_PRODUCTION_ACCESS_TOKEN':'',
        })
        cls.env.start()
        mod.ensure_online_storage();mod.init_db();mod.initialize_admin()
        cls.web=ThreadingHTTPServer(('127.0.0.1',0),mod.Handler)
        cls.thread=threading.Thread(target=cls.web.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.web.server_address[1])
    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown();cls.web.server_close();cls.thread.join(5);cls.env.stop();cls.tmp.cleanup()
    def request(self,path,method='GET',body=None,headers=None):
        req=urllib.request.Request(self.base+path,method=method,data=body,headers=headers or {})
        try:
            with urllib.request.urlopen(req,timeout=4) as r: return r.status,r.read(),r.headers
        except urllib.error.HTTPError as e: return e.code,e.read(),e.headers
    def test_health_and_no_payments(self):
        code,body,_=self.request('/api/health');self.assertEqual(code,200)
        self.assertEqual(json.loads(body)['mode'],'pedidos_demo')
        self.assertFalse(json.loads(body)['payments'])
        code,body,_=self.request('/api/public/config');self.assertEqual(code,200)
        obj=json.loads(body);self.assertFalse(obj['sales_enabled']);self.assertFalse(obj['payment_enabled']);self.assertTrue(obj['demo_mode'])
        code,body,_=self.request('/api/client/checkout','POST',b'{}',{'Content-Type':'application/json'});self.assertEqual(code,403)
        code,body,_=self.request('/api/mp/webhook','POST',b'{}',{'Content-Type':'application/json'});self.assertEqual(code,403)
    def test_bootstrap_and_setup_locked(self):
        with mod.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)
        code,body,_=self.request('/api/admin/setup','POST',b'{}',{'Content-Type':'application/json'});self.assertEqual(code,403)
        self.assertNotIn(b'long-demo-strong-pass',body)
        code,body,_=self.request('/api/admin/overview');self.assertEqual(code,401)
    def test_login_cookie_and_financial_change_locked(self):
        data=json.dumps({'username':'stayowner','password':'long-demo-strong-pass-EXAMPLE'}).encode()
        code,body,headers=self.request('/api/admin/login','POST',data,{'Content-Type':'application/json'})
        self.assertEqual(code,200,body)
        self.assertIn('Secure',headers['Set-Cookie']);self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        cookie=headers['Set-Cookie'].split(';')[0]
        header={'Cookie':cookie,'Content-Type':'application/json'}
        code,body,_=self.request('/api/admin/overview',headers={'Cookie':cookie});self.assertEqual(code,200)
        code,body,_=self.request('/api/admin/settings','POST',b'{"payment_enabled":true}',header)
        self.assertEqual(code,403)
        code,body,_=self.request('/api/admin/verify-payment','POST',b'{}',header)
        self.assertEqual(code,403)
        code,body,_=self.request('/api/admin/settings','POST',b'{"brand_name":"StayVision Studio"}',header)
        self.assertEqual(code,200,body)
    def test_origin_and_order_toggle(self):
        code,body,_=self.request('/api/orders','POST',b'foo',{'Content-Type':'multipart/form-data; boundary=x'})
        self.assertEqual(code,403)
        code,body,_=self.request('/api/orders','POST',b'foo',{'Origin':'https://attacker.test','Content-Type':'multipart/form-data; boundary=x'})
        self.assertEqual(code,403)
    def test_demo_order_upload_and_file_protection(self):
        mod.DEMO_ORDERS=True
        try:
            fields={'plan':'photo','name':'Example User','email':'example@invalid.test','phone':'47999999999','property_type':'Casa','city':'Demo City','notes':'sample','consent':'yes'}
            boundary='BOUNDARY123'
            data=b''
            for key,val in fields.items():
                data+=f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'.encode()
            data+=f'--{boundary}\r\nContent-Disposition: form-data; name="images"; filename="demo.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()+b'\xff\xd8\xff\xe0demo-not-real-jpeg-content\r\n'
            data+=f'--{boundary}--\r\n'.encode()
            code,body,_=self.request('/api/orders','POST',data,{'Content-Type':f'multipart/form-data; boundary={boundary}'})
            self.assertEqual(code,201,body)
            order=json.loads(body)
            code,payload,_=self.request('/api/client/order?token='+order['token'])
            self.assertEqual(code,200,payload);self.assertEqual(json.loads(payload)['image_count'],1)
            code,payload,_=self.request('/api/client/delivery?token='+order['token'])
            self.assertEqual(code,404)
            code,payload,_=self.request('/api/admin/files/1');self.assertEqual(code,401)
        finally: mod.DEMO_ORDERS=False
    def test_paid_status_cannot_be_marked_manually(self):
        data=json.dumps({'username':'stayowner','password':'long-demo-strong-pass-EXAMPLE'}).encode()
        code,body,headers=self.request('/api/admin/login','POST',data,{'Content-Type':'application/json'})
        self.assertEqual(code,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        with mod.connection() as db:
            order=db.execute('SELECT id,status,payment_status FROM orders LIMIT 1').fetchone()
            self.assertIsNotNone(order)
        request={'id':order['id'],'status':order['status'],'payment_status':'pago','admin_note':'tentativa de teste'}
        code,body,_=self.request('/api/admin/update','POST',json.dumps(request).encode(),{'Content-Type':'application/json','Cookie':cookie})
        self.assertEqual(code,400,body)
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',(order['id'],)).fetchone()[0],'nao_iniciado')

    def test_railway_volume_guard(self):
        with patch.dict(os.environ, {'RAILWAY_ENVIRONMENT_NAME':'production','RAILWAY_VOLUME_MOUNT_PATH':'/not-correct'}):
            with self.assertRaises(RuntimeError): mod.ensure_online_storage()

if __name__=='__main__':unittest.main(verbosity=2)
