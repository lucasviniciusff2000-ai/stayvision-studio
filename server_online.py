#!/usr/bin/env python3
"""StayVision Studio • public Railway DEMO with private admin, demo uploads, NO payments."""
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

BASE = Path(__file__).resolve().parent
STATIC = BASE / 'static'
DATA = Path(os.getenv('STAYVISION_DATA_DIR', str(BASE / 'dados'))).resolve()
UPLOADS = DATA / 'uploads'
DELIVERIES = DATA / 'entregas'
DB = DATA / 'stayvision.db'
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
        defaults = {
            'plans': DEFAULT_PLANS, 'brand_name': 'StayVision',
            'contact_whatsapp': '', 'sales_enabled': False,
            'payment_enabled': False, 'demo_mode': True
        }
        for key, value in defaults.items():
            db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))
        # Esta versao ONLINE e somente para demonstracao. Nao aceitar flags antigas de pagamento.
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
    return {**{k: setting(k) for k in ('plans', 'brand_name', 'contact_whatsapp', 'sales_enabled', 'payment_enabled', 'demo_mode')},
            'sales_enabled':False, 'payment_enabled':False, 'demo_mode':True,
            'demo_orders_enabled': DEMO_ORDERS, 'payment_environment':'desativado'}


def set_setting(key, value):
    with connection() as db:
        db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (key, json.dumps(value, ensure_ascii=False)))


def mp_environment():
    # Esta distribuição só permite transações simuladas. Produção exige nova revisão.
    return 'desativado'  # NUNCA usar pagamentos no preview publico


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


def apply_verified_payment(oid, payment):
    # Somente dados consultados no Mercado Pago podem alterar o status de cobrança.
    mapping = {'approved':'pago','pending':'pendente','in_process':'pendente',
               'rejected':'recusado','refunded':'estornado','charged_back':'estornado',
               'cancelled':'recusado'}
    state = mapping.get(payment.get('status'))
    if not state:
        raise ValueError('O Mercado Pago retornou um estado ainda não reconhecido.')
    with connection() as db:
        order = db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if not order:
            raise ValueError('Pedido não encontrado.')
        try:
            amount = float(payment.get('transaction_amount',-1))
        except (TypeError, ValueError):
            amount = -1
        if str(payment.get('external_reference')) != oid or payment.get('currency_id') != 'BRL' or abs(amount - float(order['price'])) > 0.001:
            raise ValueError('Pagamento não corresponde ao pedido e valor registrados.')
        # Testes não podem aceitar pagamento real; nunca use este módulo em produção.
        if mp_environment() == 'teste' and payment.get('live_mode') is not False:
            raise ValueError('Pagamento não está identificado como transação de teste.')
        if order['payment_status'] == 'estornado' and state == 'pago':
            raise ValueError('Pedido já estornado; revisão manual necessária.')
        db.execute('UPDATE orders SET payment_status=?,updated_at=? WHERE id=?', (state,now(),oid))
        if state == 'pago':
            ensure_job(db,oid,order['plan_code'])
            if order['delivery_filename'] and order['status']=='concluido':
                db.execute("UPDATE production_jobs SET state='entregue',updated_at=? WHERE order_id=?",(now(),oid))
    return state


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
                return self.send(200, {'ok':True,'mode':'pedidos_demo','payments':False})
            except sqlite3.Error:
                return self.fail(503,'Banco indisponivel')
        if path == '/api/admin/me':
            with connection() as db:
                setup = db.execute('SELECT COUNT(*) as c FROM users').fetchone()['c'] > 0
            return self.send(200, {'authenticated':bool(self.user()), 'initialized': setup})
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
                'engine_connected':False, 'payment_gateway_configured':False,
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
        if path == '/api/admin/settings':
            if not self.require_admin(): return
            return self.send(200, {**settings_public(),'mercadopago_ready':False,
                                   'public_url':bool(os.getenv('STAYVISION_PUBLIC_URL')), 'payment_environment':'desativado', 'pix_production_diagnostic_ready':prod_credential_configured()})
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
                                   'checkout_available': bool(setting('payment_enabled') and setting('sales_enabled') and configured_mp()), 'payment_environment':mp_environment()})
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

    def do_POST(self):
        if not self.origin_ok(): return self.fail(403,'Origem inválida.')
        path = urllib.parse.urlsplit(self.path).path
        try:
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
                if not DEMO_ORDERS:
                    return self.fail(403,'Pedidos de demonstracao ainda nao liberados.')
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
            if path in ('/api/client/checkout', '/api/admin/verify-payment', '/api/mp/webhook'):
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
    print('  PREVIA DE PEDIDOS SEM COBRANCAS.\n')
    if os.name == 'nt':
        threading.Timer(0.6, lambda: webbrowser.open('http://127.0.0.1:%d' % port)).start()
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8787)
    args = parser.parse_args()
    serve(args.host,args.port)
