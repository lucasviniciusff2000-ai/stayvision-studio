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
        if p=='/health':
            return self._send('{"ok":true,"service":"stayvision-unified"}')
        if p=='/api/status':
            from real_plan_checkout import enabled
            return self._send(json.dumps({'real_plan_checkout_enabled':enabled(),
                    'one_real_e2e_enabled':False,'commercial_checkout':True,
                    'public_server':True,'release':'V3.33_UNIFIED_RAILWAY'}))
        if p in GET_SIMPLE or p.startswith('/assets/') or _match(p,GET_PRIVATE):
            return super().do_GET()
        if _match(p,GET_ADMIN):
            if not self._admin():return self._bad(401)
            return super().do_GET()
        return self._bad()
    def do_POST(self):
        p=urlsplit(self.path).path
        if not self._origin_host_ok():return self._bad(421)
        if p in POST_SIMPLE:
            return super().do_POST()
        if _match(p,POST_ADMIN):
            if not self._admin():return self._bad(401)
