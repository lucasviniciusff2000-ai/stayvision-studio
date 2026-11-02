"""Safe, read-only fal.ai credit balance for the authenticated StayVision admin.

Requires a distinct FAL_BILLING_KEY with billing:usage:read. Does not use
FAL_KEY used for paid image inference and never returns credentials.
"""
from __future__ import annotations
import json
import math
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_URL = 'https://api.fal.ai/v1/account/billing?expand=credits'
_LOCK = threading.Lock()
_CACHE = {'time': 0.0, 'result': None}
_TTL = 120  # avoid hammering billing API when the admin refreshes the dashboard


def _json_reply(handler, payload, code=200):
    return handler._send(json.dumps(payload, ensure_ascii=False), code,
                         extra={'Cache-Control': 'no-store'})


def _fetch_balance():
    key = os.environ.get('FAL_BILLING_KEY', '').strip()
    if not key:
        return 503, {'ok': False, 'error': 'Configure FAL_BILLING_KEY (somente leitura) na Railway.'}
    req = Request(_URL, headers={
        'Authorization': 'Key ' + key,
        'Accept': 'application/json',
        'User-Agent': 'StayVisionBusinessBalance/1.0',
    }, method='GET')
    try:
        with urlopen(req, timeout=6) as resp:
            if resp.status != 200:
                return 503, {'ok': False, 'error': 'Falha na consulta de saldo da fal.ai.'}
            payload = json.loads(resp.read(64 * 1024))
        credits = payload.get('credits')
        if not isinstance(credits, dict):
            return 502, {'ok': False, 'error': 'A resposta da fal.ai não contém o saldo.'}
        balance = credits.get('current_balance')
        if isinstance(balance, bool) or not isinstance(balance, (int, float)) or not math.isfinite(balance):
            return 502, {'ok': False, 'error': 'Saldo da fal.ai retornado em formato inválido.'}
        currency = credits.get('currency')
        if currency != 'USD':
            return 502, {'ok': False, 'error': 'Moeda não reconhecida na resposta de saldo da fal.ai.'}
        return 200, {'ok': True, 'balance': balance, 'currency': 'USD',
                     'updated_at': int(time.time())}
    except HTTPError as exc:
        if exc.code in (401, 403):
            return 503, {'ok': False, 'error': 'Chave sem permissão billing:usage:read ou inválida.'}
        if exc.code == 429:
            return 503, {'ok': False, 'error': 'Limite de consultas da fal.ai. Tente mais tarde.'}
        return 503, {'ok': False, 'error': 'A fal.ai não respondeu à consulta de saldo.'}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError, TypeError):
        return 503, {'ok': False, 'error': 'Não foi possível consultar o saldo da fal.ai agora.'}


def admin_balance(handler):
    from admin_panel import authorized
    if not authorized(handler):
        return _json_reply(handler, {'ok': False, 'error': 'Acesso restrito ao operador.'}, 401)
    with _LOCK:
        now = time.monotonic()
        if _CACHE['result'] is None or now - _CACHE['time'] >= _TTL:
            _CACHE['result'] = _fetch_balance()
            _CACHE['time'] = time.monotonic()
        status, result = _CACHE['result']
    return _json_reply(handler, result, status)
