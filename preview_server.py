#!/usr/bin/env python3
"""Preview-only StayVision webserver. No uploads, admin or payments exposed."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote

STATIC = Path(__file__).resolve().parent / 'static'
PLANS = [
    {'code':'photo','name':'StayVision Photo','price':49,'unit':'pedido','description':'Tratamento visual de fotografias imobiliárias','features':['Até 8 fotografias','Ajustes de cor e iluminação','Formato para anúncio e redes sociais']},
    {'code':'video','name':'StayVision Video','price':197,'unit':'vídeo','description':'Edição de vídeo imobiliário a partir de fotos','features':['Até 8 fotografias fornecidas','Edição e trilha licenciada','Formato vertical ou horizontal']},
    {'code':'partner','name':'StayVision Partner','price':697,'unit':'pacote mensal proposto','description':'Produção recorrente para profissionais e hospedagens','features':['Escopo definido antes da contratação','Acompanhamento de pedidos','Condição especial por volume']},
]
MIMES={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml','.webp':'image/webp'}

class Handler(BaseHTTPRequestHandler):
    server_version = 'StayVisionPreview'
    def send_content(self,status,data,mime='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(data)
    def do_HEAD(self):return self.do_GET()
    def do_GET(self):
        path=unquote(urlsplit(self.path).path)
        if path == '/api/health': return self.send_content(200,b'{"ok":true,"mode":"preview"}')
        if path == '/api/public/config':
            data={'plans':PLANS,'brand_name':'StayVision','contact_whatsapp':'','sales_enabled':False,'payment_enabled':False,'demo_mode':True,'payment_environment':'desativado'}
            return self.send_content(200,json.dumps(data,ensure_ascii=False).encode('utf-8'))
        if path in ('/','/index.html'):file=STATIC/'index.html'
        elif path.startswith('/static/'):
            name=path[len('/static/'):]
            file=(STATIC/name).resolve()
            if STATIC.resolve() not in file.parents or not file.is_file():return self.send_content(404,b'Nao encontrado', 'text/plain; charset=utf-8')
        else:return self.send_content(404,b'Nao encontrado','text/plain; charset=utf-8')
        if not file.is_file():return self.send_content(404,b'Nao encontrado','text/plain; charset=utf-8')
        return self.send_content(200,file.read_bytes(),MIMES.get(file.suffix.lower(),'application/octet-stream'))
    def do_POST(self):return self.send_content(503,b'{"error":"Site em demonstracao. Pedidos e pagamentos ainda indisponiveis."}')

if __name__ == '__main__':
    port=int(os.environ.get('PORT','8787'))
    assert 1<=port<=65535
    print(f'StayVision demonstracao: porta {port}',flush=True)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
