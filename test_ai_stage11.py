"""Stage 11: safe admin-only media production and real Pillow/FFmpeg output."""
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch
from PIL import Image

import server_online as mod
from ai_engine import enhance_image, run_pipeline, AIEngineError

class ImageEngineTests(unittest.TestCase):
    def test_enhance_preserves_shapes_without_hallucinating(self):
        with tempfile.TemporaryDirectory() as root:
            a,b=Path(root)/'a.jpg',Path(root)/'b.jpg'
            Image.new('RGB',(700,420),(80,95,99)).save(a)
            result=enhance_image(a,b,'natural')
            self.assertTrue(b.is_file())
            self.assertEqual(result['size'],[700,420])
            with Image.open(b) as im:
                self.assertEqual(im.size,(700,420))
            with self.assertRaises(AIEngineError):enhance_image(a,b,'unknown')
    def test_invalid_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            a,b=Path(root)/'a.jpg',Path(root)/'b.jpg'
            a.write_bytes(b'not-an-image')
            with self.assertRaises(AIEngineError):enhance_image(a,b)
    def test_photo_zip_manifest_and_input_limit(self):
        with tempfile.TemporaryDirectory() as root:
            src=Path(root)/'photo.png';Image.new('RGB',(720,440),(180,190,160)).save(src)
            result=run_pipeline([src],Path(root)/'out',mode='photo')
            self.assertTrue((Path(root)/'out'/'Fotos_StayVision.zip').is_file())
            with zipfile.ZipFile(Path(root)/'out'/'Fotos_StayVision.zip') as z:
                self.assertEqual(len(z.namelist()),1)
            self.assertEqual(result['tour_3d'] if 'tour_3d' in result else result['tour_3d'], 'não disponível; módulo de reconstrução real reservado para futura integração')
            with self.assertRaises(AIEngineError):run_pipeline([src]*13,Path(root)/'out2')

class AIHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.previous=(mod.DATA,mod.UPLOADS,mod.DELIVERIES,mod.DB)
        mod.DATA=Path(cls.tmp.name);mod.UPLOADS=mod.DATA/'uploads';mod.DELIVERIES=mod.DATA/'entregas';mod.DB=mod.DATA/'db.sqlite'
        cls.env=patch.dict(os.environ,{'STAYVISION_ADMIN_USER':'adminunit','STAYVISION_ADMIN_PASSWORD':'very-long-sample-password!',
                                       'STAYVISION_MP_CHECKOUT_MODE':'locked', 'STAYVISION_PUBLIC_URL':'https://localhost.invalid',
                                       'RAILWAY_ENVIRONMENT_NAME':'','RAILWAY_PROJECT_ID':''})
        cls.env.start();mod.ensure_online_storage();mod.init_db();mod.initialize_admin()
        cls.oid='SV-261019-AITEST'
        with mod.connection() as db:
            db.execute('''INSERT INTO orders(id,customer_token,created_at,updated_at,plan_code,plan_name,price,
                name,email,phone,property_type,city,notes,status,payment_status,admin_note)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cls.oid,'token-unit-photo-123456789',mod.now(),mod.now(),'photo','Photo',49,
                 'Tester','test@invalid.com','47999999999','Casa','Test','', 'recebido','pendente',''))
            file=mod.UPLOADS/cls.oid;file.mkdir(parents=True)
            filename='01-local-test.jpg'
            Image.new('RGB',(800,460),(145,150,144)).save(file/filename)
            db.execute('INSERT INTO order_files(order_id,name,stored_name,mime,size) VALUES(?,?,?,?,?)',
                       (cls.oid,'photo.jpg',filename,'image/jpeg',(file/filename).stat().st_size))
        cls.web=ThreadingHTTPServer(('127.0.0.1',0),mod.Handler)
        cls.thread=Thread(target=cls.web.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.web.server_address[1])
        cls.cookie=cls.login()

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown();cls.web.server_close();cls.thread.join(3)
        cls.env.stop();mod.DATA,mod.UPLOADS,mod.DELIVERIES,mod.DB=cls.previous;cls.tmp.cleanup()

    @classmethod
    def req(cls,path,method='GET',data=None,headers=None):
        request=urllib.request.Request(cls.base+path,method=method,data=data,headers=headers or {})
        try:
            with urllib.request.urlopen(request,timeout=12) as res: return res.status,res.read(),res.headers
        except urllib.error.HTTPError as err:
            return err.code,err.read(),err.headers

    @classmethod
    def login(cls):
        data=json.dumps({'username':'adminunit','password':'very-long-sample-password!'}).encode()
        status,resp,headers=cls.req('/api/admin/login','POST',data,{'Content-Type':'application/json'})
        assert status==200,(status,resp)
        return headers['Set-Cookie'].split(';')[0]

    def test_access_control_and_invalid_input(self):
        s,_,_=self.req('/api/admin/ai/status?id='+self.oid);self.assertEqual(s,401)
        s,_,_=self.req('/api/admin/ai/file?run='+'a'*24+'&name=manifest.json');self.assertEqual(s,401)
        params=json.dumps({'id':self.oid,'mode':'photo','style':'natural'}).encode()
        s,_,_=self.req('/api/admin/ai/start','POST',params,{'Content-Type':'application/json'});self.assertEqual(s,401)
        s,_,_=self.req('/api/admin/ai/start','POST',params,{'Content-Type':'application/json','Cookie':self.cookie,'Origin':'https://attacker.com'});self.assertEqual(s,403)
        params=json.dumps({'id':self.oid,'mode':'imaginary','style':'natural'}).encode()
        s,_,_=self.req('/api/admin/ai/start','POST',params,{'Content-Type':'application/json','Cookie':self.cookie});self.assertEqual(s,400)
        s,_,_=self.req('/api/admin/ai/file?run='+'a'*24+'&name=../../secrets');self.assertEqual(s,401)

    def test_async_photo_pipeline_download_and_payment_untouched(self):
        params=json.dumps({'id':self.oid,'mode':'photo','style':'claro'}).encode()
        code,data,_=self.req('/api/admin/ai/start','POST',params,{'Cookie':self.cookie,'Content-Type':'application/json'})
        self.assertEqual(code,202,data)
        run_id=json.loads(data)['run_id']
        for _ in range(45):
            code,data,_=self.req('/api/admin/ai/status?id='+self.oid,headers={'Cookie':self.cookie})
            self.assertEqual(code,200)
            run=json.loads(data)['runs'][0]
            if run['state'] in ('pronto','falhou'):break
            time.sleep(0.2)
        self.assertEqual(run['state'],'pronto',run)
        self.assertGreaterEqual(len(run['artifacts']),2)
        url='/api/admin/ai/file?run='+run_id+'&name=Fotos_StayVision.zip'
        code,body,_=self.req(url,headers={'Cookie':self.cookie})
        self.assertEqual(code,200)
        with zipfile.ZipFile(io.BytesIO(body)) as z: self.assertEqual(len(z.namelist()),1)
        code,_,_=self.req(url);self.assertEqual(code,401)
        code,_,_=self.req('/api/admin/ai/file?run='+run_id+'&name=../../db.sqlite',headers={'Cookie':self.cookie})
        self.assertEqual(code,400)
        with mod.connection() as db:
            self.assertEqual(db.execute('SELECT payment_status FROM orders WHERE id=?',(self.oid,)).fetchone()[0],'pendente')

if __name__=='__main__':unittest.main(verbosity=2)
