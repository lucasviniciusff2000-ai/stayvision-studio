"""StayVision V3.39: painel de prospecção administrativa.

- Google Places: consulta efêmera com atribuição. NUNCA armazena conteúdo
  Google Maps em listas comerciais; place IDs são a única exceção persistida.
- CRM: dados inseridos de fonte independente + autorização comprovada.
- WhatsApp e telefone: acionamento humano; nenhum disparo em massa.
"""
import datetime as dt
import contextlib
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

_LOCK=threading.RLock()
_LAST_MAPS_SEARCH=0.0
_STATUSES=('NOVO','QUALIFICADO','CONTATADO','RESPONDEU','PROPOSTA','GANHO','PERDIDO')
_CATEGORIES=('Alimentação','Moda e acessórios','Beleza','Tecnologia','Casa e decoração','Pets','Saúde','Outros')

def _utc():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

def _path():
    base=Path(os.getenv('STAYVISION_DATA_DIR',str(Path(__file__).parent/'dados')))
    base.mkdir(mode=0o700,parents=True,exist_ok=True)
    return base/'prospeccao.sqlite3'

def _db():
    db=sqlite3.connect(_path(),timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA busy_timeout=15000')
    db.execute('''CREATE TABLE IF NOT EXISTS leads(
        id TEXT PRIMARY KEY, nome TEXT NOT NULL, categoria TEXT NOT NULL, cidade TEXT NOT NULL,
        telefone TEXT NOT NULL, instagram TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '',
        origem TEXT NOT NULL, place_id TEXT NOT NULL DEFAULT '', observacoes TEXT NOT NULL DEFAULT '',
        prioridade INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'NOVO',
        consent_whatsapp INTEGER NOT NULL DEFAULT 0, consent_ligacao INTEGER NOT NULL DEFAULT 0,
        fonte_consentimento TEXT NOT NULL DEFAULT '', data_consentimento TEXT NOT NULL DEFAULT '',
        bloqueado INTEGER NOT NULL DEFAULT 0, criado TEXT NOT NULL, atualizado TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS eventos(
        id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT NOT NULL, tipo TEXT NOT NULL,
        detalhes TEXT NOT NULL DEFAULT '', criado TEXT NOT NULL)''')
    db.execute('''CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)''')
    return db

def _require_admin(handler,write=False):
    from admin_panel import _check
    return _check(handler,modify=write)

def _json(handler,data,status=200):
    handler._send(json.dumps(data,ensure_ascii=False),code=status)

def _read(handler):
    from commerce_flow import _body
    obj=_body(handler,limit=12000)
    if not isinstance(obj,dict):raise ValueError('Envie um objeto JSON.')
    return obj

def _str(x,maxlen=150):
    if not isinstance(x,str):raise ValueError('Campo inválido.')
    x=x.strip()
    if len(x)>maxlen or any(ord(c)<32 and c!='\n' for c in x):raise ValueError('Texto inválido ou muito longo.')
    return x

def _phone(x):
    x=_str(x,25)
    if not x:return ''
    digits=re.sub(r'\D','',x)
    if not 10<=len(digits)<=13:raise ValueError('Informe telefone com DDD (10 a 13 dígitos).')
    return digits

def _event(db,lead_id,kind,details=''):
    db.execute('INSERT INTO eventos(lead_id,tipo,detalhes,criado) VALUES(?,?,?,?)',(lead_id,kind,details,_utc()))

def _load(db,lead_id):
    if not re.fullmatch(r'[a-f0-9]{16}',str(lead_id or '')):raise ValueError('Identificador inválido.')
    row=db.execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone()
    if not row:raise LookupError('Lead não encontrado.')
    return dict(row)

def _item(row):
    return {**dict(row),'consent_whatsapp':bool(row['consent_whatsapp']),
            'consent_ligacao':bool(row['consent_ligacao']),'bloqueado':bool(row['bloqueado'])}

def list_leads(h):
    try:
        _require_admin(h)
        with contextlib.closing(_db()) as db:
            rows=[_item(r) for r in db.execute('SELECT * FROM leads ORDER BY atualizado DESC LIMIT 1000').fetchall()]
            events=[dict(x) for x in db.execute('SELECT lead_id,tipo,detalhes,criado FROM eventos ORDER BY id DESC LIMIT 75').fetchall()]
        return _json(h,{'ok':True,'leads':rows,'events':events,
             'maps_enabled':bool(os.getenv('GOOGLE_PLACES_API_KEY')),
             'outbound_auto_enabled':False})
    except PermissionError:return _json(h,{'error':'Sessão administrativa necessária.'},401)
    except Exception:return _json(h,{'error':'Não foi possível carregar a prospecção.'},500)

def update_leads(h):
    try:
        _require_admin(h,write=True)
        p=_read(h);action=_str(p.get('action',''),30)
        with _LOCK, contextlib.closing(_db()) as db, db:
            if action=='create':
                nome=_str(p.get('nome',''),120)
                categoria=_str(p.get('categoria','Outros'),50)
                cidade=_str(p.get('cidade',''),90)
                origem=_str(p.get('origem',''),150)
                telefone=_phone(p.get('telefone',''))
                if not nome or not cidade or not origem:raise ValueError('Informe empresa, cidade e fonte independente dos dados.')
                if categoria not in _CATEGORIES:categoria='Outros'
                place_id=_str(p.get('place_id',''),170)
                if place_id and not re.fullmatch(r'[A-Za-z0-9_\-:]{5,170}',place_id):raise ValueError('Place ID inválido.')
                instagram=_str(p.get('instagram',''),120)
                website=_str(p.get('website',''),250)
                notes=_str(p.get('observacoes',''),600)
                priority=int(p.get('prioridade',0))
                if priority not in (0,1,2):raise ValueError('Prioridade inválida.')
                if place_id and db.execute('SELECT id FROM leads WHERE place_id=?',(place_id,)).fetchone():
                    raise ValueError('Esse Place ID já está cadastrado.')
                if telefone and db.execute('SELECT id FROM leads WHERE telefone=?',(telefone,)).fetchone():
                    raise ValueError('Telefone já cadastrado. Evitamos contatos duplicados.')
                ident=secrets.token_hex(8);now=_utc()
                db.execute('''INSERT INTO leads
                    (id,nome,categoria,cidade,telefone,instagram,website,origem,place_id,observacoes,prioridade,criado,atualizado)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (ident,nome,categoria,cidade,telefone,instagram,website,origem,place_id,notes,priority,now,now))
                _event(db,ident,'CRIADO','Registro manual ou origem independente')
                return _json(h,{'ok':True,'id':ident})
            lead=_load(db,p.get('id'))
            if action=='status':
                st=_str(p.get('status',''),30)
                if st not in _STATUSES:raise ValueError('Status inválido.')
                db.execute('UPDATE leads SET status=?,atualizado=? WHERE id=?',(st,_utc(),lead['id']))
                _event(db,lead['id'],'STATUS',st)
            elif action=='consent':
                channel=_str(p.get('canal',''),20)
                if channel not in ('whatsapp','ligacao'):raise ValueError('Canal inválido.')
                permitted=p.get('permitido') is True
                proof=_str(p.get('fonte',''),180)
                if permitted and (not lead['telefone'] or len(proof)<12):
                    raise ValueError('Para autorizar contato, informe telefone e prova de consentimento com pelo menos 12 caracteres.')
                if lead['bloqueado'] and permitted:raise ValueError('Lead bloqueado: não reative contato sem revisão de oposição.')
                col='consent_whatsapp' if channel=='whatsapp' else 'consent_ligacao'
                other='consent_ligacao' if channel=='whatsapp' else 'consent_whatsapp'
                keep_other=bool(lead[other]) and not permitted
                dtval=_utc() if permitted else (lead['data_consentimento'] if keep_other else '')
                source=proof if permitted else (lead['fonte_consentimento'] if keep_other else '')
                db.execute(f'UPDATE leads SET {col}=?,fonte_consentimento=?,data_consentimento=?,atualizado=? WHERE id=?',
                           (int(permitted),source,dtval,_utc(),lead['id']))
                _event(db,lead['id'],'CONSENTIMENTO',channel+(': AUTORIZADO' if permitted else ': REVOGADO'))
            elif action=='optout':
                db.execute('UPDATE leads SET bloqueado=1,consent_whatsapp=0,consent_ligacao=0,atualizado=? WHERE id=?',(_utc(),lead['id']))
                _event(db,lead['id'],'OPOSICAO','Não entrar em contato')
            elif action=='activity':
                kind=_str(p.get('tipo',''),20)
                if kind not in ('WHATSAPP','LIGACAO','NOTA'):raise ValueError('Tipo inválido.')
                if lead['bloqueado']:raise ValueError('Lead bloqueado para contato.')
                if kind=='WHATSAPP' and not lead['consent_whatsapp']:raise ValueError('Sem autorização para WhatsApp.')
                if kind=='LIGACAO' and not lead['consent_ligacao']:raise ValueError('Sem autorização para ligação.')
                details=_str(p.get('detalhes',''),350)
                db.execute('UPDATE leads SET atualizado=? WHERE id=?',(_utc(),lead['id']))
                _event(db,lead['id'],kind,details)
            elif action=='delete':
                db.execute('DELETE FROM eventos WHERE lead_id=?',(lead['id'],))
                db.execute('DELETE FROM leads WHERE id=?',(lead['id'],))
            else:raise ValueError('Ação inválida.')
        return _json(h,{'ok':True})
    except PermissionError as e:return _json(h,{'error':str(e)},401)
    except (ValueError,LookupError) as e:return _json(h,{'error':str(e)},400)
    except Exception:return _json(h,{'error':'Operação não concluída.'},500)

def maps_search(h):
    """Pesquisa efêmera, com atribuição e sem persistência em CRM."""
    global _LAST_MAPS_SEARCH
    try:
        _require_admin(h,write=True)
        p=_read(h)
        text_query=_str(p.get('query',''),100)
        if len(text_query)<4:raise ValueError('Informe categoria e cidade para buscar.')
        key=os.getenv('GOOGLE_PLACES_API_KEY','').strip()
        if not key:raise ValueError('Configure GOOGLE_PLACES_API_KEY na Railway para habilitar busca (API pode cobrar por consulta).')
        with _LOCK:
            if time.monotonic()-_LAST_MAPS_SEARCH<12:raise ValueError('Aguarde alguns segundos entre pesquisas para controlar os custos.')
            _LAST_MAPS_SEARCH=time.monotonic()
        query={'textQuery':text_query,'pageSize':10,'languageCode':'pt-BR','regionCode':'BR'}
        body=json.dumps(query).encode()
        req=urllib.request.Request('https://places.googleapis.com/v1/places:searchText',data=body,
            headers={'Content-Type':'application/json','X-Goog-Api-Key':key,
                     'X-Goog-FieldMask':'places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.attributions'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=9) as response:raw=response.read(85000)
        except (urllib.error.URLError,TimeoutError):return _json(h,{'error':'Busca Google indisponível. Confira API/billing e tente mais tarde.'},502)
        result=json.loads(raw)
        items=[]
        for x in result.get('places',[])[:10]:
            if not isinstance(x,dict):continue
            items.append({'place_id':str(x.get('id',''))[:170],
                    'nome':str((x.get('displayName') or {}).get('text',''))[:130],
                    'endereco':str(x.get('formattedAddress',''))[:210],
                    'maps_url':str(x.get('googleMapsUri',''))[:500],
                    'attributions':[{'provider':str(a.get('provider',''))[:100],
                                     'uri':str(a.get('providerUri',''))[:300]}
                        for a in (x.get('attributions') or [])[:5] if isinstance(a,dict)]})
        return _json(h,{'ok':True,'results':items,'source':'Google Maps',
                'notice':'Dados apresentados apenas nesta consulta. Só o Place ID pode ser guardado; dados comerciais devem ter fonte independente.'})
    except PermissionError:return _json(h,{'error':'Sessão não autorizada.'},401)
    except ValueError as e:return _json(h,{'error':str(e)},400)
    except Exception:return _json(h,{'error':'Pesquisa não concluída.'},500)
