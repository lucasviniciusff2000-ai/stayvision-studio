"""Fila semiautomática: dispara SOMENTE pagamento comprovado por provedor.
Esta fase não implementa o checkout/webhook; sem evento verificado, a fila não inicia.
"""
import os,threading,time,json
from threading import RLock
_BUDGET_LOCK=RLock()
from pathlib import Path

def enabled():
    # Requires independent budget and paid-AI opt-in; never start from checkout-only mode.
    return (os.environ.get('STAYVISION_SEMI_AUTO','').strip()=='1' and
            os.environ.get('SV_AUTO_AI_EXPLICIT')=='1' and
            os.environ.get('SV_AUTO_AI_BUDGET_MAX_CALLS','0').isdigit() and
            1<=int(os.environ.get('SV_AUTO_AI_BUDGET_MAX_CALLS','0'))<=200)

def cycle():
    if not enabled():return 0
    from commerce_flow import _store,start_commercial_production
    from premium_direct import _get,_read,RUNNING,RUN_LOCK
    # Precisely one producer at a time: avoid reserving budgets for jobs which
    # cannot acquire the engine lock. Other paid orders remain queued on disk.
    with RUN_LOCK:
        if RUNNING:return 0
    count=0
    for file in sorted(_store().glob('pedido-*.json'),key=lambda x:x.stat().st_mtime):
        try:
            order=json.loads(file.read_text(encoding='utf-8'))
            # Pilot is per-order, not a global change of the commercial checkout.
            pilot=order.get('e2e_trial') is True
            source_ok=(pilot and os.environ.get('SV_PILOT_R1_ENABLED')=='1' and
                       order.get('payment_source')=='MERCADO_PAGO_E2E_R1_VERIFICADO') or (
                       not pilot and order.get('payment_source') in
                       ('MERCADO_PAGO_WEBHOOK_VERIFICADO','MERCADO_PAGO_API_VERIFICADO'))
            if order.get('payment')!='VERIFICADO_PROVEDOR' or not source_ok:continue
            if _read(_get(order['id'])).get('status')!='PREPARADO_SEM_CREDITOS':continue
            from premium_direct import _get as get_prem, _read as read_prem
            expected=read_prem(get_prem(order['id'])).get('expected_attempts',0)
            if expected<=0:continue
            if pilot and expected!=1:continue
            from image_ai import preflight
            # Avoid reserving a job that cannot start due to insufficient
            # current-session credits. This check never calls a paid API.
            try:preflight(expected)
            except RuntimeError:
                continue
            budget_file=_store()/'auto_ia_budget.json'
            with _BUDGET_LOCK:
                ledger=json.loads(budget_file.read_text(encoding='utf-8')) if budget_file.exists() else {'reserved':{}}
                reserved=ledger.get('reserved') or {}
                # Uma reserva gravada torna o início IRREVERSÍVEL para automação.
                # Após queda de energia/erro incerto, só revisão manual; nunca repetir IA paga.
                if order['id'] in reserved:
                    continue
                limit=int(os.environ['SV_AUTO_AI_BUDGET_MAX_CALLS'])
                if sum(int(v) for v in reserved.values())+expected>limit:continue
                reserved[order['id']]=expected
                ledger['reserved']=reserved
                tmp=budget_file.with_suffix('.tmp')
                tmp.write_text(json.dumps(ledger),encoding='utf-8')
                os.replace(tmp,budget_file)
            # Calls are reserved before attempting production: never silently repeat.
            start_commercial_production(order['id'])
            count+=1
            # IMPORTANT: Do not reserve 2nd job while 1st is still in progress.
            break
        except (ValueError,RuntimeError,FileNotFoundError) as exc:
            # Não repetir falhas incertas nem gastar créditos repetidos.
            print('[fila semiauto] pendente/bloqueado:',type(exc).__name__,str(exc)[:140])
            # Um pedido problemático não bloqueia os demais da fila.
            continue
    return count

def start_background():
    if not enabled():return
    def worker():
        while True:
            try:cycle()
            except Exception as exc:print('[fila semiauto] erro:',type(exc).__name__)
            time.sleep(15)
    threading.Thread(target=worker,name='stayvision-semi-auto',daemon=True).start()
