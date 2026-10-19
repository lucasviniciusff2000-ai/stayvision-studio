"""StayVision payment-readiness tools. No payment creation and no status mutations.

This module deliberately exposes READ-ONLY API access for validating Pix availability.
Production checkout, webhook handling, reconciliation and payouts are NOT enabled.
"""
import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

API = 'https://api.mercadopago.com'


class ReadinessError(ValueError):
    """Safe, user-facing API diagnostic error (never includes private credentials)."""


def _get_payment_methods():
    """Only read-only GET request, never create a payment or preference."""
    token = os.getenv('MP_PRODUCTION_ACCESS_TOKEN', '').strip()
    if not token:
        raise ReadinessError('Configure MP_PRODUCTION_ACCESS_TOKEN apenas nas variáveis privadas da Railway.')
    req = urllib.request.Request(
        API + '/v1/payment_methods',
        method='GET',
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = json.loads(response.read(2 * 1024 * 1024))
    except urllib.error.HTTPError as exc:
        raise ReadinessError('Mercado Pago recusou a consulta (HTTP %d). Confira a credencial de produção.' % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ReadinessError('Não foi possível consultar o Mercado Pago. Tente novamente mais tarde.') from None
    except (json.JSONDecodeError, UnicodeError, ValueError):
        raise ReadinessError('O Mercado Pago retornou um formato inesperado.') from None
    if not isinstance(payload, list):
        raise ReadinessError('O Mercado Pago retornou dados inesperados.')
    return payload


def pix_production_report():
    methods = _get_payment_methods()
    listed = any(isinstance(item, dict) and (
        str(item.get('id', '')).lower() == 'pix' or
        (str(item.get('payment_type_id', '')).lower() == 'bank_transfer' and
         'pix' in str(item.get('name', '')).lower())
    ) for item in methods)
    return {
        'environment': 'producao',
        'pix_listed': listed,
        'checkout_guaranteed': False,
        'charges_created': False,
        'checkout_enabled': False,
        'message': ('Pix consta nos meios listados pela API de produção. Isso não garante que apareça no checkout.'
                    if listed else
                    'Pix não consta nos meios listados para esta credencial. Verifique a habilitação com Mercado Pago.'),
    }


def config_report():
    url = os.getenv('STAYVISION_PUBLIC_URL', '')
    return {
        'production_token_configured': bool(os.getenv('MP_PRODUCTION_ACCESS_TOKEN', '').strip()),
        'webhook_secret_configured': bool(os.getenv('MP_WEBHOOK_SECRET', '').strip()),
        'public_https_url_configured': url.startswith('https://') and '/' not in url[len('https://'):].rstrip('/'),
        'checkout_enabled': False,
        'webhooks_enabled': False,
        'real_charges_possible': False,
        'mode': 'consulta_somente',
    }


def valid_webhook_signature(secret, signature, request_id, data_id, *, now_timestamp=None, window_seconds=300):
    """Offline signature validator for a future webhook endpoint, not an endpoint itself.

    See MP template: id:{data.id};request-id:{x-request-id};ts:{ts};
    The timestamp from the signature is in milliseconds in common MP examples.
    """
    if not all(isinstance(v, str) and v for v in (secret, signature, request_id, data_id)):
        return False
    if not re.fullmatch(r'\d{1,30}', data_id):
        return False
    values = {}
    for part in signature.split(','):
        key, sep, val = part.strip().partition('=')
        if sep and key not in values:
            values[key] = val
    ts, presented = values.get('ts', ''), values.get('v1', '')
    if not re.fullmatch(r'\d{9,17}', ts) or not re.fullmatch(r'[0-9a-fA-F]{64}', presented):
        return False
    value = int(ts)
    epoch = value / 1000 if value > 10**11 else value
    t = time.time() if now_timestamp is None else now_timestamp
    if abs(t - epoch) > window_seconds:
        return False
    manifest = f'id:{data_id.lower()};request-id:{request_id};ts:{ts};'
    expected = hmac.new(secret.encode('utf-8'), manifest.encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, presented.lower())


def verified_payment_fields(payment, order, *, collector_id=None):
    """Pure validation ONLY: does not mutate database or accept payment claims from a redirect.

    A future backend must independently GET /v1/payments/{id} with server-side credentials
    before passing that response here. Never trust the client's query parameters.
    """
    if not isinstance(payment, dict) or not isinstance(order, dict):
        return None
    if payment.get('status') != 'approved' or payment.get('live_mode') is not True:
        return None
    if payment.get('currency_id') != 'BRL' or str(payment.get('external_reference')) != str(order.get('id')):
        return None
    if collector_id is not None and str(payment.get('collector_id')) != str(collector_id):
        return None
    try:
        expected = Decimal(str(order['price']))
        received = Decimal(str(payment['transaction_amount']))
    except (KeyError, TypeError, InvalidOperation):
        return None
    if expected <= 0 or expected != received or not expected.is_finite():
        return None
    pid = str(payment.get('id', ''))
    if not re.fullmatch(r'\d{1,30}', pid):
        return None
    return {'payment_id': pid, 'payment_status': 'pago', 'amount': str(received)}
