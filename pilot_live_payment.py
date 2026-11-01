"""Pilot-only real payment experiment for LOCAL StayVision admin.
One permitted preference creation per installation; no commercial order payment or AI unlock.
No webhook/Internet deployment. No client-supplied amount or redirect URL.
"""
import datetime as dt
import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

_LOCK=threading.RLock()
JOB_RE=re.compile(r'^pedido-[0-9a-f]{16}$')
REFERENCE_RE=re.compile(r'^SV_LIVE_PILOT_[a-zA-Z0-9_\-]{8,90}$')
HOSTS={'www.mercadopago.com.br','www.mercadopago.com','mercadopago.com.br','mercadopago.com'}
STATUS_TERMINAL={'APROVADO_REAL','ESTORNADO','CONTESTADO'}


def _file():
    from commerce_flow import _store
    return _store()/'piloto_real_unico.json'

def _timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def _read_record():
    p=_file()
    try:
        d=json.loads(p.read_text(encoding='utf-8'))
        return d if isinstance(d,dict) else None
    except FileNotFoundError:return None

def _save(record):
    p=_file()
    tmp=p.with_suffix('.pending.tmp')
    tmp.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,p)

def enabled():
    # Even with a production token in the environment, pilot must be separately enabled.
    return os.environ.get('SV_LIVE_PILOT_ENABLED')=='1' and bool(os.environ.get('MP_LIVE_ACCESS_TOKEN'))

def configured():
    from admin_credentials import configured as admin_configured
    return enabled() and admin_configured()

def status_for_admin(job=None):
    state=_read_record()
    # Only show metadata; never credentials or stored checkout URL to unauthorized callers.
    if state and job and state.get('order_id')!=job:
        return {'enabled':configured(),'taken':True,'status':'RESERVADO_EM_OUTRO_PEDIDO'}
    if state:
        return {k:state.get(k) for k in ('order_id','status','created_utc','checked_utc','preference_id','payment_id','amount_brl','currency')} | {'enabled':configured(),'taken':True,'url':state.get('url') if state.get('status') in ('CHECKOUT_CRIADO','PENDENTE','EM_ANALISE') else None}
    return {'enabled':configured(),'taken':False,'status':'DISPONIVEL' if configured() else 'DESLIGADO'}

def _http_json(method,url,token,payload=None,key=None,timeout=15,transport=None):
    if transport:return transport(method,url,payload,key)
    data=None if payload is None else json.dumps(payload).encode('utf-8')
    headers={'Authorization':'Bearer '+token,'Accept':'application/json'}
    if payload is not None:headers['Content-Type']='application/json'
    if key:headers['X-Idempotency-Key']=key
    request=urllib.request.Request(url,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(request,timeout=timeout) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        raise ValueError('Mercado Pago retornou HTTP %s. Confira credencial, conta e permissões.'%e.code)
    except (urllib.error.URLError,TimeoutError):raise ValueError('Mercado Pago indisponível ou sem conexão. Não tente gerar outro checkout; consulte o painel.')

def create(job,token=None,transport=None):
    """Admin-authenticated wrapper calls this. The remote side may succeed despite timeout.
    Hence the local reservation is irreversible: at most one attempt per install.
    """
    if not JOB_RE.fullmatch(str(job)):raise ValueError('Pedido inválido.')
    from commerce_flow import _read as read_order
    read_order(job) # must exist before reserving live-payment pilot
    from admin_credentials import configured as admin_configured
    if not admin_configured():raise PermissionError('Configure usuário e senha do painel antes do piloto.')
    if os.environ.get('SV_LIVE_PILOT_ENABLED')!='1':raise PermissionError('Piloto real não foi habilitado pelo iniciador exclusivo.')
    access=token if token is not None else os.environ.get('MP_LIVE_ACCESS_TOKEN','')
    if not isinstance(access,str) or not access.strip():raise PermissionError('Credencial de PRODUÇÃO não fornecida.')
    if os.environ.get('STAYVISION_AI_MODE','off')!='off' or os.environ.get('STAYVISION_IMAGE_MODE','off')!='off':raise PermissionError('O piloto só funciona com IA completamente desligada.')
    with _LOCK:
        if _read_record() is not None:raise ValueError('O piloto de R$ 1,00 já foi reservado nesta instalação. Não são permitidas novas tentativas.')
        # Read-only preflight before permanently using the one-time quota.
        seller=_http_json('GET','https://api.mercadopago.com/users/me',access,transport=transport)
        seller_id=str(seller.get('id') or '') if isinstance(seller,dict) else ''
        if not seller_id.isdigit():raise ValueError('Não foi possível identificar o recebedor na conta Mercado Pago.')
        if seller.get('site_id') not in ('MLB',None):raise ValueError('Este piloto é exclusivo para conta Mercado Pago Brasil.')
        unique=secrets.token_hex(12).upper()
        ref='SV_LIVE_PILOT_'+unique
        idem='sv-live-pilot-'+unique
        record={'order_id':job,'status':'RESERVADO','created_utc':_timestamp(),
                'amount_brl':'1.00','currency':'BRL','external_reference':ref,'idempotency_key':idem,'collector_id':seller_id,
                'notice':'Cobrança PILOTO real separada do preço do plano e sem autorização de produção.'}
        _save(record) # persistent before network, safe across thread/process restart
        payload={'items':[{'id':'pilot-1brl','title':'StayVision - PILOTO ADMIN REAL R$ 1,00',
                'quantity':1,'currency_id':'BRL','unit_price':1.0}],
                'external_reference':ref,'metadata':{'stayvision_order':job,'stayvision_kind':'ONE_TIME_REAL_PILOT'}}
        try:
            result=_http_json('POST','https://api.mercadopago.com/checkout/preferences',access,payload,idem,transport=transport)
            url=result.get('init_point') if isinstance(result,dict) else None
            parsed=urlparse(url or '')
            if parsed.scheme!='https' or parsed.hostname not in HOSTS or 'sandbox' in (parsed.hostname or ''):
                raise ValueError('Resposta do checkout de PRODUÇÃO inválida. Não é seguro abrir o link.')
            pref=str(result.get('id') or '')
            collector=str(result.get('collector_id') or '')
            if not pref or collector!=seller_id:
                raise ValueError('Identidade do recebedor da preferência divergente. Piloto bloqueado.')
            record.update({'status':'CHECKOUT_CRIADO','preference_id':pref,'collector_id':collector,'url':url})
            _save(record)
            return status_for_admin(job)
        except Exception as e:
            record.update({'status':'INCERTO_NAO_REPETIR','error_type':type(e).__name__})
            _save(record)
            raise

def _fetch_payments(record,access,transport=None):
    ref=record['external_reference']
    query=urllib.parse.urlencode({'external_reference':ref,'sort':'date_created','criteria':'desc','limit':'20'})
    result=_http_json('GET','https://api.mercadopago.com/v1/payments/search?'+query,access,transport=transport)
    if not isinstance(result,dict) or not isinstance(result.get('results'),list):raise ValueError('Resposta inesperada do Mercado Pago.')
    verified=[]
    for candidate in result['results'][:20]:
        if not isinstance(candidate,dict):continue
        payment_id=str(candidate.get('id') or '')
        if not payment_id.isdigit():continue
        # Always retrieve each payment directly from provider, never trust redirects or browser statuses.
        p=_http_json('GET','https://api.mercadopago.com/v1/payments/'+payment_id,access,transport=transport)
        if not isinstance(p,dict):continue
        try:
            amount=Decimal(str(p.get('transaction_amount')))
        except Exception:continue
        if (str(p.get('external_reference'))!=ref or amount!=Decimal('1.00') or
            str(p.get('currency_id'))!='BRL' or str(p.get('collector_id'))!=record.get('collector_id') or
            str(p.get('id'))!=payment_id):continue
        verified.append((payment_id,str(p.get('status'))))
    return verified

def check(job,token=None,transport=None):
    with _LOCK:
        record=_read_record()
        if not record or record.get('order_id')!=job:raise ValueError('Esse pedido não possui piloto real.')
        if record.get('status')=='RESERVADO':raise ValueError('Checkout ainda reservado, sem preferência pronta. Não repita.')
        if not record.get('collector_id'):raise ValueError('Checkout sem identidade do recebedor; não é possível conciliar.')
        if os.environ.get('SV_LIVE_PILOT_ENABLED')!='1':raise PermissionError('Piloto desligado.')
        access=token if token is not None else os.environ.get('MP_LIVE_ACCESS_TOKEN','')
        if not access:raise PermissionError('Configure token de produção para consulta.')
        matches=_fetch_payments(record,access,transport)
        statuses={s for _,s in matches}
        prev=record.get('status')
        if 'charged_back' in statuses:now='CONTESTADO'
        elif 'refunded' in statuses:now='ESTORNADO'
        elif 'approved' in statuses:now='APROVADO_REAL'
        elif any(s in statuses for s in ('in_process','pending','authorized','in_mediation')):now='EM_ANALISE'
        elif matches:now='NAO_APROVADO'
        else:now='SEM_PAGAMENTO'
        # Do not downgrade approval on transient search gaps. Explicit reversal wins.
        if prev=='APROVADO_REAL' and now not in ('ESTORNADO','CONTESTADO'):
            now='APROVADO_REAL'
        record.update({'status':now,'checked_utc':_timestamp(),
                       'payment_id':next((i for i,s in matches if s=='approved'),next((i for i,s in matches if s in ('refunded','charged_back')),record.get('payment_id'))),
                       'found_payment_count':len(matches)})
        _save(record)
        return status_for_admin(job)

def admin_create(h):
    from admin_panel import _check,_json
    from commerce_flow import _body
    try:
        _check(h,modify=True)
        data=_body(h,1600)
        if data.get('confirm')!='AUTORIZO UM PILOTO REAL DE R$ 1,00':raise PermissionError('Confirmação explícita obrigatória.')
        _json(h,{'ok':True,'pilot':create(str(data.get('job') or ''))})
    except PermissionError as e:_json(h,{'error':str(e)},403)
    except (KeyError,ValueError,TypeError,FileNotFoundError) as e:_json(h,{'error':str(e)},400)
    except Exception as e:
        print('[pilot live] falha',type(e).__name__)
        _json(h,{'error':'Falha no Mercado Pago. Não tente novamente: veja o status do piloto.'},502)

def admin_check(h):
    from admin_panel import _check,_json
    from commerce_flow import _body
    try:
        _check(h,modify=True)
        data=_body(h,1600)
        _json(h,{'ok':True,'pilot':check(str(data.get('job') or ''))})
    except PermissionError as e:_json(h,{'error':str(e)},403)
    except (KeyError,ValueError,TypeError) as e:_json(h,{'error':str(e)},400)
    except Exception as e:
        print('[pilot check] falha',type(e).__name__)
        _json(h,{'error':'Falha na consulta ao Mercado Pago; nenhum pagamento foi confirmado.'},502)
