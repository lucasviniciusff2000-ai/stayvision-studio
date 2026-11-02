"""V3.37: fail-closed payment-entry capacity check.

Not a spending cap at fal.ai. Only checks funding + queued reservations before
creating a NEW Mercado Pago preference. Does not charge or invoke generation.
Requires single Railway worker/replica. Existing checkout links may remain payable.
"""
from __future__ import annotations
import json
import os
from decimal import Decimal, InvalidOperation

DONE_STATUSES = {'REVISAO_NECESSARIA','INTERROMPIDO_SEM_REPETICAO',
                 'CONCLUIDO','CONCLUIDA','CONCLUIDA_TESTE','ENTREGUE'}
CHECKOUT_STATUSES = {'RESERVADA','PREFERENCIA_CRIADA','INCERTO_SEM_REPETIR'}


def _money(name, minimum, maximum):
    val = os.environ.get(name, '').strip()
    try:
        number = Decimal(val)
        if not number.is_finite() or not minimum <= number <= maximum:
            raise ValueError()
        return number
    except (InvalidOperation, ValueError):
        raise PermissionError('Checkout temporariamente indisponível: configure o orçamento de IA no painel de hospedagem.')


def _attempts(job):
    from premium_direct import _get, _read
    attempt = _read(_get(job)).get('expected_attempts')
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 40:
        raise PermissionError('Checkout temporariamente indisponível: quantidade de edições inválida.')
    return attempt


def _commitments(excluding):
    from commerce_flow import _store
    from premium_direct import _get, _read
    used = 0
    for p in _store().glob('pedido-*.json'):
        order = json.loads(p.read_text(encoding='utf-8'))
        job = order.get('id')
        if job == excluding:
            continue
        checkout = order.get('checkout_real') or {}
        if checkout.get('status') not in CHECKOUT_STATUSES:
            continue
        if order.get('payment') in ('ESTORNADO_PROVEDOR','CONTESTADO_PROVEDOR'):
            continue
        production = _read(_get(job))
        if production.get('status') in DONE_STATUSES:
            continue
        # Reserve the entire pending order until production has reached a terminal
        # state. This also accounts for someone paying an existing checkout later.
        used += _attempts(job)
    return used


def _auto_budget_remaining():
    from commerce_flow import _store
    text = os.environ.get('SV_AUTO_AI_BUDGET_MAX_CALLS','')
    if not text.isdecimal():
        raise PermissionError('Checkout indisponível: limite de produção não configurado.')
    limit = int(text)
    if limit < 1 or limit > 200:
        raise PermissionError('Checkout indisponível: limite de produção inválido.')
    file = _store() / 'auto_ia_budget.json'
    ledger = json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {'reserved':{}}
    reserved = ledger.get('reserved')
    if not isinstance(reserved, dict):
        raise PermissionError('Checkout indisponível: histórico de produção inválido.')
    total = sum(int(n) for n in reserved.values())
    if total < 0 or total > 200000:
        raise PermissionError('Checkout indisponível: histórico de produção inválido.')
    # Reservations for accepted but unpaid orders must also fit the hard queue
    # budget; avoid counting paid orders already included in the queue ledger.
    committed_not_counted = 0
    from commerce_flow import _store
    for file in _store().glob('pedido-*.json'):
        order = json.loads(file.read_text(encoding='utf8'))
        job = order.get('id')
        if job in reserved:continue
        chk = order.get('checkout_real') or {}
        if chk.get('status') not in CHECKOUT_STATUSES:continue
        if order.get('payment') in ('ESTORNADO_PROVEDOR','CONTESTADO_PROVEDOR'):continue
        from premium_direct import _get, _read
        if _read(_get(job)).get('status') in DONE_STATUSES:continue
        committed_not_counted += _attempts(job)
    return limit - total - committed_not_counted


def require_checkout_capacity(job, state):
    # An operator must explicitly set a conservative budget per image call.
    # These are estimates, NOT a guarantee of actual provider pricing.
    per_call = _money('SV_AI_BUDGET_PER_CALL_USD', Decimal('0.05'), Decimal('20'))
    buffer = _money('SV_AI_SAFETY_BUFFER_USD', Decimal('0.50'), Decimal('1000'))
    expected = _attempts(job)
    remaining_quota = _auto_budget_remaining()
    outstanding_calls = _commitments(job)
    from image_ai import remaining as image_remaining
    # The per-process image session limit is independent of the persistent
    # automatic queue budget; both must have room before starting billing.
    if expected > remaining_quota or expected + outstanding_calls > image_remaining():
        raise PermissionError('Pedidos temporariamente indisponíveis: limite de produção atingido. Nenhuma cobrança iniciada.')

    # No 120-second stale dashboard cache for a financial decision.
    from fal_balance import _fetch_balance
    status, data = _fetch_balance()
    if status != 200 or not isinstance(data, dict) or data.get('ok') is not True or data.get('currency')!='USD':
        raise PermissionError('Checkout indisponível no momento: não foi possível verificar os créditos da IA. Nenhuma cobrança iniciada.')
    try:
        balance = Decimal(str(data['balance']))
        if not balance.is_finite() or balance < 0: raise ValueError()
        needed = per_call * (outstanding_calls + expected) + buffer
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise PermissionError('Checkout indisponível: saldo ou pedidos pendentes inválidos. Nenhuma cobrança iniciada.')
    if balance < needed:
        raise PermissionError('Pedidos temporariamente indisponíveis: créditos insuficientes para garantir a reserva de produção. Nenhuma cobrança iniciada.')
    return {'ok': True, 'expected_calls': expected}
