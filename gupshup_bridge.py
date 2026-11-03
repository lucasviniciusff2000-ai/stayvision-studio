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
    """Webhook Meta v3 Gupshup: confirmar rapido, registrar apenas eventos validos.

    Os diagnosticos registram SOMENTE contagens/motivos, sem numeros/textos/IDs.
    """
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
            print("[SV_WA_DIAG] event=other_object",flush=True)
            return h._send("",200,mime="text/plain")
        from whatsapp_ai_atendimento import enabled,_configured,_db,_LOCK
        test_phone=re.sub(r"\D","",os.getenv("SV_WA_TEST_PHONE",""))
        if not test_phone and os.getenv("SV_WA_LIVE_APPROVED")!="1":
            print("[SV_WA_DIAG] event=pilot_not_authorized",flush=True)
            return h._send("",200,mime="text/plain")
        now=int(time.time())
        counts=dict(changes=0,text=0,nontext=0,stored=0,duplicate=0,
                    outside_test=0,invalid_message=0,stale=0,source_diff=0,
                    receipt_updated=0,receipt_unmatched=0)
        source=os.getenv("SV_GS_SOURCE","")
        for entry in (payload.get("entry") or [])[:10]:
            if not isinstance(entry,dict):continue
            for change in (entry.get("changes") or [])[:10]:
                if not isinstance(change,dict) or change.get("field")!="messages":continue
                counts["changes"]+=1
                val=change.get("value") or {}
                if not isinstance(val,dict):continue
                metadata=val.get("metadata") or {}
                if isinstance(metadata,dict):
                    display=re.sub(r"\D","",str(metadata.get("display_phone_number","")))
                    if display and source and display!=source:
                        counts["source_diff"]+=1
                # Delivery receipts are asynchronous and are linked to existing
                # outbound requests by Gupshup's gs_id, not by the user's phone.
                for st in (val.get("statuses") or [])[:30]:
                    if not isinstance(st,dict):continue
                    event=str(st.get("status","")).lower()
                    if event not in ("enqueued","sent","delivered","read","failed"):
                        continue
                    counts["receipt_"+event]=counts.get("receipt_"+event,0)+1
                    gs_id=str(st.get("gs_id") or (st.get("id") if event in ("enqueued","failed") else "") or "")
                    if not re.fullmatch(r"[a-zA-Z0-9_.:=/+-]{10,250}",gs_id):
                        counts["receipt_unmatched"]+=1
                        continue
                    errors=st.get("errors") or []
                    code=""
                    if event=="failed" and isinstance(errors,list) and errors and isinstance(errors[0],dict):
                        raw_code=str(errors[0].get("code",""))
                        if re.fullmatch(r"\d{1,6}",raw_code):
                            code=raw_code
                            counts["fail_code_"+code]=counts.get("fail_code_"+code,0)+1
                    target=("GS_FAILED"+("_"+code if code else "") if event=="failed"
                            else "GS_"+event.upper())
                    order={"ACEITO_GUPSHUP":0,"GS_ENQUEUED":1,"GS_SENT":2,
                           "GS_DELIVERED":3,"GS_READ":4}
                    with _LOCK,contextlib.closing(_db()) as db,db:
                        existing=db.execute("""SELECT estado FROM wa_chat
                            WHERE direcao='OUT' AND meta_id=?""",(gs_id,)).fetchone()
                        if existing:
                            old=existing["estado"]
                            if (old.startswith("GS_FAILED") or
                                (event=="failed" and old in ("GS_DELIVERED","GS_READ")) or
                                (event!="failed" and
                                 order.get(old,-1)>=order.get(target,0))):
                                continue
                            db.execute("""UPDATE wa_chat SET estado=?
                                WHERE direcao='OUT' AND meta_id=?""",(target,gs_id))
                            counts["receipt_updated"]+=1
                        else:
                            counts["receipt_unmatched"]+=1
                # gs_app_id + header privado autenticam a conta; display_phone_number
                # pode vir mascarado/normalizado e nao pode bloquear o piloto.
                for m in (val.get("messages") or [])[:20]:
                    if not isinstance(m,dict):continue
                    if m.get("type")!="text":
                        counts["nontext"]+=1
                        continue
                    counts["text"]+=1
                    mid=str(m.get("id",""))
                    phone=re.sub(r"\D","",str(m.get("from","")))
                    txt=m.get("text") or {}
                    content=txt.get("body","") if isinstance(txt,dict) else ""
                    content=str(content).strip()
                    try:timestamp=int(m.get("timestamp",0))
                    except (ValueError,TypeError):timestamp=-1
                    if not (re.fullmatch(r"[a-zA-Z0-9_.:=/+\-]{10,250}",mid)
                            and re.fullmatch(r"\d{10,15}",phone)
                            and 0<len(content)<=4000):
                        counts["invalid_message"]+=1
                        continue
                    if test_phone and phone!=test_phone:
                        counts["outside_test"]+=1
                        continue
                    if not 0<=now-timestamp<86400:
                        counts["stale"]+=1
                        continue
                    with _LOCK,contextlib.closing(_db()) as db,db:
                        state="PENDENTE" if enabled() and _configured() else "RECEBIDO_TESTE"
                        cur=db.execute("""INSERT OR IGNORE INTO wa_chat
                            (id,telefone,direcao,texto,estado,timestamp,criado)
                            VALUES(?,?,'IN',?,?,?,?)""",
                            (mid,phone,content,state,timestamp,now))
                        counts["stored" if cur.rowcount else "duplicate"]+=1
        print("[SV_WA_DIAG] "+ " ".join(
            f"{k}={v}" for k,v in counts.items()),flush=True)
        return h._send("",200,mime="text/plain")
    except (TypeError,ValueError,AttributeError,UnicodeError):
        print("[SV_WA_DIAG] invalid_payload",flush=True)
        return h._send("",400,mime="text/plain")
    except Exception:
        print("[SV_WA_DIAG] processing_failure",flush=True)
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
        "https://api.gupshup.io/wa/api/v1/msg",data=data,
        headers={"apikey":token,
                 "Content-Type":"application/x-www-form-urlencoded",
                 "Accept":"application/json"},
        method="POST")
    with urllib.request.urlopen(req,timeout=15) as response:
        result=json.load(response)
    if result.get("status")!="submitted" or not result.get("messageId"):
        raise RuntimeError("Gupshup nao confirmou envio. Confira seu painel.")
    return str(result["messageId"])[:250]

def send_image(phone, image_url, caption=""):
    """Envia imagem de portfolio por URL HTTPS publica via Gupshup."""
    from urllib.parse import urlsplit
    u=urlsplit(image_url)
    if u.scheme!="https" or not u.netloc or u.username or u.password:
        raise ValueError("URL publica HTTPS de imagem invalida")
    token=os.getenv("SV_GS_API_KEY","")
    source=os.getenv("SV_GS_SOURCE","")
    app=os.getenv("SV_GS_APP_NAME","StayVisionBusiness")
    if (not token or not re.fullmatch(r"\d{10,15}",source)
        or not re.fullmatch(r"\d{10,15}",phone)
        or not re.fullmatch(r"[A-Za-z0-9_-]{3,120}",app)):
        raise ValueError("Configuracao Gupshup invalida")
    fields={
        "channel":"whatsapp","source":source,"destination":phone,"src.name":app,
        "message":json.dumps({"type":"image","originalUrl":image_url,
                              "caption":caption[:500]},ensure_ascii=False)
    }
    req=urllib.request.Request(
        "https://api.gupshup.io/wa/api/v1/msg",
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={"apikey":token,"Content-Type":"application/x-www-form-urlencoded",
                 "Accept":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=15) as response:
        result=json.load(response)
    if result.get("status")!="submitted" or not result.get("messageId"):
        raise RuntimeError("Gupshup nao confirmou envio de imagem")
    return str(result["messageId"])[:250]
