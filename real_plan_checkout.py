"""Checkout commercial LOCAL lab: server-side catalogue and provider reconciliation.
Do NOT deploy the stdlib localhost server publicly. Live checkout is OFF by default.
Pilot R$1 is never linked or counted as payment for a commercial plan.
"""
import json,os,re,secrets,threading,urllib.parse
from decimal import Decimal
from datetime import datetime,timezone
from urllib.parse import urlparse
from pilot_live_payment import _http_json

LOCK=threading.RLock()
JOB_RE=re.compile(r'^pedido-[0-9a-f]{16}$')
PRICES={'fotos':Decimal('59.90'),'perfil':Decimal('149.90'),'vitrine':Decimal('249.90'),'premium':Decimal('399.90')}
PROD_HOSTS={'mercadopago.com.br','www.mercadopago.com.br','mercadopago.com','www.mercadopago.com'}
ONE_REAL=Decimal('1.00')

def pilot_mode():
 return os.environ.get('SV_ONE_REAL_E2E')=='1' and os.environ.get('SV_E2E_ONE_REAL_ACK')=='1'

def pilot_quota_path():
 from commerce_flow import _store
 return _store()/'e2e_r1_unico.json'

def checked_amount(state):
 chk=state.get('checkout_real') or {}
 if state.get('e2e_trial'):
  if chk.get('kind')!='E2E_ONE_REAL' or chk.get('amount_brl')!='1.00':raise ValueError('Identidade do piloto R$ 1 inconsistente.')
  return ONE_REAL
 return PRICES[state['plan']]


def enabled():
 return os.environ.get('SV_REAL_PLANS_ENABLED')=='1' and bool(os.environ.get('MP_LIVE_ACCESS_TOKEN'))
def now():return datetime.now(timezone.utc).isoformat()
def _access():
 if not enabled():raise PermissionError('Checkout real dos planos está desligado. Use o iniciador comercial autorizado.')
 access=os.environ.get('MP_LIVE_ACCESS_TOKEN','')
 if not access:raise PermissionError('Configure a credencial de produção.')
 return access

def _load(job):
 from commerce_flow import _read
 if not JOB_RE.fullmatch(str(job)):raise ValueError('Pedido inválido.')
 return _read(job)

def _save(state):
 from commerce_flow import _write
 _write(state['id'],state)

def _validate_url(value):
 u=urlparse(value or '')
 return u.scheme=='https' and u.hostname in PROD_HOSTS and u.username is None and u.password is None

def _seller(access,transport=None):
 d=_http_json('GET','https://api.mercadopago.com/users/me',access,transport=transport)
 sid=str(d.get('id') or '') if isinstance(d,dict) else ''
 if not sid.isdecimal() or d.get('site_id') not in ('MLB',None):raise ValueError('Conta Mercado Pago inválida para Brasil.')
 return sid

def create(job,token=None,transport=None):
 """Exactly one attempt for a unique order; irreversible reservation on uncertainty.
    Secret customer access token checked by caller, not accepted as order ID from browser.
 """
 from commerce_flow import _stamp
 with LOCK:
  state=_load(job)
  if state.get('payment')!='PENDENTE':raise ValueError('Pedido não está aguardando pagamento.')
  old=state.get('checkout_real') or {}
  if old:
   if old.get('status')=='PREFERENCIA_CRIADA' and _validate_url(old.get('url')):
    return {'url':old['url'],'amount_brl':old['amount_brl'],'environment':'REAL','reused':True}
   raise ValueError('Tentativa real já reservada. Confira no painel; não crie cobrança duplicada.')
  access=token if token is not None else _access()
  if not access:raise PermissionError('Sem token de produção.')
  plan=state['plan']
  if plan not in PRICES:raise ValueError('Plano não reconhecido.')
  pilot=pilot_mode()
  if state.get('e2e_trial') and not pilot:raise ValueError('Piloto real R$ 1 exige iniciador dedicado.')
  if pilot:
   if not state.get('e2e_trial') or state.get('session_mode')!='PILOTO_E2E_REAL_R1':
    raise ValueError('Apenas pedidos criados pelo iniciador piloto R$1 podem usar este checkout.')
   from premium_direct import _get,_read as production_read
   if plan!='fotos' or production_read(_get(job)).get('photos')!=1:
    raise ValueError('Piloto real R$ 1 aceita somente Fotos Business com UMA foto.')
   from path_safety import require_safe_output
   require_safe_output()
  from engine import PLANS
  seller=_seller(access,transport)
  if pilot:
   quota=pilot_quota_path()
   if quota.is_file():
    prior=json.loads(quota.read_text(encoding='utf8'))
    if prior.get('job')!=job:raise ValueError('Piloto real R$ 1 já foi reservado para outro pedido nesta instalação.')
   else:
    tmp=quota.with_suffix('.tmp')
    tmp.write_text(json.dumps({'job':job,'kind':'E2E_ONE_REAL','reserved_utc':now()}),encoding='utf8');tmp.replace(quota)
   state['e2e_trial']=True
  amount=ONE_REAL if pilot else PRICES[plan]
  reference='SV_PLAN_'+secrets.token_hex(14).upper()
  idem='sv-plan-'+secrets.token_hex(14)
  checkout={'status':'RESERVADA','amount_brl':str(amount),'currency':'BRL','reference':reference,'seller_id':seller,'idempotency_key':idem,'created_utc':now(), 'kind':'E2E_ONE_REAL' if pilot else 'REAL_PLAN'}
  state['checkout_real']=checkout;_save(state)
  payload={'items':[{'id':'sv-'+plan,'title':'StayVision - PILOTO REAL DE 1 FOTO (R$ 1)' if pilot else 'StayVision Business - '+PLANS[plan]['name'],'quantity':1,'currency_id':'BRL','unit_price':float(amount)}],
    'external_reference':reference,'metadata':{'stayvision_order':job,'stayvision_kind':'E2E_ONE_REAL' if pilot else 'REAL_PLAN','plan':plan}}
  try:
   result=_http_json('POST','https://api.mercadopago.com/checkout/preferences',access,payload,idem,transport=transport)
   url=result.get('init_point') if isinstance(result,dict) else None
   pref=str(result.get('id') or '') if isinstance(result,dict) else ''
   recv=str(result.get('collector_id') or '') if isinstance(result,dict) else ''
   if not _validate_url(url) or not pref or recv!=seller:raise ValueError('Resposta da preferência de produção inválida.')
   checkout.update(status='PREFERENCIA_CRIADA',url=url,preference_id=pref)
   state['checkout_real']=checkout;_save(state)
   return {'url':url,'amount_brl':str(amount),'environment':'REAL','pilot':pilot,'reused':False}
  except Exception:
   # Network may have accepted the preference. Deliberately no retry.
   checkout['status']='INCERTO_SEM_REPETIR';state['checkout_real']=checkout;_save(state)
   raise

def _find_valid(state,access,transport=None):
 chk=state.get('checkout_real') or {}
 ref=chk.get('reference');sid=chk.get('seller_id')
 if not ref or not sid or chk.get('status') in ('RESERVADA','INCERTO_SEM_REPETIR'):
  raise ValueError('Checkout ainda não conciliável; revise a tentativa reservada.')
 q=urllib.parse.urlencode({'external_reference':ref,'limit':'30','sort':'date_created','criteria':'desc'})
 data=_http_json('GET','https://api.mercadopago.com/v1/payments/search?'+q,access,transport=transport)
 if not isinstance(data,dict) or not isinstance(data.get('results'),list):raise ValueError('Resposta de pesquisa inesperada.')
 results=[]
 for summary in data['results'][:30]:
  pid=str(summary.get('id') or '') if isinstance(summary,dict) else ''
  if not pid.isdecimal():continue
  p=_http_json('GET','https://api.mercadopago.com/v1/payments/'+pid,access,transport=transport)
  if not isinstance(p,dict):continue
  try:amount=Decimal(str(p.get('transaction_amount')))
  except Exception:continue
  if (str(p.get('id'))!=pid or str(p.get('external_reference'))!=ref or
      str(p.get('collector_id'))!=sid or str(p.get('currency_id'))!='BRL' or
      amount!=checked_amount(state)):continue
  # Exclude sandbox records even if another identifier happened to match.
  if p.get('live_mode') is False or (state.get('e2e_trial') and p.get('live_mode') is not True):continue
  # When provider returns the preference ID, require equality.
  meta=p.get('metadata') if isinstance(p.get('metadata'),dict) else {}
  p_preference=p.get('preference_id') or meta.get('preference_id')
  if p_preference and str(p_preference)!=str(chk.get('preference_id')):continue
  results.append({'id':pid,'status':str(p.get('status') or '')})
 return results

def reconcile(job,token=None,transport=None):
 access=token if token is not None else _access()
 # Hold one lock across read/verification/write so status remains consistent and idempotent.
 with LOCK:
  state=_load(job)
  chk=state.get('checkout_real') or {}
  if not chk or chk.get('status') in ('RESERVADA','INCERTO_SEM_REPETIR'):
   raise ValueError('Pedido sem checkout real conciliável.')
  matches=_find_valid(state,access,transport)
  statuses={x['status'] for x in matches}
  previous=state.get('payment')
  if 'charged_back' in statuses:new='CONTESTADO_PROVEDOR'
  elif 'refunded' in statuses:new='ESTORNADO_PROVEDOR'
  elif 'approved' in statuses:new='VERIFICADO_PROVEDOR'
  elif statuses & {'pending','in_process','authorized','in_mediation'}:new='PENDENTE'
  else:new='PENDENTE'
  # Provider search can be eventually consistent: no downgrade on empty results.
  if previous in ('VERIFICADO_PROVEDOR','ESTORNADO_PROVEDOR','CONTESTADO_PROVEDOR') and not statuses:
   new=previous
  if previous in ('ESTORNADO_PROVEDOR','CONTESTADO_PROVEDOR') and new=='VERIFICADO_PROVEDOR':new=previous
  chk['last_check_utc']=now();chk['result_status']=new;chk['matched_count']=len(matches)
  if new in ('VERIFICADO_PROVEDOR','ESTORNADO_PROVEDOR','CONTESTADO_PROVEDOR'):
   payment=next((x for x in matches if x['status'] in ('charged_back','refunded','approved')),None)
   if payment:chk['payment_id']=payment['id']
   if new=='VERIFICADO_PROVEDOR':
    state['paid_amount_brl']=str(checked_amount(state))
    state['payment_source']='MERCADO_PAGO_E2E_R1_VERIFICADO' if state.get('e2e_trial') else 'MERCADO_PAGO_API_VERIFICADO'
   else:
    state['payment_source']='MERCADO_PAGO_API_REVERSAO'
  if previous!=new:
   state['payment']=new
   state['payment_updated_utc']=now()
  state['checkout_real']=chk;_save(state)
  if new in ('ESTORNADO_PROVEDOR','CONTESTADO_PROVEDOR') and previous!=new:
   try:
    from delivery_mobile import revoke
    revoke(job)
   except Exception:pass
  return {'status':new,'payment_id':chk.get('payment_id'), 'amount_brl':chk.get('amount_brl'),'checked_utc':chk['last_check_utc']}

def customer_checkout(h):
 from commerce_flow import _body,_by_token,_send
 try:
  data=_body(h,2048)
  state=_by_token(str(data.get('customer_token') or ''))
  r=create(state['id'])
  _send(h,{'ok':True,'checkout_url':r['url'],'amount_brl':r['amount_brl'],'environment':'REAL'})
 except (PermissionError,ValueError,KeyError,FileNotFoundError) as e:_send(h,{'error':str(e)},400)
 except Exception as e:
  print('[checkout real] falha',type(e).__name__)
  _send(h,{'error':'Checkout indisponível. Pedido preservado; contate o suporte antes de tentar novamente.'},502)

def customer_check(h):
 from commerce_flow import _body,_by_token,_send
 try:
  data=_body(h,2048)
  state=_by_token(str(data.get('customer_token') or ''))
  r=reconcile(state['id'])
  _send(h,{'ok':True,**r})
 except (PermissionError,ValueError,KeyError,FileNotFoundError) as e:_send(h,{'error':str(e)},400)
 except Exception as e:
  print('[consulta real]',type(e).__name__)
  _send(h,{'error':'Falha temporária na consulta ao Mercado Pago.'},502)

def admin_check(h):
 from admin_panel import _check,_read_json,_json
 try:
  _check(h,modify=True)
  data=_read_json(h,3000)
  r=reconcile(str(data.get('job','')))
  _json(h,{'ok':True,**r})
 except (ValueError,PermissionError,FileNotFoundError) as e:_json(h,{'error':str(e)},400)
 except Exception:_json(h,{'error':'Falha temporária na consulta.'},502)

def poll_once():
 """Read-only provider reconciliation, no production calls; idempotent and bounded."""
 if not enabled():return 0
 from commerce_flow import _store
 done=0
 for f in sorted(_store().glob('pedido-*.json')):
  try:
   state=json.loads(f.read_text(encoding='utf-8'))
   chk=state.get('checkout_real') or {}
   if chk.get('status')!='PREFERENCIA_CRIADA':continue
   if state.get('payment') in ('ESTORNADO_PROVEDOR','CONTESTADO_PROVEDOR'):continue
   reconcile(state['id']);done+=1
  except Exception as e:
   print('[MP live poll] pedido sem confirmação:',type(e).__name__)
 return done

def start_background():
 if not enabled():return
 def worker():
  import time
  while True:
   try:poll_once()
   except Exception as e:print('[MP live poll] erro:',type(e).__name__)
   time.sleep(30)
 threading.Thread(target=worker,daemon=True,name='stayvision-real-reconcile').start()
