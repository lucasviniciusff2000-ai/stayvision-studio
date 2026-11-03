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
    db.execute("""CREATE TABLE IF NOT EXISTS configuracao_prospeccao(
        chave TEXT PRIMARY KEY,valor TEXT NOT NULL,atualizado TEXT NOT NULL)""")
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
    # Links wa.me e API Cloud exigem DDI; normalizamos números brasileiros.
    if len(digits) in (10,11):digits="55"+digits
    if not digits.startswith("55") or len(digits) not in (12,13):
        raise ValueError("Informe um telefone brasileiro com DDD.")
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
            owner=db.execute("SELECT valor FROM configuracao_prospeccao WHERE chave='whatsapp_empresa'").fetchone()
            owner_whatsapp=owner["valor"] if owner else ""
        for row in data:
            for k in ("whatsapp_ok","ligacao_ok","bloqueado"):row[k]=bool(row[k])
        return _reply(h,{"ok":True,"leads":data,"events":events,
                "maps_enabled":bool(os.getenv("GOOGLE_PLACES_API_KEY")),
                "auto_messages":False,"auto_calls":False,
                "whatsapp_empresa":owner_whatsapp,
                "whatsapp_api_configured":bool((os.getenv("SV_GS_API_KEY") and os.getenv("SV_GS_SOURCE") and os.getenv("SV_GS_APP_NAME")) if os.getenv("SV_WA_PROVIDER","").lower()=="gupshup" else (os.getenv("SV_WA_CLOUD_TOKEN") and os.getenv("SV_WA_PHONE_NUMBER_ID") and os.getenv("SV_WA_TEMPLATE_NAME"))),
                "whatsapp_provider":os.getenv("SV_WA_PROVIDER","").lower() or "nao_configurado",
                "whatsapp_api_send_enabled":os.getenv("SV_WA_SEND_ENABLED")=="1" and os.getenv("SV_WA_PROVIDER","").lower()!="gupshup",
                "whatsapp_api_connected":False})
    except PermissionError:return _reply(h,{"error":"Faça login no painel."},401)
    except Exception:return _reply(h,{"error":"Erro ao consultar CRM."},500)

def change_lead(h):
    try:
        _auth(h,True)
        p=_body(h)
        action=_clean(p.get("action",""),30)
        with _LOCK,contextlib.closing(_db()) as db,db:
            if action=="whatsapp_empresa":
                # Apenas cadastra o número do operador. Não autentica no Meta,
                # não lê conversas e não habilita disparos automáticos.
                raw=p.get("telefone","")
                phone=_tel(raw) if raw else ""
                db.execute("""INSERT INTO configuracao_prospeccao(chave,valor,atualizado)
                     VALUES('whatsapp_empresa',?,?)
                     ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor,
                         atualizado=excluded.atualizado""",(phone,_now()))
                return _reply(h,{"ok":True,"whatsapp_empresa":phone,
                    "modo":"link_apenas","mensagens_enviadas":0})
            if action=="bulk_import":
                batch=p.get("empresas",[])
                source=_clean(p.get("origem",""),180)
                if not isinstance(batch,list) or not 1<=len(batch)<=50:
                    raise ValueError("Envie de 1 a 50 empresas por importação.")
                if len(source)<5:
                    raise ValueError("Informe a fonte independente dos contatos.")
                if re.search(r"google\s*maps|maps\.google|goo\.gl/maps",source,re.I):
                    raise ValueError("Não é permitido importar listas obtidas do Google Maps.")
                created=0;duplicates=0;invalid=[]
                now=_now()
                for ix,item in enumerate(batch,1):
                    try:
                        if not isinstance(item,dict):raise ValueError()
                        nome=_clean(item.get("nome",""),120)
                        telefone=_tel(item.get("telefone",""))
                        website=_clean(item.get("website",""),250)
                        instagram=_clean(item.get("instagram",""),120)
                        cidade=_clean(item.get("cidade",""),90) or "Não informada"
                        categoria=_clean(item.get("categoria","Alimentação"),50) or "Outros"
                        if not nome or not telefone:raise ValueError()
                        existing=db.execute("SELECT 1 FROM leads WHERE telefone=? OR (lower(nome)=lower(?) AND cidade=?) LIMIT 1",(telefone,nome,cidade)).fetchone()
                        if existing:duplicates+=1;continue
                        ident=secrets.token_hex(8)
                        db.execute("""INSERT INTO leads
                            (id,nome,cidade,categoria,telefone,instagram,website,origem,notas,prioridade,criado,atualizado)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (ident,nome,cidade,categoria,telefone,instagram,website,source,"",0,now,now))
                        _event(db,ident,"CRIADO","Importação revisada pelo operador; origem independente")
                        created+=1
                    except (ValueError,TypeError):
                        invalid.append(ix)
                return _reply(h,{"ok":True,"cadastrados":created,
                    "duplicados":duplicates,"linhas_invalidas":invalid,
                    "mensagens_enviadas":0})
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
                if not nome or not origem:raise ValueError("Informe empresa e origem independente dos dados.")
                if not cidade:cidade="Não informada"
                if prioridade not in (0,1,2):raise ValueError("Prioridade inválida.")
                if telefone and db.execute("SELECT 1 FROM leads WHERE telefone=?",(telefone,)).fetchone():
                    raise ValueError("Telefone já cadastrado.")
                if db.execute("SELECT 1 FROM leads WHERE lower(nome)=lower(?) AND telefone=?",(nome,telefone)).fetchone():
                    raise ValueError("Empresa já cadastrada.")
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

def _maps_mark_failure(day):
    """Registra falhas sem fazer consultas adicionais nem remover limites."""
    with _LOCK:
        with contextlib.closing(_db()) as db, db:
            db.execute("UPDATE maps_quota_v2 SET failures=failures+1 WHERE day=?",(day,))

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
        # V2: a versão inicial consumiu as 10 vagas com erros HTTP 403
        # antes da ativação do faturamento. Contador separado preserva
        # a trilha antiga e permite diagnosticar com limite estrito de custos.
        with _LOCK:
            if time.monotonic()-_LAST_SEARCH<15:
                raise ValueError("Aguarde 15 segundos entre pesquisas.")
            day=dt.datetime.now(dt.timezone.utc).date().isoformat()
            with contextlib.closing(_db()) as db, db:
                db.execute("""CREATE TABLE IF NOT EXISTS maps_quota_v2(
                            day TEXT PRIMARY KEY,used INTEGER NOT NULL,
                            failures INTEGER NOT NULL DEFAULT 0)""")
                row=db.execute("SELECT used,failures FROM maps_quota_v2 WHERE day=?",(day,)).fetchone()
                if row and row["used"]>=10:
                    raise ValueError("Limite de segurança: 10 consultas por dia. Tente amanhã.")
                if row and row["failures"]>=3:
                    raise ValueError("Três consultas falharam hoje. Verifique as permissões e o faturamento do Google antes de tentar novamente amanhã.")
                db.execute("""INSERT INTO maps_quota_v2(day,used,failures) VALUES(?,1,0)
                              ON CONFLICT(day) DO UPDATE SET used=used+1""",(day,))
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
        except urllib.error.HTTPError as ex:
            _maps_mark_failure(day)
            # HTTPError também é URLError. Capturar antes permite mostrar a causa
            # sem retornar a resposta bruta do Google (que pode conter metadados).
            code=int(ex.code)
            body={}
            try:
                body=json.loads(ex.read(8192).decode("utf-8","replace"))
            except (ValueError,UnicodeError,TypeError):
                pass
            details=body.get("error",{}) if isinstance(body,dict) else {}
            if not isinstance(details,dict):details={}
            reason=""
            for item in details.get("details",[]):
                if isinstance(item,dict) and isinstance(item.get("reason"),str):
                    reason=item["reason"][:72]
                    break
            # A resposta do Google pode explicar um 403 genérico. Expor apenas
            # um trecho higienizado no painel ADMIN, nunca chave ou payload bruto.
            raw_message=str(details.get("message",""))[:700]
            safe_message=re.sub(r"AIza[A-Za-z0-9_-]{20,}","[CHAVE_OCULTA]",raw_message)
            safe_message=re.sub(r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*[^\s,;]+","[CREDENCIAL_OCULTA]",safe_message)
            safe_message=re.sub(r"[\x00-\x1f\x7f]+"," ",safe_message)[:260].strip()
            message=raw_message.lower()
            if "billing" in message or "faturamento" in message or reason in ("BILLING_DISABLED","BILLING_NOT_ENABLED"):
                hint="Ative o faturamento no projeto Google Cloud ao qual a chave pertence."
            elif "referer" in message or "referrer" in message or "website restriction" in message or reason in ("API_KEY_HTTP_REFERRER_BLOCKED",):
                hint="A chave está restrita a sites. Para a Railway, use chave de servidor sem restrição de referenciador."
            elif "api key" in message and ("invalid" in message or "not valid" in message or "expired" in message) or reason in ("API_KEY_INVALID","API_KEY_EXPIRED"):
                hint="A chave é inválida. Confira se foi copiada corretamente na Railway."
            elif "not enabled" in message or "has not been used" in message or "disabled" in message or reason in ("SERVICE_DISABLED",):
                hint="Ative Places API (New) no mesmo projeto Google Cloud da chave."
            elif "blocked" in message or reason.startswith("API_KEY_"):
                hint="O Google bloqueou esta chave ou a API. Confira restrições e projeto da chave."
            elif code==403:
                hint="Google negou acesso. Confira se faturamento e Places API (New) estão ativos no MESMO projeto da chave."
            elif code==429 or reason in ("RATE_LIMIT_EXCEEDED","QUOTA_EXCEEDED"):
                hint="A cota ou limite de uso Google Places foi atingido. Confira Quotas no Google Cloud."
            elif code==400:
                hint="O Google rejeitou os parâmetros da consulta. Verifique a configuração da API."
            else:
                hint="Confira se Places API (New) e o faturamento estão ativos no projeto da chave."
            safe_reason=reason if re.fullmatch(r"[A-Z][A-Z0-9_]{1,71}",reason) else str(details.get("status",""))[:45]
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,44}",safe_reason):safe_reason="DESCONHECIDO"
            print("[PLACES] Google respondeu HTTP",code,"motivo",safe_reason,flush=True)
            diagnostic=((" Detalhe Google: "+safe_message) if safe_message else "")
            return _reply(h,{"error":hint+" (Google HTTP "+str(code)+"; motivo "+safe_reason+")"+diagnostic,
                             "google_http":code,"google_reason":safe_reason},502)
        except (urllib.error.URLError,TimeoutError) as ex:
            _maps_mark_failure(day)
            print("[PLACES] Falha de transporte",type(ex).__name__,flush=True)
            return _reply(h,{"error":"Falha de conexão entre a Railway e a API Places. Verifique a rede ou tente novamente."},502)
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
