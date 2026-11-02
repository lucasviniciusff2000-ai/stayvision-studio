"""Adaptador WhatsApp Gupshup, eventos Meta v3 e mensagens de sessao.

Os webhooks da Gupshup NAO sao assinaturas Meta. Exigimos cabecalho
compartilhado configurado em 'Include headers' e conferimos GS App ID.
Nao habilitar com callback publico sem o cabecalho privado.
"""
import contextlib
import hmac
import json
import os
import re
import time
import urllib.parse
import urllib.request

def configured():
    return all(os.getenv(k,"").strip() for k in (
        "SV_GS_APP_ID","SV_GS_SOURCE","SV_GS_API_KEY",
        "SV_GS_WEBHOOK_SECRET","GEMINI_API_KEY"))

def webhook(h):
    secret=os.getenv("SV_GS_WEBHOOK_SECRET","")
    received=h.headers.get("X-StayVision-Webhook-Key","")
    if len(secret)<32 or not hmac.compare_digest(secret,received):
        return h._send("",403,mime="text/plain")
    try:
        length=int(h.headers.get("Content-Length","0"))
        if not 0<length<=128000:return h._send("",413,mime="text/plain")
        payload=json.loads(h.rfile.read(length).decode("utf-8"))
        if not isinstance(payload,dict):
            return h._send("",400,mime="text/plain")
        if payload.get("gs_app_id")!=os.getenv("SV_GS_APP_ID"):
            return h._send("",403,mime="text/plain")
        if payload.get("object")!="whatsapp_business_account":
            return h._send("",200,mime="text/plain")
        from whatsapp_ai_atendimento import enabled,_configured,_db,_LOCK
        if not enabled() or not _configured():
            return h._send("",200,mime="text/plain")
        test_phone=re.sub(r"\D","",os.getenv("SV_WA_TEST_PHONE",""))
        if not test_phone and os.getenv("SV_WA_LIVE_APPROVED")!="1":
            return h._send("",200,mime="text/plain")
        source=os.getenv("SV_GS_SOURCE","")
        now=int(time.time())
        for entry in (payload.get("entry") or [])[:10]:
            if not isinstance(entry,dict):continue
            for change in (entry.get("changes") or [])[:10]:
                if not isinstance(change,dict) or change.get("field")!="messages":continue
                val=change.get("value") or {}
                metadata=val.get("metadata") or {}
                display=re.sub(r"\D","",str(metadata.get("display_phone_number","")))
                if display and display!=source:continue
                for m in (val.get("messages") or [])[:20]:
                    if not isinstance(m,dict) or m.get("type")!="text":continue
                    mid=str(m.get("id",""))
                    phone=str(m.get("from",""))
                    text=str((m.get("text") or {}).get("body","")).strip()
                    try:timestamp=int(m.get("timestamp",0))
                    except (ValueError,TypeError):continue
                    if not (re.fullmatch(r"[a-zA-Z0-9_.:=/-]{10,250}",mid)
                        and re.fullmatch(r"\d{10,15}",phone)
                        and (not test_phone or phone==test_phone)
                        and 0<=now-timestamp<86400 and 0<len(text)<=4000):
                        continue
                    with _LOCK,contextlib.closing(_db()) as db,db:
                        db.execute("""INSERT OR IGNORE INTO wa_chat
                            (id,telefone,direcao,texto,estado,timestamp,criado)
                            VALUES(?,?,'IN',?,'PENDENTE',?,?)""",
                            (mid,phone,text,timestamp,now))
        # Gupshup solicita 2xx imediato e corpo vazio; worker responde depois.
        return h._send("",200,mime="text/plain")
    except (TypeError,ValueError,AttributeError,UnicodeError):
        return h._send("",400,mime="text/plain")
    except Exception:
        return h._send("",503,mime="text/plain")

def send_text(phone,answer):
    token=os.getenv("SV_GS_API_KEY","")
    source=os.getenv("SV_GS_SOURCE","")
    app=os.getenv("SV_GS_APP_NAME","StayVisionBusiness")
    if (not token or not re.fullmatch(r"\d{10,15}",source)
        or not re.fullmatch(r"\d{10,15}",phone)
        or not re.fullmatch(r"[A-Za-z0-9_-]{3,120}",app)):
        raise ValueError("Configuracao Gupshup invalida")
    fields={
        "channel":"whatsapp",
        "source":source,
        "destination":phone,
        "src.name":app,
        "message":json.dumps({"type":"text","text":answer},ensure_ascii=False)
    }
    data=urllib.parse.urlencode(fields).encode("utf-8")
    req=urllib.request.Request(
        "https://api.gupshup.io/sm/api/v1/msg",data=data,
        headers={"apikey":token,
                 "Content-Type":"application/x-www-form-urlencoded",
                 "Accept":"application/json"},
        method="POST")
    with urllib.request.urlopen(req,timeout=15) as response:
        result=json.load(response)
    if result.get("status")!="submitted" or not result.get("messageId"):
        raise RuntimeError("Gupshup nao confirmou envio. Confira seu painel.")
    return str(result["messageId"])[:250]
