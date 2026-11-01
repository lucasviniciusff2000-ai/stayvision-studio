"""StayVision V3.9 admin dashboard -- LOCAL-ONLY demo.
Session-based authentication is a usability and defense-in-depth aid; this
stdlib HTTP server is NOT an internet-ready production admin system.
"""
from __future__ import annotations
import datetime as dt
import json
import re
import secrets
import threading
import time
from collections import Counter, defaultdict
from http.cookies import SimpleCookie
from pathlib import Path

_SESSIONS={}
_FAILURES=defaultdict(list)
_LOCK=threading.RLock()
_COOKIE='sv38_admin_session'
_EXPIRY=8*3600


def _json(h,data,status=200,headers=None):
    h._send(json.dumps(data,ensure_ascii=False),status,extra=headers)


def _read_json(h,limit=12000):
    from commerce_flow import _body
    return _body(h,limit)


def _cookie_token(h):
    try:
        c=SimpleCookie(); c.load(h.headers.get('Cookie',''))
        return c[_COOKIE].value if _COOKIE in c else ''
    except Exception:return ''


def authorized(h):
    token=_cookie_token(h)
    if not token:return None
    with _LOCK:
        info=_SESSIONS.get(token)
        if not info:return None
        if time.time()>info['expires']:
            _SESSIONS.pop(token,None)
            return None
        return info


def _check(h,modify=False):
    s=authorized(h)
    if s is None:raise PermissionError('Sessão expirada. Entre no painel novamente.')
    if modify:
        # _body enforces localhost + Origin; CSRF additionally guards admin mutations.
        if not secrets.compare_digest(str(h.headers.get('X-SV-CSRF','')),s['csrf']):
            raise PermissionError('Atualize a sessão do painel e tente novamente.')
    return s


def login(h):
    try:
        data=_read_json(h,3000)
        ip=h.client_address[0]
        now=time.time()
        with _LOCK:
            _FAILURES[ip]=[t for t in _FAILURES[ip] if now-t<90]
            if len(_FAILURES[ip])>=6:
                return _json(h,{'error':'Muitas tentativas. Tente novamente mais tarde.'},429)
        from commerce_flow import _operator_auth,SESSION_MARK
        from admin_credentials import configured,verify
        try:
            if configured():
                if not verify(str(data.get('username','')),str(data.get('password',''))):raise PermissionError('Login incorreto.')
            else:_operator_auth(h,data)
        except PermissionError:
            with _LOCK:_FAILURES[ip].append(now)
            return _json(h,{'error':'Usuário/senha incorretos ou código de operador inválido.'},403)
        with _LOCK:
            if len(_SESSIONS)>=40:
                for t in list(_SESSIONS)[:10]:_SESSIONS.pop(t,None)
            token=secrets.token_urlsafe(36)
            csrf=secrets.token_urlsafe(24)
            _SESSIONS[token]={'csrf':csrf,'expires':now+_EXPIRY}
            _FAILURES.pop(ip,None)
        cookie=f'{_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={_EXPIRY}' + ('; Secure' if __import__('os').environ.get('SV_PUBLIC_ORIGIN','').startswith('https://') else '')
        _json(h,{'ok':True,'csrf':csrf,'session':SESSION_MARK,'message':'Acesso autorizado ao painel local.'},headers={'Set-Cookie':cookie})
    except PermissionError:_json(h,{'error':'Acesso permitido somente a partir do aplicativo local.'},403)
    except (ValueError,TypeError) as e:_json(h,{'error':str(e)},400)


def session(h):
    s=authorized(h)
    _json(h,{'ok':bool(s),'csrf':s['csrf'] if s else None},200 if s else 401)


def logout(h):
    try:
        _check(h,modify=True);_read_json(h,3000)
        with _LOCK:_SESSIONS.pop(_cookie_token(h),None)
        _json(h,{'ok':True},headers={'Set-Cookie':f'{_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' + ('; Secure' if __import__('os').environ.get('SV_PUBLIC_ORIGIN','').startswith('https://') else '')})
    except PermissionError as e:_json(h,{'error':str(e)},401)
    except (ValueError,TypeError) as e:_json(h,{'error':str(e)},400)


def _orders():
    from commerce_flow import _store,_public
    orders=[]
    for f in sorted(_store().glob('pedido-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:250]:
        try:
            s=json.loads(f.read_text(encoding='utf-8'))
            p=_public(s)
            orders.append({k:p.get(k) for k in ('id','brand','plan','payment','production','phase','progress_percent','attempts_completed','expected_attempts','review','created_utc','paid_amount_brl','e2e_trial')})
        except Exception:continue
    return orders


def financial_report(orders):
    # Valores de catálogo para estimativas DEMO. Não são receitas financeiras.
    prices={'Fotos Business':5990,'Perfil Express':14990,'Vitrine Digital':24990,'Feed Premium':39990}
    stats={k:{'plan':k,'orders':0,'sandbox_confirmed_orders':0,'demo_paid_orders':0,'demo_total_cents':0,'estimated_pipeline_cents':0,'real_paid_orders':0,'real_revenue_cents':0} for k in prices}
    periods={}
    clients=set()
    for o in orders:
        plan=o.get('plan')
        if plan not in stats:continue
        x=stats[plan];x['orders']+=1
        name=str(o.get('brand') or '').strip().casefold()
        if name:clients.add(name)
        amount=prices[plan]
        x['estimated_pipeline_cents']+=amount
        month=str(o.get('created_utc') or '')[:7]
        if not re.fullmatch(r'\d{4}-\d{2}',month):month='sem data'
        t=periods.setdefault(month,{'period':month,'orders':0,'sandbox_confirmed_orders':0,'demo_paid_orders':0,'demo_total_cents':0,'real_revenue_cents':0})
        t['orders']+=1
        if o.get('payment')=='SANDBOX_APROVADO':
            x['sandbox_confirmed_orders']+=1
            t['sandbox_confirmed_orders']+=1
        if o.get('payment')=='DEMO_PAGO':
            x['demo_paid_orders']+=1;x['demo_total_cents']+=amount
            t['demo_paid_orders']+=1;t['demo_total_cents']+=amount
        if o.get('payment')=='VERIFICADO_PROVEDOR' and not o.get('e2e_trial'):
            from decimal import Decimal,InvalidOperation
            try:credit=int(Decimal(str(o.get('paid_amount_brl')))*100)
            except (InvalidOperation,TypeError):credit=0
            if credit==prices[plan]:
                x['real_paid_orders']+=1;x['real_revenue_cents']+=credit
                t['real_revenue_cents']+=credit
    ordered=sorted(stats.values(),key=lambda x:(-x['orders'],-x['demo_paid_orders'],x['plan']))
    return {'currency':'BRL','financial_mode':'LOCAL_CONCILIACAO_REAIS_PROVEDOR',
            'real_revenue_cents':sum(x['real_revenue_cents'] for x in ordered),'real_paid_orders':sum(x['real_paid_orders'] for x in ordered),
            'sandbox_confirmed_orders':sum(x['sandbox_confirmed_orders'] for x in ordered),
            'demo_paid_orders':sum(x['demo_paid_orders'] for x in ordered),
            'demo_total_cents':sum(x['demo_total_cents'] for x in ordered),
            'estimated_pipeline_cents':sum(x['estimated_pipeline_cents'] for x in ordered),
            'unique_clients':len(clients),'by_plan':ordered,'monthly':sorted(periods.values(),key=lambda x:x['period']),
            'pilot_real':__import__('pilot_live_payment').status_for_admin(),
            'note':'Vendas reais apenas com confirmação da API do Mercado Pago e valor oficial. Piloto R$1 separado. Taxas e lucro ainda não conciliados.'}


def overview(h):
    try:
        _check(h)
        orders=_orders()
        stages=Counter(o['production'] for o in orders)
        pmts=Counter(o['payment'] for o in orders)
        reviews=Counter(o['review'] for o in orders)
        # A demo order is NOT revenue. Do not conflate notional prices and paid money.
        result={'ok':True,'mode':'LOCAL_TESTE_E_CONCILIACAO_REAL_CONTROLADA',
                'summary':{'orders':len(orders),'pending_payment':pmts['PENDENTE'],
                          'demo_payments':pmts['DEMO_PAGO'],'sandbox_confirmed':pmts['SANDBOX_APROVADO'],'producing':stages['EM_PRODUCAO'],
                          'awaiting_review':stages['REVISAO_NECESSARIA']-reviews['APROVADO'],
                          'approved':reviews['APROVADO'],
                          'interrupted':stages['INTERROMPIDO_SEM_REPETICAO'],
                          'real_revenue_brl':financial_report(orders)['real_revenue_cents']/100,'real_paid_orders':financial_report(orders)['real_paid_orders'],'pilot_real':__import__('pilot_live_payment').status_for_admin()},'orders':orders,'finance':financial_report(orders),
                'note':'Valores e pagamentos DEMO não representam faturamento. Produção real por IA exige autorização explícita.'}
        _json(h,result)
    except PermissionError as e:_json(h,{'error':str(e)},401)


def details(h,job):
    try:
        _check(h)
        from commerce_flow import _read as read_commercial, _public
        s=read_commercial(job)
        p=_public(s)
        from premium_direct import _get, _read as prem_read
        st=prem_read(_get(job))
        details={'ok':True,'order':p,'photos_count':len(st.get('diagnoses',[])),
                 'diagnoses':st.get('diagnoses',[]),'payment_source':s.get('payment_source'),
                 'started_at':st.get('started_utc'),'last_action':st.get('last_action'),
                 'instagram':st.get('instagram'),'contact':st.get('contact'),'activity':st.get('activity'),
                 'errors':st.get('errors',[]),'created_utc':s.get('created_utc'),
                 'pilot_real':__import__('pilot_live_payment').status_for_admin(job),'checkout_real':s.get('checkout_real') and {'status':s['checkout_real'].get('status'),'amount_brl':s['checkout_real'].get('amount_brl')}}
        if p['production']=='REVISAO_NECESSARIA':
            from auto_delivery import status_for_admin
            details['auto_delivery']=status_for_admin(job)
            from app import get_order
            try:
                q=get_order(job)
                details['quality']={k:q.get(k) for k in ('missing','photos_ready','posts_ready','stories_ready','extras_ready','visual_previews','delivery_link','review')}
            except (FileNotFoundError,ValueError,KeyError):pass
        _json(h,details)
    except PermissionError as e:_json(h,{'error':str(e)},401)
    except (FileNotFoundError,ValueError):_json(h,{'error':'Pedido não encontrado.'},404)


def action(h,job,verb):
    try:
        _check(h,modify=True)
        data=_read_json(h,3500)
        if verb=='demo-payment':
            if data.get('confirm')!='SIMULAR_PAGAMENTO':raise ValueError('Confirmação DEMO obrigatória.')
            from commerce_flow import register_demo_payment
            msg=register_demo_payment(job)
            return _json(h,{'ok':True,'message':msg})
        if verb=='start-production':
            if data.get('confirm') not in ('AUTORIZO_PRODUCAO_COM_CUSTOS','AUTORIZO_PREMIUM_COMPLETO'):raise ValueError('Autorização explícita obrigatória.')
            from commerce_flow import start_commercial_production
            st=start_commercial_production(job)
            return _json(h,{'ok':True,'status':st['status'],'message':'Produção iniciada. As APIs podem cobrar créditos reais.'},202)
        if verb=='review':
            # Existing review handler checks artifact completeness, paid status and creates the gallery.
            from app import REVIEW_CHECKS, get_order,order_dir,read_review,OUT
            from commerce_flow import is_paid
            from delivery_mobile import create as create_delivery, revoke as revoke_delivery
            import zipfile
            decision=data.get('decision')
            if decision not in ('approved','rejected'):raise ValueError('Decisão inválida.')
            info=get_order(job)
            if not is_paid(job):raise ValueError('Pedido de teste não pago.')
            checks={k:data.get('checks',{}).get(k) is True for k in REVIEW_CHECKS}
            notes=str(data.get('notes',''))[:1500]
            if decision=='approved':
                if not all(checks.values()):raise ValueError('Marque todos os itens da revisão.')
                if info.get('missing'):raise ValueError('Pacote incompleto: '+'; '.join(info['missing']))
                if info.get('brand_conflict') and len(notes.strip())<15:raise ValueError('Registre como conferiu a divergência de marca.')
            status='APROVADO' if decision=='approved' else 'REPROVADO'
            state={'status':status,'checks':checks,'notes':notes,'reviewed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                   'review_type':'revisão humana manual'}
            folder=order_dir(job)
            (folder/'REVISAO_INTERNA.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
            arch=OUT/f'aprovado-{job}.zip'
            revoke_delivery(job)
            if decision=='approved':
                with zipfile.ZipFile(arch,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
                    for f in folder.rglob('*'):
                        if f.is_file():z.write(f,f.relative_to(folder))
            elif arch.exists():arch.unlink()
            delivery=create_delivery(job) if decision=='approved' else None
            return _json(h,{'ok':True,'message':f'Pedido {status.lower()} após revisão.','delivery':delivery})
        if verb=='revoke':
            from delivery_mobile import revoke
            revoke(job)
            return _json(h,{'ok':True,'message':'Link de entrega revogado.'})
        return _json(h,{'error':'Ação não encontrada.'},404)
    except PermissionError as e:_json(h,{'error':str(e)},401)
    except (ValueError,FileNotFoundError,KeyError,TypeError,RuntimeError) as e:_json(h,{'error':str(e)},400)
    except Exception as e:
        print('[painel] falha',type(e).__name__,str(e)[:100]);_json(h,{'error':'Falha interna; verifique o terminal.'},500)
