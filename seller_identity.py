"""Etapa 8: verificação SOMENTE LEITURA do proprietário do token Mercado Pago.

Consulta documentada GET /users/me via api.mercadolibre.com.
Não registra cartões, não cria preferência, não inicia cobranças.
"""
import json
import os
import re
import urllib.error
import urllib.request

IDENTITY_URL = 'https://api.mercadolibre.com/users/me'

class SellerIdentityError(ValueError):
    pass


def check_seller_identity(*, show_full_id=False):
    token = os.getenv('MP_PRODUCTION_ACCESS_TOKEN', '').strip()
    expected = os.getenv('MP_PRODUCTION_COLLECTOR_ID', '').strip()
    if not token:
        raise SellerIdentityError('Access Token de produção não configurado.')
    if not re.fullmatch(r'[0-9]{1,30}', expected):
        raise SellerIdentityError('ID do vendedor não configurado ou inválido.')
    req = urllib.request.Request(IDENTITY_URL, method='GET', headers={
        'Authorization':'Bearer '+token, 'Accept':'application/json'
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read(65536))
    except urllib.error.HTTPError as exc:
        raise SellerIdentityError('O Mercado Pago recusou a identificação do vendedor (HTTP %d). Nenhuma cobrança criada.' % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError):
        raise SellerIdentityError('Não foi possível confirmar o proprietário do token. Checkout permanece bloqueado.') from None
    if not isinstance(data, dict) or not re.fullmatch(r'[0-9]{1,30}', str(data.get('id',''))):
        raise SellerIdentityError('Resposta de identificação inesperada. Checkout permanece bloqueado.')
    actual = str(data['id'])
    match = actual == expected
    result = {'verified':match,
            'status':'vendedor_confirmado' if match else 'vendedor_divergente',
            'configured_id_suffix':expected[-4:], 'token_owner_id_suffix':actual[-4:],
            'read_only':True,'preference_created':False,'payment_created':False,
            'checkout_enabled':False,
            'message':('Identidade confirmada: o ID configurado pertence à conta identificada pelo token de produção.'
                       if match else
                       'DIVERGÊNCIA: o ID configurado não corresponde à conta identificada pelo token. Não desbloqueie o checkout.')}
    # Somente a rota administrativa explicita solicita este identificador completo.
    # O token e quaisquer dados pessoais nunca entram na resposta.
    if show_full_id:
        result['token_owner_id_full'] = actual
    return result


def require_seller_identity():
    """Fail closed immediately before a real preference attempt."""
    report=check_seller_identity()
    if not report['verified']:
        raise SellerIdentityError('ID do vendedor diverge da conta de produção. Nenhuma preferência criada.')
    return True
