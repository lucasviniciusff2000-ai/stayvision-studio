"""StayVision V3.7 — rehearsal of commercial journey on localhost only.

No checkout, Pix, payment webhook, public server, automatic deliveries or fake
production payment verifications. The operator enters a terminal-only code to
mark a DEMO PAYMENT explicitly. This code must never be deployed publicly.
"""
from __future__ import annotations
import hashlib, json, os, secrets, threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

TOKEN_SIZE=43
_ACCESS_LINK_LOCK=threading.RLock()
_TRACKING_REISSUE_LIMIT=10
ADMIN_CODE=os.environ.get('STAYVISION_DEMO_ADMIN_CODE') or secrets.token_urlsafe(18)
SESSION_MARK=secrets.token_hex(3).upper()  # Public diagnostic marker, NOT an authentication token


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _store():
    from app import OUT
    root=OUT/'jornada_cliente_v37'
    root.mkdir(exist_ok=True)
    return root


def _path(job):
    from app import JOB_RE
    if not JOB_RE.fullmatch(str(job)):raise ValueError('Identificador inválido')
    return _store()/(job+'.json')


def _read(job):
    return json.loads(_path(job).read_text(encoding='utf-8'))


def _write(job,state):
    path=_path(job)
    tmp=path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)


def is_commercial_job(job):
    try:return _path(job).is_file()
    except ValueError:return False


def is_paid(job):
    try:return _read(job).get('payment') in ('DEMO_PAGO', 'VERIFICADO_PROVEDOR')
    except (ValueError,OSError):return False


def _body(h,limit=75_000_000):
    ct=h.headers.get('Content-Type','').split(';')[0].strip().lower()
    if ct!='application/json':raise ValueError('Envie JSON.')
    origin=h.headers.get('Origin','')
    host=h.headers.get('Host','')
    public=os.environ.get('SV_PUBLIC_ORIGIN','').rstrip('/')
    if public:
        from urllib.parse import urlsplit
        expected=urlsplit(public)
        if expected.scheme not in ('https','http') or not expected.netloc:
            raise PermissionError('Origem pública não configurada corretamente.')
        if host.lower()!=expected.netloc.lower() or origin!=public:
            raise PermissionError('Origem ou domínio não autorizado.')
    else:
        if host not in ('127.0.0.1:8786','localhost:8786'):
            raise PermissionError('Apenas localhost.')
        if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
            raise PermissionError('Origem não autorizada.')
    n=int(h.headers.get('Content-Length','0'))
    if not 2<=n<=limit:raise ValueError('Dados inválidos ou muito grandes.')
    return json.loads(h.rfile.read(n))


def _send(h, data, status=200):
    h._send(json.dumps(data,ensure_ascii=False),status)


def _additional_access_path(job):
    # Secondary tracking hashes never modify the original order/payment record.
    _path(job)  # validates job ID before constructing the filename
    return _store()/'acessos_adicionais'/(job+'.json')


def issue_tracking_link(job):
    """Create a fresh private tracking URL; keep the original link valid.

    Admin authentication and CSRF must be enforced by the caller. Only hashed
    tokens are retained, separate from the payment and production files.
    """
    _read(job)  # nonexistent order is rejected; no requests to APIs
    token=secrets.token_urlsafe(32)
    assert len(token)==TOKEN_SIZE
    digest=hashlib.sha256(token.encode('utf-8')).hexdigest()
    path=_additional_access_path(job)
    with _ACCESS_LINK_LOCK:
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        try:
            hashes=json.loads(path.read_text(encoding='utf-8')).get('hashes',[]) if path.exists() else []
        except (OSError,ValueError,AttributeError):
            raise RuntimeError('Registro de links inválido; não gerar novo link sem revisão.')
        if not isinstance(hashes,list) or any(not isinstance(x,str) or len(x)!=64 for x in hashes):
            raise RuntimeError('Registro de links inválido; não gerar novo link sem revisão.')
        hashes=(hashes+[digest])[-_TRACKING_REISSUE_LIMIT:]
        tmp=path.with_suffix('.json.tmp')
        try:
            with open(tmp,'x',encoding='utf-8') as out:
                json.dump({'hashes':hashes},out)
                out.flush();os.fsync(out.fileno())
            os.replace(tmp,path)
            try:path.chmod(0o600)
            except OSError:pass
        finally:
            tmp.unlink(missing_ok=True)
    return '/acompanhar/'+token


def _additional_access_matches(job,digest):
    path=_additional_access_path(job)
    if not path.is_file():return False
    try:hashes=json.loads(path.read_text(encoding='utf-8')).get('hashes',[])
    except (OSError,ValueError,AttributeError):return False
    if not isinstance(hashes,list):return False
    return any(isinstance(value,str) and secrets.compare_digest(value,digest) for value in hashes)


def _by_token(token):
    if len(token)!=TOKEN_SIZE or not all(c.isalnum() or c in '-_' for c in token):
        raise FileNotFoundError('Link inválido.')
    digest=hashlib.sha256(token.encode()).hexdigest()
    for p in _store().glob('pedido-*.json'):
        try:s=json.loads(p.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if not isinstance(s,dict) or not isinstance(s.get('access_hash'),str):continue
        if secrets.compare_digest(s['access_hash'],digest):return s
        try:
            if _additional_access_matches(p.stem,digest):return s
        except ValueError:continue
    raise FileNotFoundError('Link inválido.')


def _public(s):
    from premium_direct import _get as premium_get, _read as premium_read, _public as premium_public
    from app import read_review
    job=s['id']
    try:p=premium_public(premium_read(premium_get(job)))
    except FileNotFoundError:p={}
    production=p.get('status','PREPARADO_SEM_CREDITOS')
    paid=s.get('payment')
    pilot=__import__('pilot_live_payment').status_for_admin(job)
    pilot_visible=pilot.get('taken') and pilot.get('order_id')==job and pilot.get('status')=='APROVADO_REAL'
    review='PENDENTE'
    if production=='REVISAO_NECESSARIA':
        try:review=read_review(job).get('status','PENDENTE')
        except FileNotFoundError:pass
    allowed=paid in ('DEMO_PAGO','VERIFICADO_PROVEDOR') and review=='APROVADO'
    delivery=None
    if allowed:
        from delivery_mobile import link_for_operator
        delivery=link_for_operator(job)
    from engine import PLANS
    plan=PLANS.get(s.get('plan','premium'),PLANS['premium'])['name']
    return {'ok':True,'id':job,'brand':s.get('brand'), 'plan':plan,'e2e_trial':bool(s.get('e2e_trial')),
            'payment':paid,'paid_amount_brl':s.get('paid_amount_brl'), 'checkout_real_url':(s.get('checkout_real') or {}).get('url') if paid=='PENDENTE' and __import__('real_plan_checkout').enabled() else None,'pilot_real_approved':bool(pilot_visible), 'checkout_real_available':__import__('real_plan_checkout').enabled(),
            'payment_note':('Piloto real de R$ 1,00 confirmado pelo Mercado Pago; NÃO quita o plano integral.' if paid=='VERIFICADO_PROVEDOR' and s.get('e2e_trial') else 'Plano pago e confirmado pelo Mercado Pago.' if paid=='VERIFICADO_PROVEDOR' else 'Pagamento estornado: entrega suspensa.' if paid=='ESTORNADO_PROVEDOR' else 'Pagamento contestado: entrega suspensa.' if paid=='CONTESTADO_PROVEDOR' else 'Aprovado no sandbox do Mercado Pago. Nenhum faturamento ou produção real.' if paid=='SANDBOX_APROVADO' else 'Pagamento simulado local: nenhum Pix ou cobrança real.' if paid=='DEMO_PAGO' else 'Pedido do plano aguardando pagamento. O piloto real de R$ 1,00 é separado e não quita o pacote.' if pilot_visible else 'Pagamento do plano ainda não confirmado.'),
            'production':production if paid in ('DEMO_PAGO','VERIFICADO_PROVEDOR') else 'AGUARDANDO_PAGAMENTO',
            'phase':('Arquivos disponíveis na sua galeria privada.' if delivery else 'Pagamento real confirmado; aguardando produção.' if paid=='VERIFICADO_PROVEDOR' and production=='PREPARADO_SEM_CREDITOS' else 'Pagamento de teste confirmado no sandbox. Produção paga bloqueada.' if paid=='SANDBOX_APROVADO' else ('Pagamento de teste registrado. Aguardando início da produção.' if paid=='DEMO_PAGO' and production=='PREPARADO_SEM_CREDITOS' else p.get('phase')) if paid in ('DEMO_PAGO','VERIFICADO_PROVEDOR') else 'Pedido recebido. Aguardando confirmação do pagamento.'),
            'progress_percent':p.get('progress_percent') if paid in ('DEMO_PAGO','VERIFICADO_PROVEDOR') else None,
            'attempts_completed':p.get('attempts_completed') if paid in ('DEMO_PAGO','VERIFICADO_PROVEDOR') else None,
            'expected_attempts':p.get('expected_attempts'),
            'eta_low_seconds':p.get('eta_low_seconds'),
            'eta_high_seconds':p.get('eta_high_seconds'),
            'review':review,'delivery':delivery,'created_utc':s.get('created_utc')}


def create_customer(h):
    try:
        data=_body(h)
        from engine import PLANS
        plan=str(data.get('plan') or '')
        if plan not in PLANS:raise ValueError('Escolha um dos quatro planos disponíveis.')
        if data.get('consent') is not True:raise ValueError('Confirme que os arquivos podem ser usados no ensaio privado.')
        from real_plan_checkout import pilot_mode
        if pilot_mode() and (plan!='fotos' or len(data.get('images') or [])!=1):
            raise ValueError('Modo piloto R$1: escolha Fotos Business e envie exatamente UMA foto.')
        from premium_direct import prepare_from_data
        st=prepare_from_data(data)
        token=secrets.token_urlsafe(32)
        assert len(token)==TOKEN_SIZE
        record={'id':st['id'],'brand':st['brand'],'plan':plan,'payment':'PENDENTE',
                'payment_source':'NONE','created_utc':_stamp(),
                'access_hash':hashlib.sha256(token.encode()).hexdigest(),'session_mode':'PILOTO_E2E_REAL_R1' if pilot_mode() else 'DEMONSTRACAO_LOCAL',
                'e2e_trial':bool(pilot_mode())}
        try:_write(st['id'],record)
        except Exception:
            from app import OUT
            import shutil
            shutil.rmtree(OUT/st['id'],ignore_errors=True)
            shutil.rmtree(OUT/'premium_direto_v33'/st['id'],ignore_errors=True)
            raise
        _send(h,{'ok':True,'id':st['id'],'customer_link':'/acompanhar/'+token,
                 'payment':'PENDENTE','message':'Pedido criado SEM cobrar. Guarde seu link privado.'},201)
    except (ValueError,TypeError,OverflowError,MemoryError) as e:_send(h,{'error':str(e)},400)
    except PermissionError:_send(h,{'error':'Origem não autorizada.'},403)
    except Exception as e:
        print('[commerce v37] create error',type(e).__name__,str(e)[:130]);_send(h,{'error':'Não foi possível preparar este pedido.'},500)


def status_customer(h, token):
    try:_send(h,_public(_by_token(token)))
    except FileNotFoundError:_send(h,{'error':'Link privado não encontrado.'},404)


def customer_page(h, token):
    try:
        _by_token(token)
        from app import ROOT
        h._send((ROOT/'acompanhar_cliente.html').read_bytes(),mime='text/html; charset=utf-8',extra={'X-Robots-Tag':'noindex,nofollow', 'Referrer-Policy':'no-referrer',
              'Content-Security-Policy':"default-src 'self'; img-src 'self' data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"})
    except FileNotFoundError:_send(h,{'error':'Link privado não encontrado.'},404)


def _operator_auth(h,data):
    if not secrets.compare_digest(str(data.get('operator_code','')).strip(), ADMIN_CODE.strip()):
        raise PermissionError('Código de operador incorreto. Consulte o terminal do servidor.')


def operator_list(h):
    try:
        items=[]
        for p in sorted(_store().glob('pedido-*.json'),key=lambda f:f.stat().st_mtime,reverse=True)[:60]:
            try:
                s=json.loads(p.read_text(encoding='utf-8'))
                public=_public(s)
                public.pop('delivery',None)
                items.append(public)
            except Exception:continue
        _send(h,{'ok':True,'orders':items,'notice':'Dados de ENSAIO LOCAL. Nenhum pagamento real habilitado.','session':SESSION_MARK})
    except Exception:_send(h,{'error':'Falha ao listar pedidos de teste.'},500)


def verify_operator(h):
    try:
        data=_body(h,3000)
        _operator_auth(h,data)
        _send(h,{'ok':True,'message':'Código confirmado para o servidor ativo.','session':SESSION_MARK})
    except PermissionError:
        _send(h,{'error':'Código incorreto para o servidor ativo. Confira o código no terminal que está atendendo a porta 8786.','session':SESSION_MARK},403)
    except (ValueError,TypeError) as exc:
        _send(h,{'error':str(exc)},400)

def register_demo_payment(job):
    """One demo transition; never represents a provider-confirmed payment."""
    s=_read(job)
    if __import__('real_plan_checkout').enabled() or s.get('checkout_real'):raise ValueError('Não é permitido simular pagamento de pedido com checkout real.')
    if s['payment']!='PENDENTE':raise ValueError('Pagamento de teste já registrado.')
    from premium_direct import _get, _read as premium_read
    if premium_read(_get(s['id']))['status']!='PREPARADO_SEM_CREDITOS':
        raise ValueError('Pedido já iniciado; não alterar estado de pagamento.')
    s.update(payment='DEMO_PAGO',payment_source='ADMIN_DEMO_EXPLICIT',payment_updated_utc=_stamp())
    _write(s['id'],s)
    return 'Pagamento de demonstração registrado. Nenhum Pix ou cobrança real.'


def start_commercial_production(job):
    if not is_paid(job):raise ValueError('Sem pagamento DEMO confirmado. Não produzir.')
    from premium_direct import start_prepared
    return start_prepared(job)


def operator_payment(h):
    try:
        data=_body(h,3000);_operator_auth(h,data)
        if data.get('confirm')!='SIMULAR_PAGAMENTO':raise ValueError('Confirmação de simulação obrigatória.')
        job=str(data.get('id',''))
        msg=register_demo_payment(job)
        _send(h,{'ok':True,'message':msg,'id':job})
    except FileNotFoundError:_send(h,{'error':'Pedido inexistente.'},404)
    except (ValueError,TypeError) as e:_send(h,{'error':str(e)},400)
    except PermissionError:_send(h,{'error':'Código de operador incorreto para esta sessão.','session':SESSION_MARK},403)


def operator_start(h):
    try:
        data=_body(h,3000);_operator_auth(h,data)
        if data.get('confirm') not in ('AUTORIZO_PRODUCAO_COM_CUSTOS','AUTORIZO_PREMIUM_COMPLETO'):raise ValueError('Autorização exata obrigatória.')
        job=str(data.get('id',''))
        st=start_commercial_production(job)
        _send(h,{'ok':True,'id':job,'status':st['status'],'message':'Produção iniciou. Chamadas de IA podem gerar custos REAIS.'},202)
    except FileNotFoundError:_send(h,{'error':'Pedido inexistente.'},404)
    except (ValueError,RuntimeError,TypeError) as e:_send(h,{'error':str(e)},400)
    except PermissionError:_send(h,{'error':'Código de operador não corresponde à sessão ativa. Verifique o código no terminal que atende a porta 8786.','session':SESSION_MARK},403)
