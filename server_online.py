#!/usr/bin/env python3
"""StayVision V1: Checkout Pro seguro, bloqueado por padrão; lançamento explícito."""
import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
from email.parser import BytesParser
from email.policy import default as email_policy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from payments_readiness import pix_production_report, config_report, ReadinessError
from payment_reconciliation import fetch_payment, review_payment, PaymentLookupUnavailable, audit_summary
from checkout_production import gate as production_gate, public_sales_ready, build_preference, create_preference, CheckoutError
from seller_identity import check_seller_identity, require_seller_identity, SellerIdentityError
from ai_engine import run_pipeline, AIEngineError, MODES as AI_MODES, STYLES as AI_STYLES, ASPECTS as AI_ASPECTS

BASE = Path(__file__).resolve().parent
STATIC = BASE / 'static'
DATA = Path(os.getenv('STAYVISION_DATA_DIR', str(BASE / 'dados'))).resolve()
UPLOADS = DATA / 'uploads'
DELIVERIES = DATA / 'entregas'
DB = DATA / 'stayvision.db'
def ai_outputs():
    return DATA / 'ai_gerados'
AI_RENDER_LOCK = threading.Lock()
DEMO_ORDERS = os.getenv('STAYVISION_ENABLE_DEMO_ORDERS', '0') == '1'
RATE_LOCK = threading.Lock()
ATTEMPTS = {}

def rate_ok(key, limit, seconds):
    stamp = time.monotonic()
    with RATE_LOCK:
        recent = [t for t in ATTEMPTS.get(key, []) if stamp - t < seconds]
        if len(recent) >= limit:
            ATTEMPTS[key] = recent
            return False
        recent.append(stamp)
        ATTEMPTS[key] = recent
        return True

def ensure_online_storage():
    # On Railway, never silently write client images to the ephemeral container filesystem.
    if os.getenv('RAILWAY_ENVIRONMENT_NAME') or os.getenv('RAILWAY_PROJECT_ID'):
        mount = os.getenv('RAILWAY_VOLUME_MOUNT_PATH', '')
        if not mount or Path(mount).resolve() != DATA:
            raise RuntimeError('Railway: anexe um Volume e configure STAYVISION_DATA_DIR igual ao Mount Path antes do deploy.')
    DATA.mkdir(parents=True, exist_ok=True)
    probe = DATA / ('.volume-test-' + secrets.token_hex(6))
    probe.write_text('ok')
    probe.unlink()

def initialize_admin():
    username = os.getenv('STAYVISION_ADMIN_USER', '').strip()
    password = os.getenv('STAYVISION_ADMIN_PASSWORD', '')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{3,30}', username):
        raise RuntimeError('Configure STAYVISION_ADMIN_USER nas variaveis privadas da Railway.')
    if len(password) < 16 or len(password) > 128:
        raise RuntimeError('Configure STAYVISION_ADMIN_PASSWORD com pelo menos 16 caracteres nas variaveis privadas da Railway.')
    with connection() as db:
        existing = db.execute('SELECT 1 FROM users LIMIT 1').fetchone()
        if not existing:
            salt = secrets.token_hex(16)
            db.execute('INSERT INTO users(username,password_hash,password_salt) VALUES(?,?,?)',
                       (username,password_hash(password,salt),salt))
    # Password is only used on the first startup. Subsequent password changes require a reset procedure.

MAX_BODY = 70 * 1024 * 1024
MAX_IMAGE = 10 * 1024 * 1024
MAX_DELIVERY = 90 * 1024 * 1024
STATUS = ['recebido', 'aguardando_pagamento', 'em_producao', 'em_revisao', 'concluido', 'cancelado']
PAYMENT_STATUS = ['nao_iniciado', 'pendente', 'pago', 'recusado', 'estornado']
LEAD_STAGES = ['novo', 'contatado', 'interessado', 'proposta', 'cliente', 'sem_interesse']
DEFAULT_PLANS = [
    {'code':'photo', 'name':'StayVision Photo','price':49,'unit':'pedido','description':'Tratamento visual de fotografias imobiliárias','features':['Até 8 fotografias','Ajustes de cor e iluminação','Formato para anúncio e redes sociais']},
    {'code':'video', 'name':'StayVision Video','price':197,'unit':'vídeo','description':'Edição de vídeo imobiliário a partir de fotos','features':['Até 8 fotografias fornecidas','Edição e trilha licenciada','Formato vertical ou horizontal']},
    {'code':'partner', 'name':'StayVision Partner','price':697,'unit':'pacote mensal proposto','description':'Produção recorrente para profissionais e hospedagens','features':['Escopo definido antes da contratação','Acompanhamento de pedidos','Condição especial por volume']},
]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


@contextmanager
def connection():
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(exist_ok=True)
    DELIVERIES.mkdir(exist_ok=True)
    ai_outputs().mkdir(exist_ok=True)
    with connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, password_salt TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, customer_token TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, plan_code TEXT NOT NULL, plan_name TEXT NOT NULL,
            price INTEGER NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL,
            phone TEXT NOT NULL, property_type TEXT NOT NULL, city TEXT NOT NULL,
            notes TEXT NOT NULL, status TEXT NOT NULL, payment_status TEXT NOT NULL,
            admin_note TEXT NOT NULL DEFAULT '', delivery_filename TEXT NOT NULL DEFAULT '',
            payment_url TEXT NOT NULL DEFAULT '', preference_id TEXT NOT NULL DEFAULT '')''')
        db.execute('''CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            name TEXT NOT NULL, phone TEXT NOT NULL, segment TEXT NOT NULL,
            city TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '')''')
        db.execute('''CREATE TABLE IF NOT EXISTS production_jobs (
            order_id TEXT PRIMARY KEY, mode TEXT NOT NULL, state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, error_message TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(order_id) REFERENCES orders(id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS order_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL,
            name TEXT NOT NULL, stored_name TEXT NOT NULL, mime TEXT NOT NULL,
            size INTEGER NOT NULL, FOREIGN KEY(order_id) REFERENCES orders(id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS mp_checkout_registry (
            order_id TEXT PRIMARY KEY, preference_id TEXT UNIQUE,
            checkout_url TEXT NOT NULL DEFAULT '', payment_id TEXT UNIQUE,
            idempotency_key TEXT NOT NULL UNIQUE, stage TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS ai_runs (
            id TEXT PRIMARY KEY, order_id TEXT NOT NULL, mode TEXT NOT NULL,
            style TEXT NOT NULL, aspect TEXT NOT NULL DEFAULT 'horizontal', state TEXT NOT NULL, progress INTEGER NOT NULL,
            message TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id))''')
        # Process restarts must not leave orphaned jobs falsely shown as rendering.
        db.execute("UPDATE ai_runs SET state='interrompido',message='Servidor reiniciado; inicie novamente se necessário',updated_at=? WHERE state IN ('processando','na_fila')", (now(),))
        db.execute('''CREATE TABLE IF NOT EXISTS mp_webhook_audit (
            request_id TEXT PRIMARY KEY, received_at TEXT NOT NULL,
            event_type TEXT NOT NULL, payment_id TEXT NOT NULL,
            result TEXT NOT NULL)''')
        defaults = {
            'plans': DEFAULT_PLANS, 'brand_name': 'StayVision',
            'contact_whatsapp': '', 'sales_enabled': False,
            'payment_enabled': False, 'demo_mode': True
        }
        for key, value in defaults.items():
            db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))
        # O desbloqueio financeiro NÃO depende de flags armazenadas no banco;
        # somente envs explícitas e verificações do servidor podem habilitar vendas.
        for key,value in [('sales_enabled', False), ('payment_enabled', False), ('demo_mode', True)]:
            db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(value), key))


def ensure_job(db, order_id, plan_code):
    # The queue records commercial demand; no image/video generator is connected yet.
    mode = 'photo' if plan_code == 'photo' else ('video' if plan_code == 'video' else 'partner')
    stamp = now()
    db.execute('''INSERT OR IGNORE INTO production_jobs
        (order_id,mode,state,created_at,updated_at) VALUES (?,?,?,?,?)''',
        (order_id,mode,'aguardando_integracao',stamp,stamp))


def setting(key, fallback=None):
    with connection() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else fallback


def settings_public():
    opened=public_sales_ready()
    return {**{k: setting(k) for k in ('plans', 'brand_name', 'contact_whatsapp')},
            'sales_enabled':opened, 'payment_enabled':opened, 'demo_mode':not opened,
            'demo_orders_enabled': DEMO_ORDERS and not opened,
            'payment_environment':'producao' if opened else 'desativado'}


def set_setting(key, value):
    with connection() as db:
        db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (key, json.dumps(value, ensure_ascii=False)))


def mp_environment():
    return 'producao' if public_sales_ready() else 'desativado' 


def configured_mp():
    return mp_environment() == 'teste'


def load_local_config():
    # Configuração privada: nunca é enviada ao navegador e nunca deve entrar no ZIP.
    config_file = BASE / '.env.local'
    if not config_file.is_file():
        return
    for line in config_file.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key in ('MP_TEST_ACCESS_TOKEN', 'MP_PRODUCTION_ACCESS_TOKEN') and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def password_hash(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), bytes.fromhex(salt), 260000).hex()


def validate_pass(pw):
    if not isinstance(pw, str) or len(pw) < 10 or len(pw) > 128:
        raise ValueError('A senha deve ter de 10 a 128 caracteres.')


def new_session(db):
    token = secrets.token_urlsafe(36)
    expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12)).isoformat()
    db.execute('INSERT INTO sessions(token_hash,created_at,expires_at) VALUES (?,?,?)',
               (hashlib.sha256(token.encode()).hexdigest(), now(), expiry))
    return token


def image_type(data):
    if data[:3] == b'\xff\xd8\xff': return 'image/jpeg', '.jpg'
    if data[:8] == b'\x89PNG\r\n\x1a\n': return 'image/png', '.png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP': return 'image/webp', '.webp'
    return None


def safe_filename(s):
    s = Path(s.replace('\\','/')).name
    return re.sub(r'[^\w.() -]', '_', s, flags=re.UNICODE)[:95] or 'arquivo'


def parse_form(content_type, body):
    if not content_type.startswith('multipart/form-data;'):
        raise ValueError('O formulário deve enviar arquivos em multipart/form-data.')
    msg = BytesParser(policy=email_policy).parsebytes(
        b'MIME-Version: 1.0\r\nContent-Type: ' + content_type.encode() + b'\r\n\r\n' + body)
    if not msg.is_multipart():
        raise ValueError('Formato de upload inválido.')
    fields, files = {}, []
    for item in msg.iter_parts():
        disp = item.get('Content-Disposition','')
        if 'form-data' not in disp: continue
        key = item.get_param('name', header='Content-Disposition')
        filename = item.get_filename()
        payload = item.get_payload(decode=True)
        if not key or payload is None: continue
        if filename is None:
            if len(payload) > 10000: raise ValueError('Campo excede o limite permitido.')
            fields[key] = payload.decode('utf-8', errors='replace').strip()
        else:
            files.append((key, safe_filename(filename), payload))
    return fields, files


def read_json(body):
    try:
        value = json.loads(body.decode('utf-8'))
        if not isinstance(value, dict): raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise ValueError('JSON inválido.')


def order_out(row, private=False):
    d = dict(row)
    if not private:
        for key in ('name', 'email', 'phone', 'admin_note', 'preference_id', 'customer_token'):
            d.pop(key, None)
        if not setting('payment_enabled'):
            d['payment_url'] = ''
    return d


def verify_mp_signature(headers, data_id):
    secret = os.getenv('MP_WEBHOOK_SECRET', '')
    sig = headers.get('x-signature','')
    req_id = headers.get('x-request-id','')
    parts = dict(chunk.strip().split('=',1) for chunk in sig.split(',') if '=' in chunk)
    ts, actual = parts.get('ts',''), parts.get('v1','')
    if not (secret and ts and req_id and actual and data_id): return False
    # Mercado Pago documentation: id:{data.id};request-id:{x-request-id};ts:{ts};
    template = f'id:{str(data_id).lower()};request-id:{req_id};ts:{ts};'
    digest = hmac.new(secret.encode(), template.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, actual)


def mp_request(method, path, payload=None):
    token = os.getenv('MP_TEST_ACCESS_TOKEN', '')
    if not token: raise ValueError('Integração Mercado Pago não configurada.')
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request('https://api.mercadopago.com' + path, data=data, method=method,
        headers={'Authorization':'Bearer '+token, 'Content-Type':'application/json',
                 'X-Idempotency-Key':secrets.token_hex(16)})
    try:
        with urllib.request.urlopen(req, timeout=14) as response:
            return json.loads(response.read(2*1024*1024))
    except urllib.error.HTTPError as e:
        raise ValueError('Mercado Pago retornou erro HTTP '+str(e.code)) from e


def check_pix_test_availability():
    """Consulta a lista de meios anunciados pela API; nao garante exibicao no Checkout Pro."""
    if not configured_mp():
        raise ValueError('Credencial de TESTE do Mercado Pago nao configurada.')
    methods = mp_request('GET', '/v1/payment_methods')
    if not isinstance(methods, list):
        raise ValueError('A API retornou uma lista de meios de pagamento inesperada.')
    pix = [m for m in methods if isinstance(m, dict) and
           (str(m.get('id', '')).lower() == 'pix' or
            (m.get('payment_type_id') == 'bank_transfer' and 'pix' in str(m.get('name', '')).lower()))]
    # Nao enviar a resposta original nem qualquer credencial ao browser.
    return {'environment': 'teste', 'pix_listed': bool(pix),
            'pix_methods': [{'id': str(m.get('id', ''))[:40],
                             'name': str(m.get('name', ''))[:60]} for m in pix[:5]],
            'checkout_guaranteed': False,
            'message': ('A API lista Pix para esta credencial, mas isso nao garante sua exibicao no Sandbox.'
                        if pix else
                        'Pix nao foi listado pela API para esta credencial de teste. A exibicao depende do Mercado Pago.')}



def prod_credential_configured():
    # Credencial usada SOMENTE para consultas GET protegidas pelo login admin.
    return bool(os.getenv('MP_PRODUCTION_ACCESS_TOKEN', '').strip())


def check_pix_production_availability():
    # Nao utiliza a credencial para criar preferencia, cobrar, atualizar pedidos ou enviar Pix.
    return pix_production_report()


def valid_mp_checkout_url(url):
    try:
        u = urllib.parse.urlsplit(url)
        return (u.scheme == 'https' and (u.hostname == 'mercadopago.com.br' or
                u.hostname.endswith('.mercadopago.com.br')) and not u.username and not u.password)
    except (TypeError, ValueError, AttributeError):
        return False


def preflight_checkout_order(db, order_id):
    row=db.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
    if not row: raise CheckoutError('Pedido não encontrado.')
    order=dict(row)
    build_preference(order,os.getenv('STAYVISION_PUBLIC_URL',''))
    return order


def stage_checkout(order_id):
    """Reserve the attempt BEFORE calling MP, so failure cannot auto-reissue a charge link."""
    if not production_gate(order_id):
        raise CheckoutError('Checkout real bloqueado. Nenhuma cobrança será criada.')
    try:
        require_seller_identity()
    except SellerIdentityError as exc:
        raise CheckoutError(str(exc)) from None
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        order=preflight_checkout_order(db,order_id)
        old=db.execute('SELECT * FROM mp_checkout_registry WHERE order_id=?',(order_id,)).fetchone()
        if old:
            if old['stage']=='ready':
                return {'preference_id':old['preference_id'],'checkout_url':old['checkout_url'], 'reused':True}
            raise CheckoutError('Já existe tentativa de checkout pendente. Verifique no Mercado Pago antes de repetir.')
        idem=secrets.token_hex(20)
        t=now()
        db.execute('INSERT INTO mp_checkout_registry(order_id,idempotency_key,stage,created_at,updated_at) VALUES (?,?,?,?,?)',
                   (order_id,idem,'creating',t,t))
    # If network fails or response is ambiguous, reservation remains 'creating' permanently.
    res=create_preference(order,idempotency_key=idem)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT * FROM mp_checkout_registry WHERE order_id=?',(order_id,)).fetchone()
        if not current or current['stage']!='creating' or current['idempotency_key']!=idem:
            raise CheckoutError('Registro de tentativa foi alterado; revisar antes de prosseguir.')
        db.execute('UPDATE mp_checkout_registry SET stage=?,preference_id=?,checkout_url=?,updated_at=? WHERE order_id=?',
                   ('ready',res['preference_id'],res['checkout_url'],now(),order_id))
        db.execute('UPDATE orders SET preference_id=?,payment_url=?,payment_status=?,updated_at=? WHERE id=?',
                   (res['preference_id'],res['checkout_url'],'pendente',now(),order_id))
    return {**res,'reused':False}


def settle_payment_approved(payment):
    """Strict idempotent settlement, not enabled by default; only for registered order."""
    if os.getenv('STAYVISION_MP_AUTO_CONFIRM','0') != '1': return False
    oid=str(payment.get('external_reference',''))
    # A previously issued preference may be paid after public sales are paused.
    # Verify the stored preference instead of requiring that new checkouts be enabled.
    pid=str(payment.get('id',''))
    if not re.fullmatch(r'[0-9]{1,30}',pid): return False
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        registry=db.execute('SELECT * FROM mp_checkout_registry WHERE order_id=?',(oid,)).fetchone()
        rec=db.execute('SELECT id,price,preference_id,plan_code,payment_status FROM orders WHERE id=?',(oid,)).fetchone()
        if not registry or registry['stage']!='ready' or not rec: return False
        if rec['plan_code'] not in ('photo','video','partner'): return False
        if registry['preference_id']!=rec['preference_id']: return False
        if registry['payment_id'] and registry['payment_id']!=pid: return False
        if rec['payment_status'] in ('estornado','recusado'): return False
        result=review_payment(payment,dict(rec),collector_id=os.getenv('MP_PRODUCTION_COLLECTOR_ID',''))
        if result != 'aprovado_validado_sem_baixa': return False
        other=db.execute('SELECT order_id FROM mp_checkout_registry WHERE payment_id=?',(pid,)).fetchone()
        if other and other['order_id']!=oid: return False
        db.execute('UPDATE mp_checkout_registry SET payment_id=?,updated_at=? WHERE order_id=?',(pid,now(),oid))
        db.execute("UPDATE orders SET payment_status='pago',updated_at=? WHERE id=?",(now(),oid))
        ensure_job(db,oid,rec['plan_code'])
        # Never mark delivery as complete here: fulfillment requires human review.
    if os.getenv('STAYVISION_AI_AUTO_PROCESS','0') == '1':
        try: launch_ai_after_confirmed_payment(oid, rec['plan_code'])
        except Exception as exc:
            print('[StayVision AI] Falha ao agendar pós-pagamento:',type(exc).__name__, file=sys.stderr)
    return True


def settle_payment_reversal(payment):
    """Record an authenticated full reversal/chargeback for the matching MP payment.

    Caller MUST GET payment from MP. We never create a refund here, only stop access
    to a delivery already paid for when MP has reversed the charge.
    """
    if os.getenv('STAYVISION_MP_AUTO_CONFIRM','0') != '1': return False
    if payment.get('status') not in ('refunded','charged_back'): return False
    if payment.get('live_mode') is not True: return False
    oid=str(payment.get('external_reference',''))
    pid=str(payment.get('id',''))
    if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',oid) or not re.fullmatch(r'[0-9]{1,30}',pid):
        return False
    # Do not trust a webhook body for payment fields; caller fetched these from MP.
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        registry=db.execute('SELECT * FROM mp_checkout_registry WHERE order_id=?',(oid,)).fetchone()
        rec=db.execute('SELECT id,price,preference_id,payment_status FROM orders WHERE id=?',(oid,)).fetchone()
        if not registry or registry['stage']!='ready' or not rec: return False
        if registry['preference_id']!=rec['preference_id'] or not rec['preference_id']: return False
        if registry['payment_id'] and registry['payment_id']!=pid: return False
        if payment.get('currency_id')!='BRL' or str(payment.get('collector_id',''))!=os.getenv('MP_PRODUCTION_COLLECTOR_ID',''):
            return False
        if str(payment.get('preference_id',''))!=registry['preference_id'] or str(payment.get('external_reference',''))!=oid:
            return False
        try:
            from decimal import Decimal
            amount=Decimal(str(payment['transaction_amount']))
            price=Decimal(str(rec['price']))
            if not amount.is_finite() or price<=0 or amount!=price: return False
        except (KeyError,ValueError,TypeError,ArithmeticError):
            return False
        other=db.execute('SELECT order_id FROM mp_checkout_registry WHERE payment_id=?',(pid,)).fetchone()
        if other and other['order_id']!=oid: return False
        db.execute('UPDATE mp_checkout_registry SET payment_id=?,updated_at=? WHERE order_id=?',(pid,now(),oid))
        db.execute('UPDATE orders SET payment_status=?,updated_at=? WHERE id=?',('estornado',now(),oid))
    return True




def launch_ai_after_confirmed_payment(order_id, plan_code):
    """Opt-in: verified payments may pre-render files; NEVER deliver to client."""
    if os.getenv('STAYVISION_AI_AUTO_PROCESS','0') != '1': return False
    mode = {'photo':'photo','video':'video','partner':'complete'}.get(plan_code)
    if mode is None: return False
    with connection() as db:
        done=db.execute('SELECT 1 FROM ai_runs WHERE order_id=? LIMIT 1',(order_id,)).fetchone()
        files=db.execute('SELECT COUNT(*) FROM order_files WHERE order_id=?',(order_id,)).fetchone()[0]
    if done or not 1<=files<=12: return False
    if not AI_RENDER_LOCK.acquire(blocking=False): return False
    try:
        rid=secrets.token_hex(12)
        with connection() as db:
            db.execute('INSERT INTO ai_runs(id,order_id,mode,style,aspect,state,progress,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (rid,order_id,mode,'natural','horizontal','na_fila',0,'Processamento automático após Pix aprovado',now(),now()))
        threading.Thread(target=run_ai_in_background,args=(rid,order_id,mode,'natural','horizontal'),daemon=True).start()
    except Exception:
        AI_RENDER_LOCK.release()
        raise
    return True

def run_ai_in_background(run_id, order_id, mode, style, aspect):
    """Only starts after AI_RENDER_LOCK is reserved by an authenticated admin."""
    try:
        with connection() as db:
            db.execute("UPDATE ai_runs SET state='processando',message='Preparando fotografias',progress=1,updated_at=? WHERE id=?",(now(),run_id))
            images=db.execute('SELECT stored_name FROM order_files WHERE order_id=? ORDER BY id LIMIT 13',(order_id,)).fetchall()
        if len(images)>12: raise AIEngineError('O limite de processamento é de 12 fotos.')
        files=[]
        for row in images:
            filename=str(row['stored_name'])
            if not re.fullmatch(r'[A-Za-z0-9._-]{3,100}',filename): raise AIEngineError('Nome de arquivo inválido.')
            files.append(UPLOADS/order_id/filename)
        if not files: raise AIEngineError('Este pedido não possui fotografias.')
        def progress(percent,msg):
            with connection() as db:
                db.execute('UPDATE ai_runs SET progress=?,message=?,updated_at=? WHERE id=?',
                           (min(99,int(percent)),str(msg)[:180],now(),run_id))
        run_pipeline(files,ai_outputs()/order_id/run_id,mode,style,aspect,progress)
        with connection() as db:
            db.execute("UPDATE ai_runs SET state='pronto',progress=100,message='Produção pronta para revisão',updated_at=? WHERE id=?",(now(),run_id))
            db.execute("UPDATE production_jobs SET state='revisao',updated_at=? WHERE order_id=?",(now(),order_id))
    except Exception as exc:
        # Detailed failure stays in Railway logs; responses show only technical class/general message.
        print('[StayVision AI]',type(exc).__name__,str(exc)[:350],file=sys.stderr,flush=True)
        message=str(exc)[:190] if isinstance(exc,AIEngineError) else 'Erro técnico de renderização. Confira logs na Railway.'
        try:
            with connection() as db:
                db.execute("UPDATE ai_runs SET state='falhou',message=?,updated_at=? WHERE id=?",(message,now(),run_id))
        except Exception: pass
    finally:
        AI_RENDER_LOCK.release()


def ai_run_summary(row):
    out=dict(row)
    out['artifacts']=[]
    out['previews']=[]
    out['quality_warnings']=[]
    if out['state']=='pronto':
        manifest=ai_outputs()/out['order_id']/out['id']/'manifest.json'
        if manifest.is_file():
            try:
                result=json.loads(manifest.read_text(encoding='utf-8'))
                out['artifacts']=result.get('artifacts',[])
                out['previews']=[p['file'] for p in result.get('photos',[]) if re.fullmatch(r'\d{2}_stayvision\.jpg',p.get('file',''))]
                out['quality_warnings']=[f"Foto {i+1}: {p['quality_notice']}" for i,p in enumerate(result.get('photos',[])) if p.get('quality_notice')][:12]
            except (OSError,ValueError): pass
    return out

class Handler(BaseHTTPRequestHandler):
    server_version = 'StayVision/1.0'
    def log_message(self, fmt, *args):
        # Nunca registrar tokens privados de acompanhamento que aparecem na URL.
        print('[StayVision]', self.command, urllib.parse.urlsplit(self.path).path, flush=True)

    def send(self, status, body, mime='application/json; charset=utf-8', headers=None):
        if isinstance(body, (dict,list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if headers:
            for k,v in headers.items(): self.send_header(k,v)
        self.end_headers()
        if self.command != 'HEAD': self.wfile.write(body)

    def fail(self, code, msg):
        self.send(code, {'error':msg})

    def user(self):
        cookie = self.headers.get('Cookie','')
        match = re.search(r'(?:^|;\s*)stayvision_session=([^;]+)', cookie)
        if not match: return False
        digest = hashlib.sha256(match.group(1).encode()).hexdigest()
        with connection() as db:
            r = db.execute('SELECT expires_at FROM sessions WHERE token_hash=?', (digest,)).fetchone()
        return bool(r and r['expires_at'] > now())

    def require_admin(self):
        if self.user(): return True
        self.fail(401, 'Acesse o painel com sua senha.')
        return False

    def origin_ok(self):
        # Prevent cross-origin form submission and CSRF; same-site cookie alone is not enough.
        origin = self.headers.get('Origin')
        if not origin: return True  # For script callers without browser cookies.
        url = os.getenv('STAYVISION_PUBLIC_URL', '').rstrip('/')
        if not url.startswith('https://'):
            return False
        return origin == url

    def incoming(self, limit=MAX_BODY):
        length = int(self.headers.get('Content-Length','0'))
        if length <= 0 or length > limit:
            raise ValueError('Tamanho de envio inválido ou acima do limite.')
        return self.rfile.read(length)

    def file_response(self, file, attachment=False, original=None, trusted=False):
        if not file.is_file(): return self.fail(404, 'Arquivo não encontrado.')
        mime = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
        extra = {'Content-Disposition': 'attachment; filename="'+safe_filename(original or file.name).replace('"','')+'"'} if attachment else None
        if mime == 'text/html' and not trusted: mime='application/octet-stream'
        self.send(200, file.read_bytes(), mime, extra)

    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        p = urllib.parse.urlsplit(self.path)
        path = p.path
        q = urllib.parse.parse_qs(p.query)
        if path == '/api/public/config': return self.send(200, settings_public())
        if path == '/api/health':
            try:
                with connection() as db: db.execute('SELECT 1').fetchone()
                return self.send(200, {'ok':True,'mode':'vendas' if public_sales_ready() else 'pedidos_demo','payments':public_sales_ready()})
            except sqlite3.Error:
                return self.fail(503,'Banco indisponivel')
        if path == '/api/admin/me':
            with connection() as db:
                setup = db.execute('SELECT COUNT(*) as c FROM users').fetchone()['c'] > 0
            return self.send(200, {'authenticated':bool(self.user()), 'initialized': setup})
        if path == '/api/admin/ai/status':
            if not self.require_admin(): return
            oid=q.get('id',[''])[0]
            if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',oid): return self.fail(400,'Pedido inválido.')
            with connection() as db:
                exists=db.execute('SELECT id FROM orders WHERE id=?',(oid,)).fetchone()
                rows=db.execute('SELECT * FROM ai_runs WHERE order_id=? ORDER BY created_at DESC LIMIT 8',(oid,)).fetchall()
            if not exists: return self.fail(404,'Pedido não encontrado.')
            return self.send(200,{'runs':[ai_run_summary(row) for row in rows],
                'methods':{'photos':'melhoria fotográfica local','video':'animação cinematográfica MP4',
                           'spatial':'simulação espacial 2.5D, não é reconstrução 3D'}})
        if path == '/api/admin/ai/file':
            if not self.require_admin(): return
            rid=q.get('run',[''])[0]; filename=q.get('name',[''])[0]
            if not re.fullmatch(r'[a-f0-9]{24}',rid): return self.fail(400,'Execução inválida.')
            if not re.fullmatch(r'(?:photos/)?[A-Za-z0-9._-]{3,100}',filename):
                return self.fail(400,'Arquivo inválido.')
            with connection() as db:
                run=db.execute("SELECT order_id,state FROM ai_runs WHERE id=?",(rid,)).fetchone()
            if not run or run['state']!='pronto': return self.fail(404,'Arquivo ainda não disponível.')
            allowed=ai_outputs()/run['order_id']/rid
            file=allowed/filename
            if not file.resolve().is_relative_to(allowed.resolve()) or not file.is_file():
                return self.fail(404,'Arquivo não localizado.')
            manifest=allowed/'manifest.json'
            try:
                artifacts=json.loads(manifest.read_text(encoding='utf-8')).get('artifacts',[])
            except (ValueError,OSError): return self.fail(404,'Manifesto indisponível.')
            photo_allowed=re.fullmatch(r'photos/\d{2}_stayvision\.jpg',filename) is not None
            if filename not in [a['name'] for a in artifacts] and not photo_allowed:
                return self.fail(403,'Arquivo não publicado neste processamento.')
            mime=mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            size=file.stat().st_size
            self.send_response(200)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(size))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; sandbox")
            if not photo_allowed:
                self.send_header('Content-Disposition','attachment; filename="'+file.name+'"')
            self.end_headers()
            if self.command!='HEAD':
                try:
                    with file.open('rb') as content:
                        shutil.copyfileobj(content,self.wfile,length=128*1024)
                except (BrokenPipeError,ConnectionResetError): pass
            return
        if path == '/api/admin/overview':
            if not self.require_admin(): return
            with connection() as db:
                rows = [dict(x) for x in db.execute('SELECT * FROM orders ORDER BY created_at DESC').fetchall()]
            paid_total = sum(r['price'] for r in rows if r['payment_status']=='pago')
            return self.send(200, {'orders':rows,'total':len(rows), 'paid_total':paid_total,
                                   'received':sum(r['status']=='recebido' for r in rows),
                                   'in_progress':sum(r['status'] in ('em_producao','em_revisao') for r in rows),
                                   'completed':sum(r['status']=='concluido' for r in rows)})
        if path == '/api/admin/operations':
            if not self.require_admin(): return
            with connection() as db:
                jobs = [dict(x) for x in db.execute('''SELECT o.id,o.created_at,o.updated_at,o.name,o.plan_code,
                    o.plan_name,o.price,o.payment_status,o.status,o.delivery_filename,
                    j.state AS ai_state,j.mode AS ai_mode,j.attempts,j.error_message,j.updated_at AS ai_updated_at
                    FROM orders o LEFT JOIN production_jobs j ON j.order_id=o.id
                    ORDER BY o.created_at DESC''')]
            breakdown = {'aguardando_pagamento':0,'aguardando_integracao':0,'processando':0,
                         'revisao':0,'falhou':0,'entregue':0}
            for job in jobs:
                if job['payment_status'] != 'pago': breakdown['aguardando_pagamento'] += 1
                elif job['delivery_filename'] and job['status']=='concluido': breakdown['entregue'] += 1
                else: breakdown[job['ai_state'] if job['ai_state'] in breakdown else 'aguardando_integracao'] += 1
            return self.send(200, {'jobs':jobs,'counts':breakdown,
                'engine_connected':True, 'payment_gateway_configured':bool(os.getenv('MP_PRODUCTION_ACCESS_TOKEN')),
                'payments_enabled':bool(setting('payment_enabled')),
                'sales_enabled':bool(setting('sales_enabled'))})
        if path == '/api/admin/leads':
            if not self.require_admin(): return
            with connection() as db:
                rows = [dict(x) for x in db.execute('SELECT * FROM leads ORDER BY updated_at DESC')]
            return self.send(200, {'leads':rows})
        if path == '/api/admin/pix-diagnostic':
            if not self.require_admin(): return
            if not configured_mp(): return self.fail(409, 'Configure o Access Token de TESTE primeiro.')
            try:
                return self.send(200, check_pix_test_availability())
            except ValueError as exc:
                return self.fail(502, str(exc))
        if path == '/api/admin/checkout-readiness':
            if not self.require_admin(): return
            mode=os.getenv('STAYVISION_MP_CHECKOUT_MODE','locked')
            public=public_sales_ready()
            return self.send(200, {'mode':mode if mode in ('locked','restricted','public') else 'locked',
                'orders_publicly_open':public,'checkout_real_enabled':public,
                'single_order_gate_ready':production_gate(os.getenv('STAYVISION_MP_ALLOWED_ORDER_ID','')) and mode=='restricted',
                'seller_identity_check_required':True,
                'production_token_present':prod_credential_configured(),
                'collector_id_configured':bool(re.fullmatch(r'[0-9]{1,30}',os.getenv('MP_PRODUCTION_COLLECTOR_ID',''))),
                'webhook_secret_configured':bool(os.getenv('MP_WEBHOOK_SECRET','').strip()),
                'auto_confirm_enabled':os.getenv('STAYVISION_MP_AUTO_CONFIRM','0')=='1',
                'message':'Vendas públicas prontas.' if public else 'Checkout público BLOQUEADO até lançamento explícito.'})
        if path == '/api/admin/seller-identity':
            if not self.require_admin(): return
            if not rate_ok(('admin-seller-identity',self.client_address[0]),6,3600):
                return self.fail(429,'Limite de verificações atingido. Aguarde.')
            try:
                return self.send(200,check_seller_identity())
            except SellerIdentityError as exc:
                return self.fail(502,str(exc))
        if path == '/api/admin/seller-identity-full':
            # Diagnóstico explicitamente solicitado, privado e somente leitura.
            # Não inclui Access Token, e-mail ou outros dados da conta na resposta.
            if not self.require_admin(): return
            if not rate_ok(('admin-seller-identity-full',self.client_address[0]),3,3600):
                return self.fail(429,'Limite de consultas do ID completo atingido. Aguarde uma hora.')
            try:
                return self.send(200,check_seller_identity(show_full_id=True))
            except SellerIdentityError as exc:
                return self.fail(502,str(exc))
        if path == '/api/admin/checkout-preview':
            if not self.require_admin(): return
            oid=q.get('id',[''])[0]
            if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',oid): return self.fail(400,'Código do pedido inválido.')
            try:
                with connection() as db:
                    order=preflight_checkout_order(db,oid)
                    existing=db.execute('SELECT stage,preference_id FROM mp_checkout_registry WHERE order_id=?',(oid,)).fetchone()
                payload=build_preference(order,os.getenv('STAYVISION_PUBLIC_URL',''))
                return self.send(200,{'dry_run':True,'charge_created':False,
                    'order_id':oid,'plan':order['plan_code'],'amount_brl':order['price'],'currency':'BRL',
                    'preference_linked':bool(existing and existing['stage']=='ready'),
                    'checkout_locked':not production_gate(oid),
                    'payment_methods':'Definidos pelo Mercado Pago; Pix nao garantido no checkout',
                    'return_host':urllib.parse.urlsplit(payload['back_urls']['success']).hostname})
            except CheckoutError as exc: return self.fail(409,str(exc))
        if path == '/api/admin/checkout-observe':
            if not self.require_admin(): return
            oid=q.get('id',[''])[0]
            pid=q.get('payment_id',[''])[0]
            if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',oid) or not re.fullmatch(r'[0-9]{1,30}',pid):
                return self.fail(400,'Pedido ou identificador do pagamento inválido.')
            if not rate_ok(('admin-payment-inspect',self.client_address[0]),15,3600):
                return self.fail(429,'Limite de consultas excedido.')
            with connection() as db:
                order=db.execute('SELECT id,price,preference_id,plan_code,payment_status FROM orders WHERE id=?',(oid,)).fetchone()
                registry=db.execute('SELECT stage,preference_id,payment_id FROM mp_checkout_registry WHERE order_id=?',(oid,)).fetchone()
            if not order or not registry or registry['stage']!='ready' or registry['preference_id']!=order['preference_id']:
                return self.fail(409,'Não há preferência própria válida vinculada a esse pedido.')
            try:
                payment=fetch_payment(pid)
            except PaymentLookupUnavailable:
                return self.fail(502,'Não foi possível consultar o pagamento; tente novamente mais tarde.')
            result=review_payment(payment,dict(order),collector_id=os.getenv('MP_PRODUCTION_COLLECTOR_ID',''))
            if registry['payment_id'] and registry['payment_id']!=pid:
                result='pagamento_ja_vinculado_a_outro_id'
            return self.send(200,{'order_id':oid,'payment_id':pid,'result':result,
                'payment_status':payment.get('status','') if payment else 'nao_encontrado',
                'order_payment_status':order['payment_status'],'updated':False,
                'message':'Consulta somente leitura. Não libera produção nem confirma pedido.'})
        if path == '/api/admin/mp-readiness':
            if not self.require_admin(): return
            return self.send(200, config_report())
        if path == '/api/admin/pix-production-diagnostic':
            if not self.require_admin(): return
            if not prod_credential_configured():
                return self.fail(409, 'Credencial de producao ausente. Configure MP_PRODUCTION_ACCESS_TOKEN nas variaveis privadas da Railway.')
            try:
                return self.send(200, check_pix_production_availability())
            except ReadinessError as exc:
                return self.fail(502, str(exc))
        if path == '/api/admin/webhook-status':
            if not self.require_admin(): return
            with connection() as db:
                rows = [dict(r) for r in db.execute('''SELECT received_at,event_type,result FROM mp_webhook_audit
                    ORDER BY received_at DESC LIMIT 10''')]
                count = db.execute('SELECT COUNT(*) FROM mp_webhook_audit').fetchone()[0]
            return self.send(200, {'webhook_secret_configured': bool(os.getenv('MP_WEBHOOK_SECRET','').strip()),
                'events_received': count,'recent_events':rows,'checkout_enabled':public_sales_ready(),
                'orders_approved_from_webhooks':os.getenv('STAYVISION_MP_AUTO_CONFIRM','0')=='1',
                'mode':'automatico_validado' if os.getenv('STAYVISION_MP_AUTO_CONFIRM','0')=='1' else 'consulta_readonly',
                'reconciliation':audit_summary(rows),
                'collector_configured':bool(re.fullmatch(r'[0-9]{1,30}', os.getenv('MP_PRODUCTION_COLLECTOR_ID','')))})
        if path == '/api/admin/settings':
            if not self.require_admin(): return
            return self.send(200, {**settings_public(),'mercadopago_ready':public_sales_ready(),
                                   'public_url':bool(os.getenv('STAYVISION_PUBLIC_URL')),
                                   'pix_production_diagnostic_ready':prod_credential_configured()})
        match = re.fullmatch(r'/api/admin/orders/([A-Z0-9-]+)', path)
        if match:
            if not self.require_admin(): return
            with connection() as db:
                order = db.execute('SELECT * FROM orders WHERE id=?', (match.group(1),)).fetchone()
                files = [dict(x) for x in db.execute('SELECT id,name,mime,size FROM order_files WHERE order_id=?', (match.group(1),))]
            return self.send(200, {'order':dict(order),'files':files} if order else {'error':'Pedido inexistente.'})
        match = re.fullmatch(r'/api/admin/files/(\d+)', path)
        if match:
            if not self.require_admin(): return
            with connection() as db:
                f = db.execute('SELECT * FROM order_files WHERE id=?', (match.group(1),)).fetchone()
            if not f: return self.fail(404, 'Arquivo não encontrado.')
            return self.file_response(UPLOADS/f['order_id']/f['stored_name'], original=f['name'])
        match = re.fullmatch(r'/api/client/order', path)
        if match:
            token = q.get('token',[''])[0]
            if len(token)<30: return self.fail(403, 'Link de acompanhamento inválido.')
            with connection() as db:
                order = db.execute('SELECT * FROM orders WHERE customer_token=?', (token,)).fetchone()
                if not order: return self.fail(404, 'Pedido não encontrado.')
                num = db.execute('SELECT COUNT(*) c FROM order_files WHERE order_id=?',(order['id'],)).fetchone()['c']
            return self.send(200, {'order':order_out(order),'image_count':num,'delivery_ready':bool(order['delivery_filename']),
                                   'checkout_available': public_sales_ready() and order['payment_status'] in ('nao_iniciado','pendente'),
                                   'payment_environment':mp_environment()})
        if path == '/api/client/delivery':
            token = q.get('token',[''])[0]
            with connection() as db:
                order = db.execute('SELECT * FROM orders WHERE customer_token=?', (token,)).fetchone()
            if not order or not order['delivery_filename']:
                return self.fail(404, 'Material ainda não disponível.')
            if order['payment_status'] != 'pago':
                return self.fail(403, 'Entrega liberada após confirmação de pagamento.')
            return self.file_response(DELIVERIES/order['delivery_filename'], attachment=True,
                                      original=order['delivery_filename'].split('_',1)[-1])
        if path == '/retorno':
            # Browser redirect is never payment proof. No IDs or tokens in return page.
            html='''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>StayVision • Pagamento em análise</title><body style="font:16px system-ui;max-width:680px;margin:12vh auto;padding:24px;color:#143925"><h1>StayVision</h1><h2>Seu pagamento está sendo verificado.</h2><p>O retorno do checkout não confirma o pagamento. Aguarde a confirmação do Mercado Pago, validada pela StayVision.</p><p>Use o link privado de acompanhamento que recebeu ao enviar seu pedido.</p><a href="/">Voltar ao site</a></body></html>'''
            return self.send(200,html,'text/html; charset=utf-8')
        routes = {'/':'index.html','/index.html':'index.html',
                  '/painel':'painel.html','/painel.html':'painel.html',
                  '/operacoes':'operacoes.html','/operacoes.html':'operacoes.html',
                  '/acompanhar':'acompanhar.html','/acompanhar.html':'acompanhar.html'}
        if path in routes:
            return self.file_response(STATIC/routes[path], trusted=True)
        if path.startswith('/static/'):
            relative = path[len('/static/'):]
            candidate = (STATIC / relative).resolve()
            if candidate != STATIC and STATIC in candidate.parents:
                return self.file_response(candidate, trusted=True)
        return self.fail(404,'Página não encontrada.')

    def mp_webhook_diagnostic(self):
        from payments_readiness import valid_webhook_signature
        import urllib.parse
        secret = os.getenv('MP_WEBHOOK_SECRET', '').strip()
        if not secret:
            return self.fail(503, 'Diagnóstico de webhook ainda não configurado.')
        if self.headers.get('Origin'):
            return self.fail(403, 'Origem de navegador não autorizada.')
        if self.headers.get('Content-Type','').split(';',1)[0].strip().lower() != 'application/json':
            return self.fail(415, 'Tipo de conteúdo inválido.')
        parts = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        pid_list = params.get('data.id', [])
        event_type = params.get('type', [])
        if len(pid_list)!=1 or len(event_type)!=1 or event_type[0]!='payment':
            return self.fail(400, 'Parâmetros do webhook inválidos.')
        pid = pid_list[0]
        reqid = self.headers.get('X-Request-Id', '')
        signature = self.headers.get('X-Signature', '')
        if not valid_webhook_signature(secret,signature,reqid,pid):
            return self.fail(401, 'Assinatura inválida.')
        try:
            raw = self.incoming(16384)
            body = json.loads(raw)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return self.fail(400, 'Corpo inválido.')
        if not isinstance(body,dict) or body.get('type')!='payment' or not isinstance(body.get('data'),dict):
            return self.fail(400, 'Evento inválido.')
        if str(body['data'].get('id',''))!=pid:
            return self.fail(400, 'Identificador divergente.')
        if not str(body.get('action','')).startswith('payment.'):
            return self.fail(400, 'Ação inválida.')
        # Duplicatas são idempotentes (nenhuma consulta desnecessária).
        with connection() as db:
            existing = db.execute('SELECT result FROM mp_webhook_audit WHERE request_id=?',
                                  (reqid[:128],)).fetchone()
        if existing:
            return self.send(200, {'ok':True,'already_recorded':True,'payment_updated':False})
        # O simulador pode enviar IDs sem pagamento real: 404 é um diagnóstico,
        # nunca aprovação. A API externa é fonte autoritativa, não o webhook.
        remote_payment = None
        if os.getenv('MP_PRODUCTION_ACCESS_TOKEN', '').strip():
            try:
                remote_payment = fetch_payment(pid)
            except PaymentLookupUnavailable:
                # 503 permite reenvio posterior quando a API falhar.
                return self.fail(503, 'Consulta de pagamento temporariamente indisponível.')
            order = None
            if remote_payment and re.fullmatch(r'SV-[A-Z0-9-]{5,40}',
                    str(remote_payment.get('external_reference',''))):
                with connection() as db:
                    rec = db.execute('SELECT id, price, preference_id FROM orders WHERE id=?',
                              (str(remote_payment['external_reference']),)).fetchone()
                if rec: order=dict(rec)
            result = review_payment(remote_payment, order,
                    collector_id=os.getenv('MP_PRODUCTION_COLLECTOR_ID',''))
        else:
            result = 'assinatura_validada_sem_consulta'
        # Etapa 7: liquidação estritamente condicionada a uma preferência emitida
        # pelo próprio backend e a habilitação explícita. Por padrão, NÃO baixa.
        payment_updated=False
        if remote_payment is not None:
            if result == 'aprovado_validado_sem_baixa':
                payment_updated=settle_payment_approved(remote_payment)
                if payment_updated: result='aprovado_baixa_validada'
            elif remote_payment.get('status') in ('refunded','charged_back'):
                payment_updated=settle_payment_reversal(remote_payment)
                if payment_updated: result='estorno_validado'
        with connection() as db:
            db.execute('''INSERT OR IGNORE INTO mp_webhook_audit
                (request_id,received_at,event_type,payment_id,result) VALUES(?,?,?,?,?)''',
                (reqid[:128],now(),str(body['action'])[:50],pid,result))
        return self.send(200, {'ok':True,'accepted_for_diagnostics':True,
                               'payment_updated':payment_updated,'reconciliation_recorded':True})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        # Mercado Pago server-to-server requests have no browser Origin header.
        # HMAC obrigatório; API GET de pagamento caso token de produção esteja configurado.
        # Jamais inicia uma cobrança ou altera pagamento do pedido.
        if path == '/api/mp/webhook':
            return self.mp_webhook_diagnostic()
        if not self.origin_ok(): return self.fail(403,'Origem inválida.')
        try:
            if path == '/api/admin/ai/start':
                if not self.require_admin(): return
                if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':
                    return self.fail(415,'Envie JSON.')
                if not rate_ok(('admin-ai-render',self.client_address[0]),12,3600):
                    return self.fail(429,'Limite temporário de renderizações atingido.')
                data=read_json(self.incoming(2048))
                oid=str(data.get('id','')).strip()
                mode=str(data.get('mode','photo')); style=str(data.get('style','natural')); aspect=str(data.get('aspect','horizontal'))
                if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',oid) or mode not in AI_MODES or style not in AI_STYLES or aspect not in AI_ASPECTS:
                    return self.fail(400,'Pedido, modo ou estilo inválido.')
                with connection() as db:
                    has=db.execute('SELECT id FROM orders WHERE id=?',(oid,)).fetchone()
                    cnt=db.execute('SELECT COUNT(*) FROM order_files WHERE order_id=?',(oid,)).fetchone()[0]
                    active=db.execute("SELECT id FROM ai_runs WHERE order_id=? AND state IN ('processando','na_fila')",(oid,)).fetchone()
                if not has: return self.fail(404,'Pedido não localizado.')
                if cnt<1 or cnt>12: return self.fail(409,'São necessárias entre 1 e 12 fotos no pedido.')
                if active: return self.fail(409,'Este pedido já está sendo processado.')
                if not AI_RENDER_LOCK.acquire(blocking=False):
                    return self.fail(409,'Outro pedido está renderizando. Aguarde concluir.')
                try:
                    rid=secrets.token_hex(12)
                    with connection() as db:
                        db.execute('INSERT INTO ai_runs(id,order_id,mode,style,aspect,state,progress,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                   (rid,oid,mode,style,aspect,'na_fila',0,'Aguardando processamento',now(),now()))
                    task=threading.Thread(target=run_ai_in_background,args=(rid,oid,mode,style,aspect),daemon=True)
                    task.start()
                except Exception:
                    AI_RENDER_LOCK.release()
                    raise
                return self.send(202,{'ok':True,'run_id':rid,'state':'na_fila',
                    'message':'Renderização iniciada, sem cobrança e sem entrega automática.'})
            if path == '/api/admin/checkout-create':
                if not self.require_admin(): return
                payload=read_json(self.incoming(4096))
                oid=str(payload.get('id',''))
                if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',oid): return self.fail(400,'Pedido inválido.')
                if not rate_ok(('admin-checkout',self.client_address[0]),3,3600):
                    return self.fail(429,'Limite de testes atingido.')
                # Financial endpoints require a real browser Origin matching the public site,
                # JSON content-type and a distinct acknowledgement. Admin cookies alone are
                # not sufficient to initiate a live preference.
                if self.headers.get('Origin','') != os.getenv('STAYVISION_PUBLIC_URL','').rstrip('/'):
                    return self.fail(403,'Origem obrigatória e deve corresponder à StayVision.')
                if self.headers.get('Content-Type','').split(';')[0].strip().lower() != 'application/json':
                    return self.fail(415,'Envie JSON nesta operação.')
                if self.headers.get('X-StayVision-Checkout-Intent','') != 'single-real-test':
                    return self.fail(403,'Confirmação técnica ausente.')
                if payload.get('confirmation') != 'AUTORIZO PIX REAL '+oid+' R$49':
                    return self.fail(403,'Digite exatamente a autorização exibida no painel para este pedido.')
                if not production_gate(oid):
                    return self.fail(403,'Checkout real bloqueado nas variáveis da Railway. Nenhuma preferência criada.')
                try:
                    result=stage_checkout(oid)
                    return self.send(200,{'ok':True,'created':not result['reused'],
                        'preference_id':result['preference_id'], 'url':result['checkout_url'],
                        'warning':'URL de cobrança REAL. Apenas admin autorizado pode usá-la.'})
                except CheckoutError as exc: return self.fail(409,str(exc))
            if path == '/api/client/checkout':
                if not public_sales_ready():
                    return self.fail(403,'Checkout público ainda não foi liberado.')
                if self.headers.get('Origin','') != os.getenv('STAYVISION_PUBLIC_URL','').rstrip('/'):
                    return self.fail(403,'Origem do checkout inválida.')
                if self.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json':
                    return self.fail(415,'Envie JSON.')
                if not rate_ok(('client-checkout',self.client_address[0]),12,3600):
                    return self.fail(429,'Limite de tentativas. Aguarde.')
                data=read_json(self.incoming(2048))
                token=str(data.get('token',''))
                if not (30<=len(token)<=128):
                    return self.fail(403,'Link de acompanhamento inválido.')
                with connection() as db:
                    rec=db.execute('SELECT id FROM orders WHERE customer_token=?',(token,)).fetchone()
                if not rec: return self.fail(404,'Pedido não localizado.')
                try:
                    result=stage_checkout(rec['id'])
                    return self.send(200,{'ok':True,'url':result['checkout_url'],'reused':result['reused']})
                except CheckoutError as exc:
                    return self.fail(409,str(exc))
            if path == '/api/admin/verify-payment':
                # Conciliação manual autenticada do PAGAMENTO EXISTENTE, nunca cria cobranças.
                # Recupera os detalhes usando a API do MP, nunca confia no status do navegador.
                if not self.require_admin(): return
                if self.headers.get('Origin','') != os.getenv('STAYVISION_PUBLIC_URL','').rstrip('/'):
                    return self.fail(403,'Origem do painel inválida.')
                if self.headers.get('Content-Type','').split(';',1)[0].strip().lower() != 'application/json':
                    return self.fail(415,'Envie JSON nesta operação.')
                if not rate_ok(('admin-manual-reconciliation',self.client_address[0]),10,3600):
                    return self.fail(429,'Limite de conciliações atingido. Aguarde uma hora.')
                data=read_json(self.incoming(2048))
                oid=str(data.get('id','')).strip()
                pid=str(data.get('payment_id','')).strip()
                if not re.fullmatch(r'SV-[A-Z0-9-]{5,40}',oid) or not re.fullmatch(r'[0-9]{1,30}',pid):
                    return self.fail(400,'Informe um pedido StayVision e um ID numérico de pagamento válidos.')
                with connection() as db:
                    order=db.execute('SELECT id,plan_code,price,preference_id,payment_status FROM orders WHERE id=?',(oid,)).fetchone()
                    registry=db.execute('SELECT stage,preference_id,payment_id FROM mp_checkout_registry WHERE order_id=?',(oid,)).fetchone()
                if not order or not registry or registry['stage']!='ready' or not order['preference_id'] or registry['preference_id']!=order['preference_id']:
                    return self.fail(409,'Pedido sem preferência de pagamento emitida e registrada pela StayVision.')
                if registry['payment_id'] and registry['payment_id']!=pid:
                    return self.fail(409,'Pedido já vinculado a outro ID de pagamento. Não houve alteração.')
                if os.getenv('STAYVISION_MP_AUTO_CONFIRM','0')!='1':
                    return self.fail(409,'Confirmação automática desabilitada em STAYVISION_MP_AUTO_CONFIRM. Nenhuma alteração.')
                try:
                    payment=fetch_payment(pid)
                except PaymentLookupUnavailable:
                    return self.fail(502,'Consulta à API do Mercado Pago indisponível. Nenhuma alteração.')
                verdict=review_payment(payment,dict(order),collector_id=os.getenv('MP_PRODUCTION_COLLECTOR_ID',''))
                if verdict!='aprovado_validado_sem_baixa':
                    return self.fail(409,'Pagamento não conciliado: '+verdict+'. Nenhuma alteração.')
                # A rotina preexistente revalida os detalhes dentro de uma transação
                # SQLite, impede duplicidade e só então altera Pendente -> Pago.
                updated=settle_payment_approved(payment)
                with connection() as db:
                    current=db.execute('SELECT payment_status FROM orders WHERE id=?',(oid,)).fetchone()
                    linked=db.execute('SELECT payment_id FROM mp_checkout_registry WHERE order_id=?',(oid,)).fetchone()
                if not current or current['payment_status']!='pago' or not linked or linked['payment_id']!=pid:
                    return self.fail(409,'Pagamento verificado, mas o pedido não foi conciliado. Confira o diagnóstico do webhook.')
                return self.send(200,{'ok':True,'order_id':oid,'payment_status':'pago',
                    'provider_status':'approved','updated':updated,'payment_id':pid,
                    'message':'Pagamento real conciliado e validado pela API. Nenhuma cobrança nova foi criada.'})
            if path == '/api/admin/setup':
                return self.fail(403,'Administrador configurado somente pelas variaveis privadas da Railway.')
            if path == '/api/admin/login':
                if not rate_ok(('login',self.client_address[0]), 8, 900):
                    return self.fail(429,'Muitas tentativas. Aguarde 15 minutos.')
                data = read_json(self.incoming(4096))
                user = str(data.get('username',''))
                pw = str(data.get('password',''))
                with connection() as db:
                    r = db.execute('SELECT * FROM users WHERE username=?', (user,)).fetchone()
                    if not r or not hmac.compare_digest(password_hash(pw,r['password_salt']),r['password_hash']):
                        return self.fail(401,'Usuário ou senha incorretos.')
                    token = new_session(db)
                return self.send(200, {'ok':True}, headers={'Set-Cookie':f'stayvision_session={token}; HttpOnly; SameSite=Strict; Secure; Path=/; Max-Age=43200'})
            if path == '/api/admin/logout':
                if self.user():
                    cookie = self.headers.get('Cookie','')
                    match = re.search(r'stayvision_session=([^;]+)',cookie)
                    if match:
                        with connection() as db: db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(match.group(1).encode()).hexdigest(),))
                return self.send(200, {'ok':True}, headers={'Set-Cookie':'stayvision_session=; HttpOnly; SameSite=Strict; Secure; Path=/; Max-Age=0'})
            if path == '/api/orders':
                if not (DEMO_ORDERS or public_sales_ready()):
                    return self.fail(403,'Pedidos ainda não liberados.')
                if not rate_ok(('orders',self.client_address[0]), 15, 3600):
                    return self.fail(429,'Limite de pedidos de teste atingido. Aguarde.')
                fields, files = parse_form(self.headers.get('Content-Type',''), self.incoming())
                plans = setting('plans', DEFAULT_PLANS)
                plan = next((x for x in plans if x['code']==fields.get('plan')),None)
                if not plan: raise ValueError('Escolha um serviço válido.')
                req = ['name','email','phone','property_type','city']
                if any(not fields.get(key) for key in req): raise ValueError('Preencha todos os campos obrigatórios.')
                if len(fields['name'])>100 or len(fields['phone'])>35 or len(fields['city'])>100 or len(fields.get('notes',''))>3000:
                    raise ValueError('Há um campo com texto longo demais.')
                if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',fields['email']) or len(fields['email'])>150:
                    raise ValueError('Informe um e-mail válido.')
                if fields.get('consent')!='yes': raise ValueError('Você precisa confirmar autorização sobre as imagens.')
                files = [x for x in files if x[0]=='images' and x[2]]
                if not (1<=len(files)<=12): raise ValueError('Envie de 1 a 12 fotos.')
                total_images_bytes = sum(len(x[2]) for x in files)
                if total_images_bytes > 40*1024*1024:
                    raise ValueError('As fotos juntas ultrapassam 40 MB.')
                if shutil.disk_usage(DATA).free < total_images_bytes + 20*1024*1024:
                    raise ValueError('Armazenamento de testes quase cheio. Contate o administrador.')
                for field, name, payload in files:
                    if len(payload)>MAX_IMAGE: raise ValueError(f'O arquivo {name} tem mais de 10 MB.')
                    if not image_type(payload): raise ValueError(f'Formato de imagem não suportado: {name}. Use JPG, PNG ou WEBP.')
                oid = 'SV-'+dt.datetime.now().strftime('%y%m%d')+'-'+secrets.token_hex(3).upper()
                token = secrets.token_urlsafe(32)
                folder = UPLOADS/oid
                folder.mkdir(mode=0o700, exist_ok=False)
                try:
                    with connection() as db:
                        stamp = now()
                        db.execute('''INSERT INTO orders(id,customer_token,created_at,updated_at,plan_code,plan_name,price,name,email,phone,property_type,city,notes,status,payment_status)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (oid,token,stamp,stamp,plan['code'],plan['name'],int(plan['price']),
                            fields['name'][:100],fields['email'][:150],fields['phone'][:35],fields['property_type'][:90],fields['city'][:100],
                            fields.get('notes','')[:3000],'recebido','nao_iniciado'))
                        for ix, (key, name, payload) in enumerate(files):
                            mime,ext=image_type(payload)
                            stored = f'{ix+1:02d}-{secrets.token_hex(8)}{ext}'
                            (folder/stored).write_bytes(payload)
                            db.execute('INSERT INTO order_files(order_id,name,stored_name,mime,size) VALUES(?,?,?,?,?)',
                                       (oid,name,stored,mime,len(payload)))
                except Exception:
                    for f in folder.glob('*'): f.unlink(missing_ok=True)
                    folder.rmdir()
                    raise
                return self.send(201, {'ok':True,'id':oid,'token':token,'tracking_url':'/acompanhar?token='+urllib.parse.quote(token)})
            if path == '/api/admin/lead':
                if not self.require_admin(): return
                data = read_json(self.incoming(15000))
                name = str(data.get('name','')).strip()[:100]
                phone = str(data.get('phone','')).strip()[:35]
                segment = str(data.get('segment','')).strip()[:80]
                city = str(data.get('city','')).strip()[:100]
                source = str(data.get('source','')).strip()[:140]
                notes = str(data.get('notes','')).strip()[:3000]
                stage = str(data.get('stage','novo'))
                lead_id = str(data.get('id',''))
                if not (name and phone and segment) or stage not in LEAD_STAGES:
                    raise ValueError('Informe nome, telefone, segmento e etapa válida.')
                if not re.fullmatch(r'[+0-9() -]{8,35}', phone):
                    raise ValueError('Telefone inválido.')
                with connection() as db:
                    stamp = now()
                    if lead_id:
                        if not db.execute('SELECT 1 FROM leads WHERE id=?',(lead_id,)).fetchone():
                            return self.fail(404,'Contato não encontrado.')
                        db.execute('UPDATE leads SET updated_at=?,name=?,phone=?,segment=?,city=?,source=?,stage=?,notes=? WHERE id=?',
                                   (stamp,name,phone,segment,city,source,stage,notes,lead_id))
                    else:
                        lead_id='LD-'+secrets.token_hex(5).upper()
                        db.execute('INSERT INTO leads (id,created_at,updated_at,name,phone,segment,city,source,stage,notes) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                   (lead_id,stamp,stamp,name,phone,segment,city,source,stage,notes))
                return self.send(200, {'ok':True,'id':lead_id})
            if path == '/api/admin/update':
                if not self.require_admin(): return
                data = read_json(self.incoming(10000))
                oid = str(data.get('id',''))
                status = data.get('status')
                payment = data.get('payment_status')
                note = str(data.get('admin_note',''))[:3000]
                if status not in STATUS or payment not in PAYMENT_STATUS:
                    raise ValueError('Status inválido.')
                with connection() as db:
                    r = db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
                    if not r: return self.fail(404,'Pedido não encontrado.')
                    if payment != r['payment_status']:
                        raise ValueError('Nao e permitido mudar pagamento manualmente na versao online de demonstracao.')
                    db.execute('UPDATE orders SET status=?,payment_status=?,admin_note=?,updated_at=? WHERE id=?',
                               (status,payment,note,now(),oid))
                    if payment=='pago' and r['payment_status'] != 'pago':
                        ensure_job(db, oid, r['plan_code'])
                        if r['delivery_filename'] and status=='concluido':
                            db.execute('UPDATE production_jobs SET state=?,updated_at=? WHERE order_id=?',
                                       ('entregue',now(),oid))
                return self.send(200, {'ok':True})
            if path == '/api/admin/settings':
                if not self.require_admin(): return
                data = read_json(self.incoming(12000))
                if 'payment_enabled' in data or 'sales_enabled' in data:
                    return self.fail(403,'Cobranças e vendas estao bloqueadas nesta versao de demonstracao.')
                if 'plans' in data:
                    plans = data['plans']
                    if not isinstance(plans,list) or len(plans)!=3 or [p.get('code') for p in plans]!=['photo','video','partner']:
                        raise ValueError('A lista de planos precisa conter photo, video e partner.')
                    for p in plans:
                        if not isinstance(p.get('price'),int) or not 1<=p['price']<=100000:
                            raise ValueError('Preços inválidos.')
                        for textfield in ('name','description','unit'):
                            if not isinstance(p.get(textfield),str) or not p[textfield] or len(p[textfield])>180:
                                raise ValueError('Dados de planos inválidos.')
                        if not isinstance(p.get('features'),list) or len(p['features'])>8:
                            raise ValueError('Características inválidas.')
                    set_setting('plans', plans)
                for key in ('brand_name','contact_whatsapp'):
                    if key in data:
                        v = str(data[key]).strip()[:100]
                        if key == 'contact_whatsapp' and v and not re.fullmatch('[0-9+() -]{8,24}',v):
                            raise ValueError('Contato inválido.')
                        set_setting(key,v)
                # Habilitar aqui ativa SOMENTE compras simuladas com credenciais de teste.
                if 'payment_enabled' in data:
                    allow = bool(data['payment_enabled'])
                    if allow and not configured_mp():
                        raise ValueError('Para testar configure MP_TEST_ACCESS_TOKEN no arquivo .env.local e reinicie o servidor.')
                    set_setting('payment_enabled',allow)
                    if not allow:
                        set_setting('sales_enabled',False)
                        set_setting('demo_mode',True)
                if 'sales_enabled' in data:
                    allow = bool(data['sales_enabled'])
                    if allow and (not configured_mp() or not setting('payment_enabled')):
                        raise ValueError('Primeiro configure a integração de cobrança antes de abrir vendas.')
                    set_setting('sales_enabled',allow)
                    set_setting('demo_mode',not allow)
                return self.send(200, {'ok':True})
            if path == '/api/admin/deliver':
                if not self.require_admin(): return
                fields, files = parse_form(self.headers.get('Content-Type',''), self.incoming(MAX_DELIVERY + 200000))
                oid = fields.get('id','')
                with connection() as db: order = db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
                if not order: return self.fail(404,'Pedido não encontrado.')
                if len(files)!=1: raise ValueError('Selecione exatamente um arquivo final.')
                key, original, payload=files[0]
                suffix = Path(original).suffix.lower()
                if suffix not in ('.mp4','.webm','.jpg','.jpeg','.png','.zip','.pdf'):
                    raise ValueError('Entrega permitida: MP4, WEBM, JPG, PNG, ZIP ou PDF.')
                if not payload or len(payload)>MAX_DELIVERY:
                    raise ValueError('Entrega vazia ou maior que 90 MB.')
                signatures = {'.mp4': lambda d:b'ftyp' in d[:20], '.webm':lambda d:d[:4]==b'\x1a\x45\xdf\xa3',
                              '.jpg':lambda d:d[:3]==b'\xff\xd8\xff','.jpeg':lambda d:d[:3]==b'\xff\xd8\xff',
                              '.png':lambda d:d[:8]==b'\x89PNG\r\n\x1a\n',
                              '.pdf':lambda d:d.startswith(b'%PDF'),'.zip':lambda d:d.startswith(b'PK\x03\x04')}
                if not signatures[suffix](payload): raise ValueError('O conteúdo do arquivo não corresponde ao formato informado.')
                stored = oid+'_'+secrets.token_hex(5)+'_'+original
                (DELIVERIES/stored).write_bytes(payload)
                with connection() as db:
                    db.execute('UPDATE orders SET delivery_filename=?,status=?,updated_at=? WHERE id=?',
                               (stored,'concluido',now(),oid))
                    job = db.execute('SELECT 1 FROM production_jobs WHERE order_id=?',(oid,)).fetchone()
                    if job:
                        db.execute('UPDATE production_jobs SET state=?,updated_at=? WHERE order_id=?',
                                   ('entregue',now(),oid))
                return self.send(200,{'ok':True})
            if path == '/api/client/checkout':
                return self.fail(403,'Pagamentos indisponiveis nesta versao online de demonstracao.')
            return self.fail(404,'Endpoint não encontrado.')
        except ValueError as exc:
            return self.fail(400,str(exc))
        except Exception as exc:
            print('Server exception:', repr(exc), file=sys.stderr)
            return self.fail(500,'Erro interno. Veja o terminal do servidor.')


def serve(host,port):
    ensure_online_storage()
    init_db()
    initialize_admin()
    server = ThreadingHTTPServer((host,port),Handler)
    print(f'\n  STAYVISION STUDIO V1  |  http://{host}:{port}')
    print('  Site: http://127.0.0.1:%d' % port)
    print('  Painel privado: http://127.0.0.1:%d/painel' % port)
    print('  Banco: '+str(DB))
    print('  PUBLICO: '+('ABERTO' if public_sales_ready() else 'BLOQUEADO')+'\n')
    if os.name == 'nt':
        threading.Timer(0.6, lambda: webbrowser.open('http://127.0.0.1:%d' % port)).start()
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8787)
    args = parser.parse_args()
    serve(args.host,args.port)
