"""StayVision Checkout Pro production bridge. ALL write actions are DENIED by default.

This module must never run an actual payment unless a separate explicit operator
change has enabled ONE whitelisted order. Only the backend holds API credentials.
"""
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from seller_identity import require_seller_identity, SellerIdentityError
from decimal import Decimal, InvalidOperation

API = 'https://api.mercadopago.com/checkout/preferences'

class CheckoutError(ValueError):
    pass


def seller_config_ready():
    if not re.fullmatch(r'[0-9]{1,30}', os.environ.get('MP_PRODUCTION_COLLECTOR_ID', '')):
        return False
    if not os.environ.get('MP_PRODUCTION_ACCESS_TOKEN', '').strip():
        return False
    if not os.environ.get('MP_WEBHOOK_SECRET', '').strip():
        return False
    public_url = os.environ.get('STAYVISION_PUBLIC_URL','').strip()
    try:
        u = urllib.parse.urlsplit(public_url)
        return (u.scheme == 'https' and bool(u.hostname) and not u.username
                and not u.password and u.path in ('','/') and not u.query and not u.fragment)
    except ValueError:
        return False


def public_sales_ready():
    # Two independent, deliberate approvals. Never enabled by a code deployment.
    return (os.environ.get('STAYVISION_MP_CHECKOUT_MODE','locked') == 'public'
            and os.environ.get('STAYVISION_MP_PUBLIC_LAUNCH','') == 'I_AUTHORIZE_PUBLIC_SALES'
            and os.environ.get('STAYVISION_MP_AUTO_CONFIRM','0') == '1'
            and seller_config_ready())


def gate(order_id=None):
    """Restrict writes to a single explicit test or fully launched public sales."""
    if not order_id or not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',order_id):
        return False
    if not seller_config_ready():
        return False
    if public_sales_ready():
        return True
    return (os.environ.get('STAYVISION_MP_CHECKOUT_MODE','locked') == 'restricted'
            and order_id == os.environ.get('STAYVISION_MP_ALLOWED_ORDER_ID','')
            and os.environ.get('STAYVISION_MP_REAL_TEST_AUTHORIZATION','') == 'EXPLICIT_SINGLE_ORDER_TEST')


def build_preference(order,public_url):
    """Build a single-payment Checkout Pro preference; never a subscription."""
    oid=str(order['id'])
    if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',oid):
        raise CheckoutError('Pedido inválido.')
    code=str(order.get('plan_code',''))
    if code not in ('photo','video','partner'):
        raise CheckoutError('Plano inválido.')
    try:
        price=Decimal(str(order['price']))
    except (InvalidOperation,TypeError):
        raise CheckoutError('Preço inválido.') from None
    if not price.is_finite() or price<=0 or price>Decimal('100000') or price!=price.to_integral_value():
        raise CheckoutError('Preço inválido.')
    # Restricted mode is an approved R$49 Photo pilot ONLY.
    if not public_sales_ready() and (code!='photo' or price!=Decimal('49')):
        raise CheckoutError('Modo restrito: apenas Photo R$ 49.')
    if order['payment_status'] not in ('nao_iniciado','pendente'):
        raise CheckoutError('O pedido não está elegível para novo checkout.')
    u=urllib.parse.urlsplit(public_url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
        raise CheckoutError('URL pública HTTPS obrigatória.')
    public_url=public_url.rstrip('/')
    labels={'photo':'Tratamento de fotografias','video':'Edicao de video imobiliario',
            'partner':'Pacote de servicos - pagamento avulso'}
    return {
        'items':[{'id':code,'title':'StayVision '+code.capitalize()+' - '+labels[code],
                  'description':'Servico digital imobiliario. Pagamento unico.',
                  'quantity':1,'currency_id':'BRL','unit_price':float(price)}],
        'external_reference':oid,
        'back_urls':{'success':public_url+'/retorno?status=success',
                     'failure':public_url+'/retorno?status=failure',
                     'pending':public_url+'/retorno?status=pending'},
        'auto_return':'approved',
        'notification_url':public_url+'/api/mp/webhook',
        'statement_descriptor':'STAYVISION',
    }


def trusted_checkout_url(url):
    if not isinstance(url,str): return False
    try:
        u=urllib.parse.urlsplit(url)
        return (u.scheme=='https' and not u.username and not u.password and
                u.hostname in ('mercadopago.com.br','www.mercadopago.com.br') and
                not u.path.startswith('//'))
    except (TypeError,ValueError):
        return False


def create_preference(order, *, idempotency_key):
    """Network-writing function. Caller MUST check gate and idempotent DB reservation."""
    if not gate(order['id']):
        raise CheckoutError('Checkout real está bloqueado.')
    try:
        require_seller_identity()
    except SellerIdentityError as exc:
        raise CheckoutError(str(exc)) from None
    payload=build_preference(order,os.environ['STAYVISION_PUBLIC_URL'])
    key=str(idempotency_key)
    if not re.fullmatch(r'[0-9a-f]{32,64}',key):
        raise CheckoutError('Chave de idempotência inválida.')
    token=os.environ['MP_PRODUCTION_ACCESS_TOKEN'].strip()
    req=urllib.request.Request(API,method='POST',data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
                 'Accept':'application/json','X-Idempotency-Key':key})
    try:
        with urllib.request.urlopen(req,timeout=20) as response:
            result=json.loads(response.read(256*1024))
    except urllib.error.HTTPError as exc:
        raise CheckoutError('Mercado Pago recusou criar a preferência (HTTP %d).'%exc.code) from None
    except (urllib.error.URLError,TimeoutError,OSError,ValueError,UnicodeError):
        raise CheckoutError('A preferência pode ter sido criada, mas não foi confirmada. Não tente novamente: revise o pedido com suporte.') from None
    if not isinstance(result,dict):
        raise CheckoutError('Resposta inválida do Mercado Pago: não repetir automaticamente.')
    pref=str(result.get('id',''))
    url=result.get('init_point','')
    if not pref or len(pref)>150 or not re.fullmatch(r'[a-zA-Z0-9-]+',pref) or not trusted_checkout_url(url):
        raise CheckoutError('Resposta de preferência não verificável: não repetir automaticamente.')
    return {'preference_id':pref,'checkout_url':url}
