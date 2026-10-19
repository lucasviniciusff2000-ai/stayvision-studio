"""StayVision Stage 5: consulta SOMENTE LEITURA de pagamentos MP.

Nenhum endpoint deste módulo cria cobrança, altera pedido ou confirma pagamento.
"""
import json
import os
import re
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

API = 'https://api.mercadopago.com/v1/payments/'

class PaymentLookupUnavailable(Exception):
    """Falha temporária/API indisponível: o Mercado Pago pode tentar webhook novamente."""


def fetch_payment(payment_id):
    if not re.fullmatch(r'[0-9]{1,30}', str(payment_id)):
        raise ValueError('Identificador de pagamento inválido.')
    token = os.getenv('MP_PRODUCTION_ACCESS_TOKEN', '').strip()
    if not token:
        raise PaymentLookupUnavailable('Credencial de produção não configurada.')
    req = urllib.request.Request(
        API + str(payment_id), method='GET',
        headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=10) as response:
            obj=json.loads(response.read(256*1024))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise PaymentLookupUnavailable('Consulta do pagamento indisponível.') from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeError):
        raise PaymentLookupUnavailable('Consulta do pagamento indisponível.') from None
    if not isinstance(obj,dict) or str(obj.get('id',''))!=str(payment_id):
        raise PaymentLookupUnavailable('Resposta inválida ao consultar o pagamento.')
    return obj


def review_payment(payment, order, *, collector_id=''):
    """Retorna um resultado de auditoria; NUNCA libera entrega e NUNCA escreve no banco."""
    if payment is None: return 'pagamento_nao_encontrado'
    if payment.get('live_mode') is not True: return 'transacao_nao_produtiva'
    if payment.get('status') != 'approved': return 'pagamento_nao_aprovado'
    if payment.get('currency_id') != 'BRL': return 'moeda_divergente'
    if not order: return 'pedido_nao_localizado'
    if str(payment.get('external_reference','')) != str(order['id']): return 'referencia_divergente'
    try:
        expected=Decimal(str(order['price']))
        amount=Decimal(str(payment['transaction_amount']))
    except (InvalidOperation, TypeError, KeyError):
        return 'valor_divergente'
    if not amount.is_finite() or amount != expected or expected <= 0: return 'valor_divergente'
    if not re.fullmatch(r'[0-9]{1,30}',str(collector_id)):
        return 'id_vendedor_nao_configurado'
    if str(payment.get('collector_id','')) != str(collector_id):
        return 'vendedor_divergente'
    # A fase DEMO não cria preferências reais. Somente uma futura preferência
    # gerada pelo backend deve habilitar a associação de um pagamento a pedido.
    if not order.get('preference_id'):
        return 'pedido_sem_preferencia_propria'
    if str(payment.get('preference_id','')) != str(order['preference_id']):
        return 'preferencia_nao_comprovada'
    return 'aprovado_validado_sem_baixa'


def audit_summary(rows):
    """Usado pelo painel, sem expor comprador nem credenciais."""
    return {'verified_readonly':sum(r['result']=='aprovado_validado_sem_baixa' for r in rows),
            'ignored_or_rejected':sum(r['result']!='aprovado_validado_sem_baixa' for r in rows)}
