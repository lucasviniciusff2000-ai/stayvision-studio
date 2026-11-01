"""Revisão e liberação automáticas OPCIONAIS, local, somente pagamentos reais.

Não certifica fidelidade visual semântica: falha fechada se houver alerta de qualidade,
conflito de marca ou arquivo incompleto. O operador pode usar revisão manual.
"""
from __future__ import annotations
import datetime, json, os, threading, zipfile
from pathlib import Path
from PIL import Image

LOCK=threading.RLock()

def enabled():
    """Production opt-in OR constrained one-photo pilot, with strict budget."""
    env=os.environ
    common=(env.get('STAYVISION_FULL_AUTO')=='1' and
            env.get('SV_AUTO_DELIVERY_EXPLICIT')=='1' and
            env.get('STAYVISION_SEMI_AUTO')=='1' and
            env.get('SV_AUTO_AI_EXPLICIT')=='1' and
            env.get('SV_REAL_PLANS_ENABLED')=='1' and
            bool(env.get('MP_LIVE_ACCESS_TOKEN')))
    if not common:return False
    max_orders=env.get('SV_AUTO_DELIVERY_MAX_ORDERS','0')
    max_calls=env.get('SV_AUTO_AI_BUDGET_MAX_CALLS','0')
    if not (max_orders.isdecimal() and 1<=int(max_orders)<=200 and max_calls.isdecimal() and 1<=int(max_calls)<=200):return False
    if env.get('SV_COMMERCIAL_AUTO_DELIVERY')=='1':return True
    return (env.get('SV_ONE_REAL_E2E')=='1' and env.get('SV_E2E_ONE_REAL_ACK')=='1'
            and max_orders=='1' and max_calls=='1')


def paid_for_delivery(state):
    if state.get('payment')!='VERIFICADO_PROVEDOR':return False
    checkout=state.get('checkout_real') or {}
    if checkout.get('status')!='PREFERENCIA_CRIADA' or checkout.get('currency')!='BRL':return False
    if not (str(checkout.get('seller_id') or '').isdecimal() and
            str(checkout.get('payment_id') or '').isdecimal() and
            checkout.get('preference_id')):return False
    if state.get('e2e_trial') is True:
        return (enabled() and state.get('session_mode')=='PILOTO_E2E_REAL_R1'
                and state.get('payment_source')=='MERCADO_PAGO_E2E_R1_VERIFICADO'
                and state.get('paid_amount_brl')=='1.00' and
                state.get('plan')=='fotos' and checkout.get('kind')=='E2E_ONE_REAL'
                and checkout.get('amount_brl')=='1.00')
    if not enabled() or os.environ.get('SV_COMMERCIAL_AUTO_DELIVERY')!='1':return False
    from real_plan_checkout import PRICES
    try:
        from decimal import Decimal
        price=PRICES[state.get('plan')]
        return (checkout.get('kind')=='REAL_PLAN' and
                state.get('payment_source') in ('MERCADO_PAGO_API_VERIFICADO','MERCADO_PAGO_WEBHOOK_VERIFICADO') and
                Decimal(str(state.get('paid_amount_brl'))) == price and
                Decimal(str(checkout.get('amount_brl'))) == price)
    except (ValueError,KeyError,TypeError):return False

def production_finished(job):
    """Only completed jobs may be evaluated. Payment can precede image production by minutes.

    V3.27 accidentally classified jobs that were still generating as permanently
    needing human review; a later successful image could never be auto-delivered.
    """
    from premium_direct import _get, _read
    return _read(_get(job)).get('status')=='REVISAO_NECESSARIA'


def status_for_admin(job):
    """Read-only report for the existing panel; never exposes private access tokens."""
    from app import OUT, read_review
    from commerce_flow import _read
    from premium_direct import _get, _read as prod_read
    record=_read(job)
    review=read_review(job)
    if review.get('status')=='APROVADO':
        return {'status':'LIBERADO_AUTOMATICO' if review.get('review_type')=='triagem automática conservadora, sem análise humana' else 'LIBERADO_MANUAL', 'issues':[]}
    if review.get('status')=='REPROVADO':return {'status':'REPROVADO_MANUAL','issues':[]}
    blocked=OUT/job/'AUTO_TRIAGEM.json'
    if blocked.is_file():
        try:
            obj=json.loads(blocked.read_text(encoding='utf-8'))
            return {'status':'REVISAO_NECESSARIA','issues':[str(x)[:250] for x in obj.get('issues',[])][:15]}
        except (ValueError,OSError,TypeError):return {'status':'REVISAO_NECESSARIA','issues':['Registro de auditoria ilegível.']}
    receipt=OUT/job/'AUTO_REVISAO_RESERVADA.json'
    if receipt.is_file():return {'status':'VERIFICAR_RESERVA','issues':['Uma liberação automática foi reservada; verificar antes de repetir.']}
    if record.get('payment')!='VERIFICADO_PROVEDOR':return {'status':'AGUARDANDO_PAGAMENTO','issues':[]}
    status=prod_read(_get(job)).get('status')
    if status=='INTERROMPIDO_SEM_REPETICAO':return {'status':'ERRO_PRODUCAO','issues':['Produção interrompida; não repetir chamadas pagas automaticamente.']}
    if status!='REVISAO_NECESSARIA':return {'status':'AGUARDANDO_PRODUCAO','issues':[]}
    return {'status':'AGUARDANDO_REVISAO_HUMANA','issues':[]}

def gate(job):
    """Auditoria técnica conservadora; impossível assegurar aparência por métricas."""
    from app import get_order,order_dir,audit_artifacts
    from commerce_flow import _read
    from premium_direct import _get,_read as production_read
    from photo_quality import inspect_result
    reasons=[]
    order=_read(job)
    if not paid_for_delivery(order):
        reasons.append('Pagamento integral não verificado na API do provedor.')
    if production_read(_get(job)).get('status')!='REVISAO_NECESSARIA':
        reasons.append('Produção ainda não terminou.')
    detail=get_order(job)
    if detail.get('missing'):reasons.extend('Auditoria: '+str(x) for x in detail['missing'][:20])
    if detail.get('brand_conflict'):reasons.append('Conflito de identidade visual: requer avaliação humana.')
    if detail.get('creative_quality_flags'):reasons.append('Alertas no motor criativo: requer avaliação humana.')
    folder=order_dir(job)
    info=json.loads((folder/'INFO_PEDIDO.json').read_text(encoding='utf-8'))
    if info.get('plan')!=order.get('plan'):reasons.append('Plano dos arquivos não corresponde à compra.')
    if bool(info.get('sample_only')):reasons.append('Pacote incompleto/amostra.')
    pstate=production_read(_get(job))
    if pstate.get('errors'):reasons.append('Falhas de produção registradas.')
    for d in pstate.get('diagnoses') or []:
        if d.get('risk')=='alto':reasons.append('Imagem original de alto risco; exige revisão.')
    if detail.get('plan_code') in ('fotos','premium'):
        n=int(info.get('photos_received') or 0)
        if n<1:reasons.append('Nenhuma foto recebida.')
        for i in range(1,min(8,n)+1):
            original=folder/f'00_originais/original_{i:02d}.jpg'
            edited=folder/f'01_fotos_tratadas/foto_profissional_{i:02d}.jpg'
            if not original.is_file() or not edited.is_file():
                reasons.append(f'Original/foto editada {i} ausente.');continue
            try:
                with Image.open(original) as a,Image.open(edited) as b:
                    checked=inspect_result(a,b,sector=(info.get('creative_direction') or {}).get('sector','generico'))
                # Sinais heurísticos de risco não liberam automaticamente.
                if checked.get('review_flags'):reasons.extend('Foto %s: %s'%(i,m) for m in checked['review_flags'])
            except Exception:
                reasons.append(f'Foto {i}: inspeção local falhou.')
    return reasons

def approve_one(job, force_test=False):
    """Publica galeria privada somente após auditoria sem alertas e pagamento real.
    force_test não ignora pagamento; é reservado aos testes offline com mocks.
    """
    if not enabled() and not force_test:return 'DISABLED'
    from commerce_flow import _read
    from app import OUT,order_dir,read_review
    from delivery_mobile import create as create_delivery,link_for_operator,revoke
    with LOCK:
        state=_read(job)
        if not paid_for_delivery(state):
            return 'UNPAID'
        existing=read_review(job).get('status')
        if existing=='APROVADO':return 'ALREADY_APPROVED'
        if existing=='REPROVADO':return 'MANUAL_REJECTED'
        # A produção demora. NÃO registrar alerta permanente enquanto a IA trabalha.
        if not production_finished(job):return 'NOT_READY'
        triage=OUT/job/'AUTO_TRIAGEM.json'
        if triage.exists():
            # Recuperar somente classificações feitas prematuramente na V3.27.
            # A auditoria é executada novamente do zero sobre os arquivos finais.
            try:
                past=json.loads(triage.read_text(encoding='utf-8'))
                old_issues=past.get('issues') or []
                if 'Produção ainda não terminou.' in old_issues:
                    triage.unlink()
                else:return 'REVIEW_REQUIRED'
            except (OSError,ValueError,TypeError):return 'REVIEW_REQUIRED'
        receipt=OUT/job/'AUTO_REVISAO_RESERVADA.json'
        if receipt.exists():return 'MANUAL_CHECK_REQUIRED'
        try:
            issues=gate(job)
        except (FileNotFoundError,ValueError,KeyError,RuntimeError) as e:
            issues=['Falha de auditoria: '+type(e).__name__]
        if issues:
            note={'status':'REVISAO_HUMANA_NECESSARIA','issues':issues[:30],
                  'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
            p=OUT/job/'AUTO_TRIAGEM.json'
            p.write_text(json.dumps(note,ensure_ascii=False,indent=2),encoding='utf-8')
            return 'REVIEW_REQUIRED'
        # Reserva antes de tocar no pacote: após queda incerta, nunca repetir automaticamente.
        receipt.write_text(json.dumps({'status':'RESERVADO','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}),encoding='utf-8')
        try:
            # Não aceitar estorno/contestação entre auditoria e liberação.
            current=_read(job)
            if current.get('payment')!='VERIFICADO_PROVEDOR':return 'PAYMENT_CHANGED'
            folder=order_dir(job)
            review_file=folder/'REVISAO_INTERNA.json'
            review={'status':'APROVADO', 'checks':{'arquivos':True},
                    'notes':'Liberação automática após verificações técnicas. Fidelidade visual semântica não certificada.',
                    'review_type':'triagem automática conservadora, sem análise humana',
                    'reviewed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
            # Escrever revisão somente quando a auditoria foi aceita.
            review_file.write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
            output=OUT/f'aprovado-{job}.zip'
            tmp=OUT/f'aprovado-{job}.zip.tmp'
            with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as arc:
                for item in sorted(folder.rglob('*')):
                    if item.is_file():arc.write(item,item.relative_to(folder))
            tmp.replace(output)
            # Rechecar a situação de pagamento ANTES da criação do link.
            if _read(job).get('payment')!='VERIFICADO_PROVEDOR':
                output.unlink(missing_ok=True);review_file.unlink(missing_ok=True)
                return 'PAYMENT_CHANGED'
            revoke(job)
            create_delivery(job)
            receipt.write_text(json.dumps({'status':'ENTREGUE','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()},ensure_ascii=False),encoding='utf-8')
            return 'DELIVERED' if link_for_operator(job) else 'LINK_ERROR'
        except Exception as exc:
            try:revoke(job)
            except Exception:pass
            print('[entrega automatica] revisar manualmente',type(exc).__name__)
            return 'MANUAL_CHECK_REQUIRED'

def cycle():
    if not enabled():return 0
    from commerce_flow import _store
    limit=int(os.environ.get('SV_AUTO_DELIVERY_MAX_ORDERS','1'))
    from app import OUT
    # Limite por instalação, não apenas por ciclo. Evita entregas ilimitadas por engano.
    previous=sum(1 for f in OUT.glob('pedido-*/AUTO_REVISAO_RESERVADA.json') if '"ENTREGUE"' in f.read_text(encoding='utf-8'))
    if previous>=limit:return 0
    total=0
    for f in sorted(_store().glob('pedido-*.json'),key=lambda p:p.stat().st_mtime):
        if previous+total>=limit:break
        try:
            record=json.loads(f.read_text(encoding='utf-8'))
            if not paid_for_delivery(record):continue
            # Não realizar triagem antes da última imagem terminar.
            if not production_finished(record['id']):continue
            result=approve_one(record['id'])
            if result=='DELIVERED':
                total+=1
                print('[entrega] Auditoria aprovada. Galeria privada liberada no acompanhamento.')
            elif result in ('REVIEW_REQUIRED','MANUAL_CHECK_REQUIRED'):
                print('[entrega] Material RETIDO; verificar qualidade no painel, sem novas chamadas de IA.')
        except Exception as exc:print('[entrega auto] triagem adiada:',type(exc).__name__)
    return total

def start_background():
    if not enabled():return
    def worker():
        import time
        while True:
            try:cycle()
            except Exception as exc:print('[entrega auto] falha de ciclo:',type(exc).__name__)
            time.sleep(20)
    threading.Thread(target=worker,name='stayvision-auto-delivery',daemon=True).start()
