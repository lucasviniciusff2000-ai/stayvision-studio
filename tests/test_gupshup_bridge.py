"""Gupshup v3 tests without network and without real credentials."""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
import gupshup_bridge as bridge
import whatsapp_ai_atendimento as wa

class Handler:
    def __init__(self,raw,auth):
        self.headers={"Content-Length":str(len(raw)),
                      "X-StayVision-Webhook-Key":auth}
        self.rfile=io.BytesIO(raw)
        self.status=None
    def _send(self,body,code=200,mime="application/json",extra=None):
        self.status=code
        return (code,body,mime)

class GupshupTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.secret="a_really_long_secret_only_for_webhook_test_1234"
        env={
          "STAYVISION_DATA_DIR":self.temp.name,
          "SV_WA_PROVIDER":"gupshup",
          "SV_WA_AUTO_REPLY_ENABLED":"1",
          "SV_WA_TEST_PHONE":"5547999999999",
          "SV_GS_WEBHOOK_SECRET":self.secret,
          "SV_GS_APP_ID":"ec3591fc-132b-4039-8cec-945e3b61537f",
          "SV_GS_SOURCE":"554797546758",
          "SV_GS_API_KEY":"test_only_do_not_use",
          "GEMINI_API_KEY":"dummy_test",
        }
        self.patch=patch.dict(os.environ,env)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def event(self,app=None):
        body={"object":"whatsapp_business_account",
              "gs_app_id":app or os.getenv("SV_GS_APP_ID"),
              "entry":[{"changes":[{"field":"messages","value":{
                  "metadata":{"display_phone_number":"554797546758"},
                  "messages":[{"id":"wamid.Test10000","from":"5547999999999",
                               "type":"text","timestamp":str(int(time.time())),
                               "text":{"body":"Quais são os planos?"}}]}}]}]}
        return json.dumps(body).encode()

    def test_reject_missing_header(self):
        h=Handler(self.event(),"")
        bridge.webhook(h)
        self.assertEqual(h.status,403)

    def test_wrong_app_id_is_rejected(self):
        h=Handler(self.event("wrong"),self.secret)
        bridge.webhook(h)
        self.assertEqual(h.status,403)

    def test_persists_once_on_redelivery(self):
        for _ in range(2):
            h=Handler(self.event(),self.secret)
            bridge.webhook(h)
            self.assertEqual(h.status,200)
        with contextlib.closing(wa._db()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wa_chat").fetchone()[0],1)

    def test_authenticated_event_with_masked_display_is_received(self):
        body=json.loads(self.event())
        body["entry"][0]["changes"][0]["value"]["metadata"]["display_phone_number"]="55****6758"
        h=Handler(json.dumps(body).encode(),self.secret)
        bridge.webhook(h)
        self.assertEqual(h.status,200)
        with contextlib.closing(wa._db()) as db:
            self.assertEqual(db.execute("SELECT estado FROM wa_chat").fetchone()[0],"PENDENTE")

    def test_outside_test_phone_never_queued(self):
        body=json.loads(self.event())
        body["entry"][0]["changes"][0]["value"]["messages"][0]["from"]="5547888888888"
        h=Handler(json.dumps(body).encode(),self.secret)
        bridge.webhook(h)
        self.assertEqual(h.status,200)
        with contextlib.closing(wa._db()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wa_chat").fetchone()[0],0)

    def test_delivery_receipt_updates_existing_outbound(self):
        gs_id="4ac9aaf0-22d4-4716-8895-21876bb4ce52"
        now=int(time.time())
        with contextlib.closing(wa._db()) as db,db:
            db.execute("""INSERT INTO wa_chat
                (id,telefone,direcao,texto,estado,timestamp,criado,meta_id)
                VALUES(?,?,'OUT',?,'ACEITO_GUPSHUP',?,?,?)""",
                (gs_id,"5547999999999","teste",now,now,gs_id))
        for status in ("enqueued","sent","delivered"):
            payload={"object":"whatsapp_business_account",
                     "gs_app_id":os.getenv("SV_GS_APP_ID"),
                     "entry":[{"changes":[{"field":"messages",
                        "value":{"statuses":[{"status":status,"gs_id":gs_id}]}}]}]}
            h=Handler(json.dumps(payload).encode(),self.secret)
            bridge.webhook(h)
            self.assertEqual(h.status,200)
        with contextlib.closing(wa._db()) as db:
            self.assertEqual(db.execute("""SELECT estado FROM wa_chat
                WHERE id=?""",(gs_id,)).fetchone()[0],"GS_DELIVERED")

    def test_delivery_failure_stores_only_error_code(self):
        gs_id="4ac9aaf0-22d4-4716-8895-21876bb4ce53"
        now=int(time.time())
        with contextlib.closing(wa._db()) as db,db:
            db.execute("""INSERT INTO wa_chat
                (id,telefone,direcao,texto,estado,timestamp,criado,meta_id)
                VALUES(?,?,'OUT',?,'ACEITO_GUPSHUP',?,?,?)""",
                (gs_id,"5547999999999","teste",now,now,gs_id))
        payload={"object":"whatsapp_business_account",
                 "gs_app_id":os.getenv("SV_GS_APP_ID"),
                 "entry":[{"changes":[{"field":"messages",
                 "value":{"statuses":[{"status":"failed","gs_id":gs_id,
                          "errors":[{"code":131047,"title":"sensitive text"}]}]}}]}]}
        h=Handler(json.dumps(payload).encode(),self.secret)
        bridge.webhook(h)
        self.assertEqual(h.status,200)
        with contextlib.closing(wa._db()) as db:
            self.assertEqual(db.execute("""SELECT estado FROM wa_chat
                WHERE id=?""",(gs_id,)).fetchone()[0],"GS_FAILED_131047")

    def test_off_means_no_queued_messages(self):
        os.environ["SV_WA_AUTO_REPLY_ENABLED"]="0"
        h=Handler(self.event(),self.secret)
        bridge.webhook(h)
        self.assertEqual(h.status,200)
        with contextlib.closing(wa._db()) as db:
            self.assertEqual(db.execute("SELECT estado FROM wa_chat").fetchone()[0],"RECEBIDO_TESTE")

if __name__=="__main__":
    unittest.main()
