"""Single admin-only, one-photo, one-time BRL 1 live payment pilot.

Customer catalogue and its public endpoints are deliberately unchanged.
This is opt-in, CSRF protected, and records its one-use provider preference on /data.
"""
from __future__ import annotations
import hashlib,json,os,secrets,shutil


def create_pilot_order(handler):
    from admin_panel import _check, _json
    from commerce_flow import _body,_store,_write,_stamp
    from real_plan_checkout import LOCK, pilot_quota_path,create
    from premium_direct import prepare_from_data
    from app import OUT
    try:
        _check(handler,modify=True)
        if os.environ.get('SV_PILOT_R1_ENABLED')!='1':
            raise PermissionError('Piloto privado de R$1 desativado.')
        data=_body(handler,12_000_000)
        if data.get('confirm')!='AUTORIZO UMA COBRANCA REAL DE R$ 1':
            raise PermissionError('Autorização explícita obrigatória.')
        if data.get('plan')!='fotos' or len(data.get('images') or [])!=1:
            raise ValueError('Piloto limitado a Fotos Business com uma foto.')
        if data.get('consent') is not True:
            raise ValueError('Confirme a autorização de tratamento da foto.')
        with LOCK:
            if pilot_quota_path().exists():
                raise ValueError('Piloto de R$1 já utilizado ou reservado. Não repetir cobrança.')
            prepared=prepare_from_data(data)
            job=prepared['id']
            access=secrets.token_urlsafe(32)
            state={
                'id':job,'brand':prepared['brand'],'plan':'fotos',
                'payment':'PENDENTE','payment_source':'NONE',
                'created_utc':_stamp(),
                'access_hash':hashlib.sha256(access.encode()).hexdigest(),
                'session_mode':'PILOTO_E2E_REAL_R1',
                'e2e_trial':True,
            }
            try:
                _write(job,state)
            except Exception:
                shutil.rmtree(OUT/job,ignore_errors=True)
                shutil.rmtree(OUT/'premium_direto_v33'/job,ignore_errors=True)
                raise
            # This creates at most one REAL BRL1 preference. Fail-closed if uncertain:
            # no retry from this endpoint, and existing order is kept for inspection.
            try:
                pay=create(job)
            except Exception as exc:
                print('[piloto-r1] checkout indisponível:',type(exc).__name__,flush=True)
                # Never return the private order link after an uncertain checkout.
                raise RuntimeError('Pedido preparado, mas checkout não confirmado. NÃO tente novamente; revise o painel.') from exc
        _json(handler,{'ok':True,'job':job,'amount_brl':'1.00',
                       'checkout_url':pay['url'],'customer_link':'/acompanhar/'+access,
                       'note':'Teste de cobrança REAL R$1. Apenas uma foto. Não quita o plano comercial.'},201)
    except PermissionError as exc:
        _json(handler,{'error':str(exc)},403)
    except (ValueError,TypeError,KeyError) as exc:
        _json(handler,{'error':str(exc)},400)
    except Exception as exc:
        print('[piloto-r1] falha:',type(exc).__name__,flush=True)
        _json(handler,{'error':'Falha no piloto. Não repita a cobrança; confira o painel e os logs.'},502)
