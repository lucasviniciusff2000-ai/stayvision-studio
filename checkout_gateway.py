"""Checkout Pro laboratory: create test preferences only; no payment confirmation.
Localhost only. Never deploy this endpoint publicly. No production payments or AI unlock.
"""
import json, os, re, threading, urllib.request, urllib.error
from decimal import Decimal
from urllib.parse import urlparse

class CheckoutNotConfigured(RuntimeError): pass

# Valores inteiros dos planos SOMENTE em sandbox. Nenhuma cobrança real.
from real_plan_checkout import PRICES as SANDBOX_PRICES
_SANDBOX_LOCK=threading.RLock()


def make_preference(job, plan, title, token=None, transport=None, return_path=None):
    access=token if token is not None else os.environ.get('MP_TEST_ACCESS_TOKEN','')
    if not access or not access.startswith('APP_USR-'):
        raise CheckoutNotConfigured('Configure MP_TEST_ACCESS_TOKEN com a credencial DE TESTE. Não utilize credencial de produção.')
    if not re.fullmatch(r'pedido-[0-9a-f]{16}',job): raise ValueError('Pedido inválido')
    if plan not in ('fotos','perfil','vitrine','premium'): raise ValueError('Plano inválido')
    # Preço integral fixado no servidor; cliente não escolhe o valor.
    amount=SANDBOX_PRICES[plan]
    payload={'items':[{'id':plan,'title':'Teste StayVision - '+title,'quantity':1,'currency_id':'BRL','unit_price':float(amount)}],
             'external_reference':'SV_TEST_'+job,'metadata':{'stayvision_order':job,'stayvision_environment':'TEST'}}
    # Return navigation is optional: a local return cannot verify the payment.
    # This is navigation only, never a paid-status signal.
    if return_path and re.fullmatch(r'/acompanhar/[A-Za-z0-9_-]{43}',return_path):
        root='http://127.0.0.1:8786'
        payload['back_urls']={k:root+return_path for k in ('success','pending','failure')}
    body=json.dumps(payload).encode('utf-8')
    if transport:
        result=transport(payload,access)
    else:
        request=urllib.request.Request('https://api.mercadopago.com/checkout/preferences',data=body,
            headers={'Authorization':'Bearer '+access,'Content-Type':'application/json','X-Idempotency-Key':'stayvision-test-'+job},method='POST')
        try:
            with urllib.request.urlopen(request,timeout=18) as resp: result=json.load(resp)
        except urllib.error.HTTPError as e:
            raise CheckoutNotConfigured('Mercado Pago recusou criar a preferência de teste (HTTP %s). Confira as credenciais de teste.'%e.code)
        except (urllib.error.URLError,TimeoutError):
            raise CheckoutNotConfigured('Não foi possível acessar o Mercado Pago. Confira sua conexão.')
    url=result.get('sandbox_init_point')
    # Never use a live init_point or accept untrusted redirects.
    if not isinstance(url,str) or urlparse(url).scheme!='https' or urlparse(url).hostname not in ('sandbox.mercadopago.com.br','sandbox.mercadopago.com'):
        raise CheckoutNotConfigured('Mercado Pago não retornou uma URL de sandbox segura. Operação cancelada.')
    return {'url':url,'preference_id':str(result.get('id','')),'amount':str(amount),'currency':'BRL','environment':'TEST_ONLY'}


def customer_checkout(h):
    from commerce_flow import _body,_by_token,_send,_path,_write
    try:
        data=_body(h,2048)
        secret=str(data.get('customer_token') or '')
        state=_by_token(secret)
        if state.get('payment')!='PENDENTE': raise ValueError('Pedido não está aguardando pagamento.')
        from engine import PLANS
        plan=state['plan']; title=PLANS[plan]['name']
        # An optional preference cache is intentionally not persisted until API succeeds.
        item=make_preference(state['id'],plan,title,return_path='/acompanhar/'+secret)
        with _SANDBOX_LOCK:
            state['checkout_test']={'preference_id':item['preference_id'],'amount_brl':item['amount'],'status':'PREFERENCIA_TESTE_CRIADA'}
            _write(state['id'],state)
        _send(h,{'ok':True,'sandbox_url':item['url'],'amount_brl':item['amount'],'warning':'Somente sandbox. Sem cobrança real, faturamento ou IA paga.'})
    except (CheckoutNotConfigured,ValueError,KeyError,FileNotFoundError,PermissionError) as e:
        _send(h,{'error':str(e)},400)
    except Exception as e:
        print('[checkout sandbox]',type(e).__name__)
        _send(h,{'error':'Falha ao preparar checkout de teste; pagamento não foi registrado.'},502)


def search_test_payment(job, preference_id, token=None, transport=None, amount_brl=None):
    """Read-only sandbox reconciliation. Never confirms a commercial payment."""
    import urllib.parse
    access = token if token is not None else os.environ.get('MP_TEST_ACCESS_TOKEN','')
    if not access.startswith('APP_USR-'): raise CheckoutNotConfigured('Credencial de TESTE não configurada.')
    if not re.fullmatch(r'pedido-[0-9a-f]{16}',job): raise ValueError('Pedido inválido.')
    if not isinstance(preference_id,str) or len(preference_id)>130 or not re.fullmatch(r'[A-Za-z0-9-]+',preference_id):
        raise ValueError('Preferência inválida.')
    if amount_brl is None:
        from commerce_flow import _read
        amount_brl=(_read(job).get('checkout_test') or {}).get('amount_brl','1.00')
    try:expected=Decimal(str(amount_brl))
    except Exception:raise ValueError('Valor de teste inválido.')
    if expected<=0 or expected>Decimal('399.90'):raise ValueError('Valor de teste fora do catálogo.')
    query={'external_reference':'SV_TEST_'+job,'sort':'date_created','criteria':'desc','limit':'50'}
    if transport: result=transport(query,access)
    else:
        url='https://api.mercadopago.com/v1/payments/search?'+urllib.parse.urlencode(query)
        request=urllib.request.Request(url,headers={'Authorization':'Bearer '+access,'Accept':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=15) as resp:result=json.load(resp)
        except urllib.error.HTTPError as e:raise CheckoutNotConfigured('Consulta ao Mercado Pago falhou (HTTP %s).'%e.code)
        except (urllib.error.URLError,TimeoutError):raise CheckoutNotConfigured('Não foi possível consultar Mercado Pago.')
    if not isinstance(result,dict) or not isinstance(result.get('results'),list):raise CheckoutNotConfigured('Resposta de pagamento inesperada.')
    matches=[]
    for p in result['results']:
        if not isinstance(p,dict):continue
        if str(p.get('external_reference'))!='SV_TEST_'+job:continue
        if str(p.get('currency_id'))!='BRL':continue
        try:amount=Decimal(str(p.get('transaction_amount')))
        except Exception:continue
        if amount!=expected:continue
        if p.get('live_mode') is True:continue  # jamais classificar transação real como sandbox
        # Some MP payments include a preference ID under metadata, others do not.
        # External reference + amount are not enough to establish commercial settlement.
        matches.append({'id':str(p.get('id','')),'status':str(p.get('status',''))})
    states=[p['status'] for p in matches]
    if 'approved' in states:status='APROVADO_SANDBOX'
    elif any(x in states for x in ('pending','in_process','authorized')):status='PENDENTE_SANDBOX'
    elif any(x in states for x in ('rejected','cancelled','refunded','charged_back')):status='NAO_APROVADO_SANDBOX'
    else:status='SEM_PAGAMENTO'
    return {'status':status,'matched_count':len(matches),'sandbox_only':True}


def verify_order(job,token=None,transport=None):
    """Confirma SOMENTE estado de sandbox. Nunca gera faturamento/produção."""
    from commerce_flow import _read,_write,_stamp
    with _SANDBOX_LOCK:
        state=_read(job)
        chk=state.get('checkout_test') or {}
        if not chk.get('preference_id'):raise ValueError('Crie primeiro o checkout de teste.')
        if state.get('payment') not in ('PENDENTE','SANDBOX_APROVADO'):
            return {'status':'OUTRO_PAGAMENTO','matched_count':0,'sandbox_only':True}
        outcome=search_test_payment(job,str(chk['preference_id']),token=token,transport=transport,amount_brl=chk.get('amount_brl','1.00'))
        checkout=dict(chk)
        checkout['last_check_utc']=_stamp()
        checkout['status']=outcome['status']
        checkout['matched_count']=outcome['matched_count']
        state['checkout_test']=checkout
        if outcome['status']=='APROVADO_SANDBOX':
            state['payment']='SANDBOX_APROVADO'
            state['payment_source']='MERCADO_PAGO_SANDBOX_QUERY'
            state['payment_updated_utc']=checkout['last_check_utc']
        _write(job,state)
        return outcome


def poll_once(token=None,transport=None,max_orders=12):
    """Consulta pendências em sandbox; nunca usa credencial de produção."""
    from commerce_flow import _store
    from real_plan_checkout import enabled
    if enabled():return 0  # ambiente comercial não mistura sandbox no mesmo processo
    access=token if token is not None else os.environ.get('MP_TEST_ACCESS_TOKEN','')
    if not access.startswith('APP_USR-'):return 0
    completed=0;scanned=0
    for file in sorted(_store().glob('pedido-*.json'),key=lambda x:x.stat().st_mtime):
        if scanned>=max_orders:break
        try:
            state=json.loads(file.read_text(encoding='utf-8'))
            if state.get('payment')!='PENDENTE':continue
            checkout=state.get('checkout_test') or {}
            if not checkout.get('preference_id'):continue
            scanned+=1
            result=verify_order(state['id'],token=access,transport=transport)
            if result['status']=='APROVADO_SANDBOX':completed+=1
        except Exception as e:
            print('[sandbox auto] consulta adiada:',type(e).__name__)
    return completed


def start_background():
    if not os.environ.get('MP_TEST_ACCESS_TOKEN','').startswith('APP_USR-'):return
    if __import__('real_plan_checkout').enabled():return
    def worker():
        import time
        while True:
            try:poll_once()
            except Exception as e:print('[sandbox auto] falha:',type(e).__name__)
            time.sleep(30)
    threading.Thread(target=worker,daemon=True,name='stayvision-sandbox-reconcile').start()


def customer_verify(h):
    from commerce_flow import _body,_by_token,_send
    try:
        data=_body(h,2048)
        state=_by_token(str(data.get('customer_token') or ''))
        outcome=verify_order(state['id'])
        _send(h,{'ok':True,**outcome,'note':'Confirmação somente sandbox, sem produção ou faturamento real.'})
    except (CheckoutNotConfigured,ValueError,KeyError,FileNotFoundError,PermissionError) as e:_send(h,{'error':str(e)},400)
    except Exception as e:
        print('[mp reconciliation sandbox]',type(e).__name__)
        _send(h,{'error':'Não foi possível consultar o pagamento de teste.'},502)
