"""Testes de seguranca do webhook sem rede, tokens reais ou envio de mensagens."""
import hashlib
import hmac
import io
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import whatsapp_ai_atendimento as wa

class Handler:
    def __init__(self,body=b"",headers=None,path="/api/whatsapp/webhook"):
        self.path=path
        self.headers=headers or {}
        self.rfile=io.BytesIO(body)
        self.output=None
    def _send(self,content,code=200,mime="application/json",extra=None):
        self.output=(code,content,mime)
        return self.output

class WAWebhookTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env={
            "STAYVISION_DATA_DIR":self.tmp.name,
            "SV_WA_AUTO_REPLY_ENABLED":"1",
            "SV_WA_WEBHOOK_VERIFY_TOKEN":"only_for_test_123",
            "SV_WA_APP_SECRET":"app_secret_testing",
            "SV_WA_CLOUD_TOKEN":"dummy_token",
            "SV_WA_PHONE_NUMBER_ID":"123456789012",
            "SV_WA_TEST_PHONE":"5547999999999",
            "GEMINI_API_KEY":"dummy_gemini",
        }
        self.env=patch.dict(os.environ,env)
        self.env.start()
        self.addCleanup(self.env.stop)

    def _signed_event(self,msg="wamid.ABCD12345678"):
        event={"object":"whatsapp_business_account","entry":[{"changes":[{
            "value":{"metadata":{"phone_number_id":"123456789012"},
                     "messages":[{"id":msg,"from":"5547999999999",
                                  "type":"text","timestamp":str(int(time.time())),
                                  "text":{"body":"Como funciona?"}}]}}]}]}
        body=json.dumps(event).encode()
        signature="sha256="+hmac.new(b"app_secret_testing",body,hashlib.sha256).hexdigest()
        return Handler(body,{"Content-Length":str(len(body)),
                             "X-Hub-Signature-256":signature})

    def test_webhook_verification(self):
        ok=Handler(path="/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=only_for_test_123&hub.challenge=49384")
        wa.verify(ok)
        self.assertEqual(ok.output[0],200)
        self.assertEqual(ok.output[1],"49384")
        bad=Handler(path="/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=bad&hub.challenge=1")
        wa.verify(bad)
        self.assertEqual(bad.output[0],403)

    def test_forged_post_rejected(self):
        h=self._signed_event()
        h.headers["X-Hub-Signature-256"]="sha256="+"0"*64
        wa.webhook(h)
        self.assertEqual(h.output[0],403)

    def test_duplicate_webhook_only_queues_once(self):
        for _ in range(2):
            h=self._signed_event()
            wa.webhook(h)
            self.assertEqual(h.output[0],200)
        with wa._db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM wa_chat").fetchone()[0],1)

    def test_disabled_mode_does_not_collect_text(self):
        os.environ["SV_WA_AUTO_REPLY_ENABLED"]="0"
        h=self._signed_event()
        wa.webhook(h)
        self.assertEqual(h.output[0],200)
        with wa._db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM wa_chat").fetchone()[0],0)

    def test_human_handoff_and_pause(self):
        h=self._signed_event()
        wa.webhook(h)
        item=wa._next()
        item["texto"]="Quero falar com atendente humano"
        with patch.object(wa,"_send_text",return_value="wamid.SENT123456") as sender:
            state,_=wa._process(item)
        self.assertEqual(state,"ACEITO_META")
        self.assertEqual(sender.call_count,1)
        with wa._db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM wa_pausas").fetchone()[0],1)

if __name__=="__main__":
    unittest.main()
