"""StayVision V3.39 — CRM privado e pesquisa oficial Google Places.
Não envia mensagens ou ligações em massa e não persiste resultados do Google Maps.
"""
import contextlib
import datetime as dt
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_LOCK = threading.RLock()
_LAST_SEARCH = 0.
_STATUSES = ("NOVO","QUALIFICADO","CONTATADO","RESPONDEU","PROPOSTA","GANHO","PERDIDO")

def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def _db():
    folder = Path(os.getenv("STAYVISION_DATA_DIR") or "dados")
    folder.mkdir(parents=True,exist_ok=True)
    db = sqlite3.connect(folder/"prospeccao.sqlite3",timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("""CREATE TABLE IF NOT EXISTS leads(
        id TEXT PRIMARY KEY,nome TEXT NOT NULL,cidade TEXT NOT NULL,categoria TEXT NOT NULL,
        telefone TEXT NOT NULL DEFAULT '',instagram TEXT NOT NULL DEFAULT '',
        website TEXT NOT NULL DEFAULT '',origem TEXT NOT NULL,
        notas TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'NOVO',
        prioridade INTEGER NOT NULL DEFAULT 0,
        whatsapp_ok INTEGER NOT NULL DEFAULT 0,ligacao_ok INTEGER NOT NULL DEFAULT 0,
        fonte_consentimento TEXT NOT NULL DEFAULT '',bloqueado INTEGER NOT NULL DEFAULT 0,
        criado TEXT NOT NULL,atualizado TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS eventos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,lead_id TEXT NOT NULL,
        tipo TEXT NOT NULL,detalhes TEXT NOT NULL DEFAULT '',criado TEXT NOT NULL)""")
    return db

def _auth(h,write=False):
    from admin_panel import _check
    _check(h,modify=write)

def _reply(h,data,code=200):
    h._send(json.dumps(data,ensure_ascii=False),code)

def _body(h):
    from commerce_flow import _body as decode
    x=decode(h,limit=12000)
    if not isinstance(x,dict):raise ValueError("Envie um objeto JSON.")
    return x

def _clean(x,n=160):
    if not isinstance(x,str):raise ValueError("Texto inválido.")
    x=x.strip()
    if len(x)>n or any(ord(c)<32 and c!='\n' for c in x):
        raise ValueError("Campo inválido ou muito longo.")
    return x

def _tel(x):
    x=_clean(x,25)
    if not x:return ""
    digits=re.sub(r"\D","",x)
    if len(digits)<10 or len(digits)>13:raise ValueError("Informe telefone com DDD.")
    return digits

def _event(db,ident,kind,details=""):
    db.execute("INSERT INTO eventos(lead_id,tipo,detalhes,criado) VALUES(?,?,?,?)",
               (ident,kind,details,_now()))

def _lead(db,ident):
    if not isinstance(ident,str) or not re.fullmatch(r"[a-f0-9]{16}",ident):
        raise ValueError("Identificador inválido.")
    row=db.execute("SELECT * FROM leads WHERE id=?",(ident,)).fetchone()
    if row is None:raise ValueError("Lead não encontrado.")
    return dict(row)

def list_leads(h):
    try:
        _auth(h)
        with contextlib.closing(_db()) as db:
            data=[dict(r) for r in db.execute("SELECT * FROM leads ORDER BY atualizado DESC LIMIT 500")]
            events=[dict(r) for r in db.execute("SELECT lead_id,tipo,detalhes,criado FROM eventos ORDER BY id DESC LIMIT 60")]
        for row in data:
            for k in ("whatsapp_ok","ligacao_ok","bloqueado"):row[k]=bool(row[k])
        return _reply(h,{"ok":True,"leads":data,"events":events,
                "maps_enabled":bool(os.getenv("GOOGLE_PLACES_API_KEY")),
                "auto_messages":False,"auto_calls":False})
    except PermissionError:return _reply(h,{"error":"Faça login no painel."},401)
    except Exception:return _reply(h,{"error":"Erro ao consultar CRM."},500)

def change_lead(h):
    try:
        _auth(h,True)
        p=_body(h)
        action=_clean(p.get("action",""),30)
        with _LOCK,contextlib.closing(_db()) as db,db:
            if action=="create":
                nome=_clean(p.get("nome",""),120)
                cidade=_clean(p.get("cidade",""),90)
                categoria=_clean(p.get("categoria","Outros"),50)
                origem=_clean(p.get("origem",""),180)
                telefone=_tel(p.get("telefone",""))
                instagram=_clean(p.get("instagram",""),120)
                website=_clean(p.get("website",""),250)
                notas=_clean(p.get("notas",""),650)
                prioridade=int(p.get("prioridade",0))
                if not nome or not cidade or not origem:raise ValueError("Informe empresa, cidade e origem independente dos dados.")
                if prioridade not in (0,1,2):raise ValueError("Prioridade inválida.")
                if telefone and db.execute("SELECT 1 FROM leads WHERE telefone=?",(telefone,)).fetchone():
                    raise ValueError("Telefone já cadastrado.")
                ident=secrets.token_hex(8)
                now=_now()
                db.execute("""INSERT INTO leads
                (id,nome,cidade,categoria,telefone,instagram,website,origem,notas,prioridade,criado,atualizado)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ident,nome,cidade,categoria,telefone,instagram,website,origem,notas,prioridade,now,now))
                _event(db,ident,"CRIADO","Cadastro com fonte independente")
                return _reply(h,{"ok":True,"id":ident})
            lead=_lead(db,p.get("id"))
            ident=lead["id"]
            if action=="status":
                status=_clean(p.get("status",""),30)
                if status not in _STATUSES:raise ValueError("Etapa inválida.")
                db.execute("UPDATE leads SET status=?,atualizado=? WHERE id=?",(status,_now(),ident))
                _event(db,ident,"ETAPA",status)
            elif action=="consent":
                canal=_clean(p.get("canal",""),20)
                if canal not in ("whatsapp","ligacao"):raise ValueError("Canal inválido.")
                autorizado=p.get("permitido") is True
                prova=_clean(p.get("fonte",""),220)
                if autorizado and (lead["bloqueado"] or not lead["telefone"] or len(prova)<12):
                    raise ValueError("Necessário telefone, autorização comprovada e lead não bloqueado.")
                field="whatsapp_ok" if canal=="whatsapp" else "ligacao_ok"
                db.execute("UPDATE leads SET "+field+"=?,fonte_consentimento=?,atualizado=? WHERE id=?",
                           (int(autorizado),prova if autorizado else lead["fonte_consentimento"],_now(),ident))
                _event(db,ident,"CONSENTIMENTO",canal+": "+("AUTORIZADO" if autorizado else "REVOGADO"))
            elif action=="optout":
                db.execute("UPDATE leads SET bloqueado=1,whatsapp_ok=0,ligacao_ok=0,atualizado=? WHERE id=?",
                           (_now(),ident))
                _event(db,ident,"OPOSICAO","Não contatar novamente")
            elif action=="activity":
                tipo=_clean(p.get("tipo",""),20)
                if tipo not in ("WHATSAPP","LIGACAO","NOTA"):raise ValueError("Tipo inválido.")
                if lead["bloqueado"]:raise ValueError("Contato bloqueado.")
                if tipo=="WHATSAPP" and not lead["whatsapp_ok"]:raise ValueError("WhatsApp não autorizado.")
                if tipo=="LIGACAO" and not lead["ligacao_ok"]:raise ValueError("Ligação não autorizada.")
                detalhe=_clean(p.get("detalhes",""),300)
                db.execute("UPDATE leads SET atualizado=? WHERE id=?",(_now(),ident))
                _event(db,ident,tipo,detalhe)
            elif action=="delete":
                db.execute("DELETE FROM eventos WHERE lead_id=?",(ident,))
                db.execute("DELETE FROM leads WHERE id=?",(ident,))
            else:raise ValueError("Ação inválida.")
        return _reply(h,{"ok":True})
    except PermissionError as e:return _reply(h,{"error":str(e)},401)
    except (ValueError,TypeError) as e:return _reply(h,{"error":str(e)},400)
    except Exception:return _reply(h,{"error":"Operação não concluída."},500)

def maps_search(h):
    """Google Places Text Search (New): resultados efêmeros, não cadastrados no CRM."""
    global _LAST_SEARCH
    try:
        _auth(h,True)
        p=_body(h)
        query=_clean(p.get("query",""),100)
        if len(query)<4:raise ValueError("Informe segmento e cidade.")
        key=os.getenv("GOOGLE_PLACES_API_KEY","").strip()
        if not key:raise ValueError("Configure GOOGLE_PLACES_API_KEY antes de pesquisar. Google Places pode cobrar pela consulta.")
        with _LOCK:
            if time.monotonic()-_LAST_SEARCH<15:raise ValueError("Aguarde 15 segundos entre pesquisas.")
            _LAST_SEARCH=time.monotonic()
        payload=json.dumps({"textQuery":query,"pageSize":10,"languageCode":"pt-BR","regionCode":"BR"}).encode()
        req=urllib.request.Request("https://places.googleapis.com/v1/places:searchText",
            data=payload,method="POST",headers={
                "Content-Type":"application/json",
                "X-Goog-Api-Key":key,
                "X-Goog-FieldMask":"places.id,places.displayName,places.formattedAddress,places.googleMapsUri"})
        try:
            with urllib.request.urlopen(req,timeout=10) as resp:
                result=json.loads(resp.read(80000))
        except (urllib.error.URLError,TimeoutError):
            return _reply(h,{"error":"Busca indisponível. Verifique a chave Places e o faturamento Google."},502)
        out=[]
        for place in (result.get("places") or [])[:10]:
            if not isinstance(place,dict):continue
            out.append({"nome":str((place.get("displayName") or {}).get("text",""))[:120],
                "endereco":str(place.get("formattedAddress",""))[:200],
                "maps_url":str(place.get("googleMapsUri",""))[:450]})
        return _reply(h,{"ok":True,"results":out,"source":"Google Maps",
                "notice":"Resultados apenas para consulta, sem exportação ou cadastro automático no CRM. Cadastre contatos somente de fontes independentes."})
    except PermissionError:return _reply(h,{"error":"Login necessário."},401)
    except ValueError as e:return _reply(h,{"error":str(e)},400)
    except Exception:return _reply(h,{"error":"Busca não concluída."},500)
