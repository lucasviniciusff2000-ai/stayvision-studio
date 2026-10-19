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


def gate(order_id=None):
    """Fail-closed; no published client or admin interface enables this gate."""
    mode = os.environ.get('STAYVISION_MP_CHECKOUT_MODE', 'locked').strip()
    allowed = os.environ.get('STAYVISION_MP_ALLOWED_ORDER_ID', '').strip()
    if mode != 'restricted' or not order_id or order_id != allowed:
        return False
    if os.environ.get('STAYVISION_MP_REAL_TEST_AUTHORIZATION', '') != 'EXPLICIT_SINGLE_ORDER_TEST':
        return False
    if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}', order_id):
        return False
    if not re.fullmatch(r'[0-9]{1,30}', os.environ.get('MP_PRODUCTION_COLLECTOR_ID', '')):
        return False
    if not os.environ.get('MP_PRODUCTION_ACCESS_TOKEN', '').strip():
        return False
    if not os.environ.get('MP_WEBHOOK_SECRET', '').strip():
        return False
    public_url=os.environ.get('STAYVISION_PUBLIC_URL','').strip()
    try:
        url=urllib.parse.urlsplit(public_url)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.path not in ('','/') or url.query or url.fragment:
            return False
    except ValueError:
        return False
    return True


def build_preference(order, public_url):
    oid=str(order['id'])
    if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',oid):
        raise CheckoutError('Pedido inválido.')
    if order.get('plan_code') != 'photo':
        raise CheckoutError('Apenas o plano Photo pode participar do teste restrito.')
    try:
        price=Decimal(str(order['price']))
    except (InvalidOperation,TypeError):
        raise CheckoutError('Preço inválido.') from None
    if not price.is_finite() or price != Decimal('49'):
        raise CheckoutError('O teste restrito está limitado a R$ 49 do plano Photo.')
    if order['payment_status'] not in ('nao_iniciado','pendente'):
        raise CheckoutError('O pedido não está elegível para novo checkout.')
    public_url=public_url.rstrip('/')
    if not public_url.startswith('https://'):
        raise CheckoutError('URL pública HTTPS obrigatória.')
    # Avoid embedding private tracking tokens or personal data in URLs sent to MP.
    return {
        'items':[{'id':'photo','title':'StayVision Photo - tratamento de fotografias',
                  'description':'Servico de apresentacao imobiliaria',
                  'quantity':1,'currency_id':'BRL','unit_price':float(price)}],
        'external_reference':oid,
        'back_urls':{
            'success':public_url+'/retorno?status=success',
            'failure':public_url+'/retorno?status=failure',
            'pending':public_url+'/retorno?status=pending',
        },
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
