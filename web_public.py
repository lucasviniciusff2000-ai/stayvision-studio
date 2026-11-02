"""StayVision Business: unified public checkout + private admin + AI workers.
The legacy app.py is NOT a public entry point. This allowlisted gateway is.
"""
import json, os, re, sys, time
from pathlib import Path
from urllib.parse import urlsplit
from http.server import ThreadingHTTPServer

class SafeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

GET_SIMPLE={
    '/', '/index.html', '/comprar', '/painel', '/operacao',
    '/assets/admin_v38.js', '/galeria_celular.js', '/api/plans',
    '/api/admin/session', '/api/admin/overview', '/health', '/api/status'
}
POST_SIMPLE={
    '/api/cliente/pedido', '/api/cliente/checkout-real',
    '/api/cliente/verificar-pagamento-real',
    '/api/admin/login', '/api/admin/logout', '/api/admin/plan-payment/check'
}
GET_PRIVATE=(r'/acompanhar/[A-Za-z0-9_-]{43}',
             r'/api/cliente/status/[A-Za-z0-9_-]{43}',
             r'/entrega/[A-Za-z0-9_-]{40,80}',
             r'/api/entrega/[A-Za-z0-9_-]{40,80}',
             r'/(?:midia|salvar)/[A-Za-z0-9_-]{40,80}/[a-z_]+/(?:[1-9][0-9]?)',
             r'/salvar/[A-Za-z0-9_-]{40,80}/pacote-completo')
GET_ADMIN=(r'/api/admin/orders/pedido-[0-9a-f]{16}',
           r'/preview/pedido-[0-9a-f]{16}/(?:original|photo|feed|profile|cover|story|extra)/[1-9][0-9]?',
           r'/preview/pedido-[0-9a-f]{16}/instagram/(?:perfil|feed|banner)',
           r'/download/(?:aprovado-)?pedido-[0-9a-f]{16}\.zip')
POST_ADMIN=(r'/api/admin/orders/pedido-[0-9a-f]{16}/(?:review|revoke)',
            r'/api/orders/pedido-[0-9a-f]{16}/review',
            r'/api/orders/pedido-[0-9a-f]{16}/delivery/revoke')

def _match(p,patterns):return any(re.fullmatch(x,p) for x in patterns)

from app import LocalServer
class PublicHandler(LocalServer):
    server_version='StayVisionWeb'
    sys_version=''
    def _send(self,body,code=200,mime='application/json',extra=None):
        data=body if isinstance(body,bytes) else body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Robots-Tag','index, follow' if os.getenv('SV_SITE_PUBLIC_INDEX')=='1' and self.path.startswith(('/','/index.html')) and self.path.split('?')[0] in ('/','/index.html') else 'noindex, nofollow')
        if os.getenv('SV_PUBLIC_ORIGIN','').startswith('https://'):
            self.send_header('Strict-Transport-Security','max-age=31536000')
        if 'text/html' in mime:
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self' https://www.mercadopago.com.br https://www.mercadopago.com; frame-ancestors 'none'")
        if extra:
            for k,v in extra.items():
                if k.lower()=='content-security-policy':continue # avoid double conflicting policies
                self.send_header(k,v)
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(data)
    def _origin_host_ok(self):
        root=os.getenv('SV_PUBLIC_ORIGIN','')
        if not root:return False
        expected=urlsplit(root).netloc.lower()
        return self.headers.get('Host','').lower()==expected
    def _bad(self,code=404):
        return self._send(json.dumps({'error':'Rota indisponível.'}),code)
    def _admin(self):
        from admin_panel import authorized
        return bool(authorized(self))
    def do_GET(self):
        p=urlsplit(self.path).path
        if p!='/health' and not self._origin_host_ok():return self._bad(421)
        if p=='/piloto-r1':
            if not self._admin():return self._bad(401)
            if os.getenv('SV_PILOT_R1_ENABLED')!='1':return self._bad(404)
            return self._send((Path(__file__).parent/'piloto_r1.html').read_bytes(),
                              mime='text/html; charset=utf-8')
        if p=='/health':
            return self._send('{"ok":true,"service":"stayvision-unified"}')
        if p=='/api/status':
            from real_plan_checkout import enabled
            from semi_auto_queue import enabled as queue_enabled
            from auto_delivery import enabled as delivery_enabled
            return self._send(json.dumps({'real_plan_checkout_enabled':enabled(),
                    'one_real_e2e_enabled':False,'commercial_checkout':True,
                    'ai_queue_enabled':queue_enabled(),'auto_delivery_enabled':delivery_enabled(),
                    'public_server':True,'release':'V3.34_UNIFIED_RAILWAY'}))
        if p in GET_SIMPLE or p.startswith('/assets/') or _match(p,GET_PRIVATE):
            return super().do_GET()
        if _match(p,GET_ADMIN):
            if not self._admin():return self._bad(401)
            return super().do_GET()
        return self._bad()
    def do_POST(self):
        p=urlsplit(self.path).path
        if not self._origin_host_ok():return self._bad(421)
        if (m:=re.fullmatch(r'/api/admin/orders/(pedido-[0-9a-f]{16})/tracking-link',p)):
            from admin_panel import tracking_link
            return tracking_link(self,m.group(1))
        if p=='/api/admin/piloto-r1/criar':
            from piloto_r1_privado import create_pilot_order
            return create_pilot_order(self)
        if p in POST_SIMPLE:
            return super().do_POST()
        if _match(p,POST_ADMIN):
            if not self._admin():return self._bad(401)
            return super().do_POST()
        return self._bad()
    def do_PUT(self):return self._bad(405)
    def do_DELETE(self):return self._bad(405)
    def do_PATCH(self):return self._bad(405)
    def log_message(self,format,*args):
        # Never print tracking tokens, checkout urls, credentials or query strings.
        p=urlsplit(self.path).path
        label='/[private]' if any(x in p for x in ['/acompanhar/','/entrega/','/api/cliente/status/','/salvar/','/midia/']) else p[:76]
        print('[WEB]',self.command,label,flush=True)

def prepare():
    from urllib.parse import urlsplit
    origin=os.getenv('SV_PUBLIC_ORIGIN','').rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.path or parsed.query:
        raise RuntimeError('SV_PUBLIC_ORIGIN precisa ser https://dominio-da-stayvision, sem caminho.')
    if os.getenv('RAILWAY_VOLUME_MOUNT_PATH')!='/data' or not os.getenv('RAILWAY_VOLUME_NAME'):
        raise RuntimeError('Volume Railway obrigatório: conecte o volume ao MESMO serviço em /data antes de abrir pagamentos.')
    if os.getenv('STAYVISION_DATA_DIR')!='/data':
        raise RuntimeError('STAYVISION_DATA_DIR deve ser /data.')
    Path('/data').mkdir(parents=True,exist_ok=True)
    if not os.access('/data',os.W_OK):raise RuntimeError('Volume /data sem permissão de escrita.')
    required=('MP_LIVE_ACCESS_TOKEN','GEMINI_API_KEY','FAL_KEY')
    for name in required:
        if not os.getenv(name,'').strip():raise RuntimeError('Configure o secret Railway '+name+'.')
    if os.getenv('SV_REAL_PLANS_ENABLED')!='1':
        raise RuntimeError('SV_REAL_PLANS_ENABLED=1 é obrigatório para esta versão comercial.')
    if os.getenv('SV_ONE_REAL_E2E')=='1':raise RuntimeError('Desative o piloto de R$1 no ambiente comercial.')
    if os.getenv('STAYVISION_IMAGE_MODE')!='required' or os.getenv('STAYVISION_AI_MODE')=='off':
        raise RuntimeError('Configure IA de imagem e criativo antes do checkout.')
    if os.getenv('STAYVISION_EDIT_GOAL')!='new':
        raise RuntimeError('Use STAYVISION_EDIT_GOAL=new para produção comercial.')
    from admin_credentials import configured,setup
    if not configured():
        username=os.getenv('SV_ADMIN_USER','')
        password=os.getenv('SV_ADMIN_PASSWORD','')
        if not username or len(password)<16 or 'SENHA_FORTE' in password.upper() or 'DE_SUA_ESCOLHA' in username.upper():raise RuntimeError('Defina SV_ADMIN_USER e SV_ADMIN_PASSWORD REAIS (16+ caracteres) antes de iniciar.')
        setup(username,password)
    if os.getenv('STAYVISION_IMAGE_SESSION_LIMIT','0').isdigit() is False or int(os.getenv('STAYVISION_IMAGE_SESSION_LIMIT','0'))<1:
        raise RuntimeError('Defina STAYVISION_IMAGE_SESSION_LIMIT maior que zero.')
    from semi_auto_queue import enabled as queue_enabled
    if not queue_enabled():raise RuntimeError('Configure orçamento e consentimento explícito da fila automática.')
    from auto_delivery import enabled as deliv_enabled
    if not deliv_enabled():raise RuntimeError('Configure SV_COMMERCIAL_AUTO_DELIVERY=1 e o limite de entregas automáticas.')
    from real_plan_checkout import start_background as poll
    from semi_auto_queue import start_background as queue
    from auto_delivery import start_background as delivery
    poll(); queue(); delivery()

def main():
    prepare()
    port=int(os.getenv('PORT','8080'))
    if port<1 or port>65535:raise RuntimeError('PORT inválida.')
    print('StayVision unified active: site, Mercado Pago reconciliation, AI queue, quality-gated delivery; port',port,flush=True)
    SafeServer(('0.0.0.0',port),PublicHandler).serve_forever()

if __name__=='__main__':main()
