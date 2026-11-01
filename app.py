"""Interface local StayVision Business. Não publique este servidor na internet."""
import base64, json, re, secrets, sys, webbrowser, zipfile, datetime, shutil, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from engine import PLANS, build, count_visual_calls
from creative_ai import available, mode, DEFAULT_MODEL
from image_ai import enabled as image_enabled, remaining as image_remaining, model as image_model, edit_goal

ROOT=Path(__file__).resolve().parent
OUT=Path(os.environ.get('STAYVISION_DATA_DIR',str(ROOT/'pedidos_teste'))).resolve(); OUT.mkdir(parents=True,exist_ok=True)
MAX_POST=70 * 1024 * 1024

JOB_RE=re.compile(r'^pedido-[0-9a-f]{16}$')
REVIEW_CHECKS=('identidade','produto','texto','arquivos')

def order_dir(job):
    if not JOB_RE.fullmatch(job): raise ValueError('Identificador de pedido inválido.')
    p=OUT/job/'entrega'
    if not p.is_dir():raise FileNotFoundError('Pedido não encontrado.')
    return p

def read_review(job):
    p=order_dir(job)
    review_file=p/'REVISAO_INTERNA.json'
    return json.loads(review_file.read_text(encoding='utf-8')) if review_file.exists() else {'status':'PENDENTE','checks':{},'notes':''}


def audit_artifacts(folder, plan, info):
    """Inspeção determinística de entregáveis; não substitui revisão visual humana."""
    from PIL import Image
    missing=[]; cfg=PLANS[plan]
    def required(relative, desc):
        target=folder/relative
        if not target.is_file() or target.stat().st_size==0: missing.append(desc)
        return target
    def picture(relative, desc, size=None):
        p=required(relative,desc)
        if p.is_file():
            try:
                with Image.open(p) as im:
                    im.verify()
                if size:
                    with Image.open(p) as im:
                        if im.size!=size: missing.append(desc+f' (dimensão incorreta: {im.size})')
            except Exception:missing.append(desc+' (imagem inválida)')
    required('INFO_PEDIDO.json','Informações do pedido ausentes')
    required('05_controle_de_qualidade/relatorio.txt','Relatório de qualidade ausente')
    required('05_controle_de_qualidade/briefing_criativo.json','Briefing criativo ausente')
    if plan in ('fotos','premium'):
        edits=int(info.get('photo_edits',info.get('photos_received',0)))
        creatives=int(info.get('creative_compositions',0))
        # Premium direto trata TODAS as 1..8 fotos reais. Reuso legado pode ter 6 peças
        # incluindo composições separadamente rotuladas. NUNCA inventar 8 originais.
        flex_fotos=(plan=='fotos' and 1<=edits<=6 and creatives==0)
        direct_premium=(plan=='premium' and 1<=edits<=8 and creatives==0 and
                        info.get('premium_photos_included')==edits)
        required_photos=edits if (direct_premium or flex_fotos) else 6
        if not (direct_premium or flex_fotos or (3<=edits<=6 and creatives==6-edits)):
            missing.append('Distribuição de fotografias e composições inconsistente')
        for i in range(1,required_photos+1):
            picture(f'01_fotos_tratadas/foto_profissional_{i:02d}.jpg',f'Imagem final {i}/{required_photos} ausente')
            if i<=edits:
                picture(f'00_originais/original_{i:02d}.jpg',f'Original {i} ausente')
                picture(f'05_controle_de_qualidade/antes_depois_{i:02d}.jpg',f'Comparativo real {i} ausente')
            else:
                picture(f'05_controle_de_qualidade/referencia_composicao_{i:02d}.jpg',f'Comparativo de composicao {i} ausente')
                required(f'05_controle_de_qualidade/AVISO_COMPOSICAO_{i:02d}.txt',f'Aviso de composicao {i} ausente')
    else:
        for i in range(1,cfg['photos']+1):
            picture(f'01_fotos_tratadas/foto_profissional_{i:02d}.jpg',f'Foto {i}/{cfg["photos"]} ausente')
            picture(f'05_controle_de_qualidade/antes_depois_{i:02d}.jpg',f'Comparativo {i}/{cfg["photos"]} ausente')
    if info.get('sample_only'):missing.append('Amostra única, pacote comercial propositalmente incompleto')
    if cfg['brand'] and info.get('brand_engine')!='gpt_image_2_5_fal_ai':
        missing.append('Identidade não gerada pelo GPT Image')
    if cfg['brand'] and not info.get('sample_only') and info.get('generative_design_count',0)< (6+cfg['feed']+cfg['stories']+cfg['premium']):
        missing.append('Artes geradas por GPT Image em quantidade insuficiente')
    if cfg['brand']:
        picture('02_perfil_express/foto_de_perfil_1080.png','Foto de perfil ausente',(1080,1080))
        picture('02_perfil_express/previa_perfil.png','Prévia de perfil ausente',(1300,900))
        required('02_perfil_express/bio_sugerida.txt','Bio ausente')
        required('02_perfil_express/identidade_visual.txt','Paleta/guia de identidade ausente')
        covers=list((folder/'02_perfil_express').glob('capa_destaque_*.png'))
        if len(covers)!=5:missing.append(f'Capas de destaque: {len(covers)}/5')
        for item in covers:picture(item.relative_to(folder),'Capa de destaque inválida',(600,600))
    if cfg['feed']:
        for i in range(1,cfg['feed']+1):
            picture(f'03_vitrine_digital/feed_{i:02d}_1080x1350.jpg',f'Post {i}/6 ausente',(1080,1350))
        for i in range(1,cfg['stories']+1):
            picture(f'03_vitrine_digital/story_{i:02d}_1080x1920.jpg',f'Story {i}/4 ausente',(1080,1920))
        cap=required('03_vitrine_digital/legendas_prontas_para_revisao.txt','Legendas ausentes')
        if cap.is_file():
            content=cap.read_text(encoding='utf-8')
            if sum(f'POST {i:02d}:' in content for i in range(1,7)) !=6:missing.append('Legendas: menos de 6 posts')
    for i in range(1,cfg['premium']+1):
        picture(f'04_feed_premium/arte_extra_{i:02d}_1080x1350.png',f'Arte extra {i}/3 ausente',(1080,1350))
    if (plan in ('fotos','premium')) and info.get('photo_edit_engine')!='generative_image_ai':
        missing.append('Motor visual profissional não utilizado')
    if plan in ('fotos','premium') and int(info.get('generative_photo_count',0))<(int(info['premium_photos_included']) if plan=='premium' and info.get('premium_photos_included') is not None else int(info.get('photos_received',0))):
        missing.append('Quantidade insuficiente de fotos geradas por IA')
    if plan=='vitrine' and int(info.get('generative_design_count',0))<16:
        missing.append('Vitrine incompleta: imagens de post/story não produzidas integralmente por GPT Image')
    if info.get('marketing_upgrade_version')=='3.0' and cfg['brand'] and not info.get('sample_only'):
        for relative,label,sz in [
          ('02_perfil_express/logo_horizontal_escuro_1600x600.png','Logo horizontal escuro',(1600,600)),
          ('02_perfil_express/logo_horizontal_claro_1600x600.png','Logo horizontal claro',(1600,600)),
        ]:picture(relative,label,sz)
        bios=required('02_perfil_express/bios_3_opcoes.txt','Três versões de bio ausentes')
        if bios.exists():
            content=bios.read_text(encoding='utf-8')
            if not all(x in content for x in ('COMERCIAL','CRIATIVA','INSTITUCIONAL')):
                missing.append('Bios alternativas incompletas')
        if cfg['feed']:
            required('03_vitrine_digital/textos_stories.txt','Roteiros de Stories ausentes')
            plan_file=required('05_controle_de_qualidade/planejamento_editorial.json','Planejamento editorial ausente')
            if plan_file.exists():
                try:
                    content=json.loads(plan_file.read_text(encoding='utf-8'))
                    if not content.get('headline_unique') or not content.get('caption_unique'):
                        missing.append('Campanha com textos repetidos')
                except (ValueError,KeyError,TypeError):missing.append('Planejamento editorial inválido')
    if plan!='perfil' and info.get('photos_received',0)<1:missing.append('Nenhuma imagem de referência enviada')
    return missing

def get_order(job):
    p=order_dir(job)
    info=json.loads((p/'INFO_PEDIDO.json').read_text(encoding='utf-8'))
    plan=info['plan'];required=int(info.get('premium_photos_included',6) if plan=='premium' else info.get('photos_received',0) if plan=='fotos' else PLANS[plan]['photos'])
    produced=len(list((p/'01_fotos_tratadas').glob('foto_profissional_*.jpg'))) if (p/'01_fotos_tratadas').exists() else 0
    feed=len(list((p/'03_vitrine_digital').glob('feed_*.jpg'))) if (p/'03_vitrine_digital').exists() else 0
    stories=len(list((p/'03_vitrine_digital').glob('story_*.jpg'))) if (p/'03_vitrine_digital').exists() else 0
    extras=len(list((p/'04_feed_premium').glob('arte_extra_*.png'))) if (p/'04_feed_premium').exists() else 0
    missing=[]
    if required and produced<required:missing.append(f'Fotos tratadas: {produced}/{required}')
    if PLANS[plan]['feed'] and feed<PLANS[plan]['feed']:missing.append(f'Posts: {feed}/{PLANS[plan]["feed"]}')
    if PLANS[plan]['stories'] and stories<PLANS[plan]['stories']:missing.append(f'Stories: {stories}/{PLANS[plan]["stories"]}')
    if PLANS[plan]['brand'] and not (p/'02_perfil_express'/'previa_perfil.png').exists():missing.append('Prévia do perfil ausente')
    missing.extend(audit_artifacts(p,plan,info))
    data={'job':job, 'brand':info['brand'], 'plan':info['plan_name'],'plan_code':plan,
          'photos_received':info['photos_received'],'photos_required':required,'photos_ready':produced,
          'creative_compositions':info.get('creative_compositions',0),'photo_edits':info.get('photo_edits',info['photos_received']),'creative_quality_flags':info.get('creative_quality_flags',[]),'brand_conflict':info.get('brand_conflict',False),
          'posts_ready':feed, 'stories_ready':stories,'extras_ready':extras, 'engine':info.get('photo_edit_engine'),
          'missing':missing,'review':read_review(job),
          'preview':{'covers':len(list((p/'02_perfil_express').glob('capa_destaque_*.png'))), 'originals':info['photos_received'],'photos':produced,'feed':feed, 'profile':PLANS[plan]['brand'],'stories':stories,'extras':extras},
          'delivery_link':__import__('delivery_mobile').link_for_operator(job),
          'visual_previews':{key:(p/'06_previas_instagram'/fname).is_file() for key,fname in {'perfil':'perfil_completo_1080x1920.png','feed':'grade_publicacoes_1080x1350.png','banner':'apresentacao_premium_2000x1250.png'}.items()},
          'internal_draft':f'/download/{job}.zip',
          'approved_download':f'/download/aprovado-{job}.zip' if (OUT/f'aprovado-{job}.zip').exists() else None}
    return data

class LocalServer(BaseHTTPRequestHandler):
    def _send(self,body,code=200,mime='application/json',extra=None):
        body=body if isinstance(body,bytes) else body.encode('utf-8')
        self.send_response(code); self.send_header('Content-Type',mime); self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cache-Control','no-store')
        if extra:
            for k,v in extra.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p=urlparse(self.path).path
        if p=='/comprar':
            return self._send((ROOT/'comprar_premium.html').read_bytes(),mime='text/html; charset=utf-8')
        if p in ('/operacao','/painel'):
            return self._send((ROOT/'painel_admin_v38.html').read_bytes(),mime='text/html; charset=utf-8',extra={'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"})
        if p=='/assets/admin_v38.js':
            return self._send((ROOT/'assets'/'admin_v38.js').read_bytes(),mime='text/javascript; charset=utf-8')
        if p=='/api/admin/session':
            from admin_panel import session
            return session(self)
        if p=='/api/admin/pilot':
            from admin_panel import authorized,_json
            from pilot_live_payment import status_for_admin
            if not authorized(self):return _json(self,{'error':'Entre no painel.'},401)
            return _json(self,{'ok':True,'pilot':status_for_admin()})
        if p=='/api/admin/overview':
            from admin_panel import overview
            return overview(self)
        if (m:=re.fullmatch(r'/api/admin/orders/(pedido-[0-9a-f]{16})',p)):
            from admin_panel import details
            return details(self,m.group(1))
        if (m:=re.fullmatch(r'/acompanhar/([A-Za-z0-9_-]{43})',p)):
            from commerce_flow import customer_page
            return customer_page(self,m.group(1))
        if (m:=re.fullmatch(r'/api/cliente/status/([A-Za-z0-9_-]{43})',p)):
            from commerce_flow import status_customer
            return status_customer(self,m.group(1))
        if p=='/api/operacao/pedidos':
            from admin_panel import authorized
            if not authorized(self):return self._send('{"error":"Acesso administrativo exige login."}',401)
            from commerce_flow import operator_list
            return operator_list(self)
        if p.startswith(('/entrega/','/api/entrega/','/midia/','/salvar/')):
            from delivery_mobile import handle_get
            return handle_get(self,p)
        if p in ('/','/index.html'):
            self._send((ROOT/'index.html').read_bytes(),mime='text/html; charset=utf-8')
        elif p in ('/estudio','/estudio.html'): self._send((ROOT/'estudio.html').read_bytes(),mime='text/html; charset=utf-8')
        elif p.startswith('/assets/'):
            import mimetypes
            asset=(ROOT/p.lstrip('/')).resolve()
            root_assets=(ROOT/'assets').resolve()
            if not asset.is_relative_to(root_assets) or asset.suffix.lower() not in ('.svg','.jpg','.jpeg','.png','.webp','.js','.css') or not asset.is_file():
                return self._send('{"error":"Arquivo não encontrado."}',404)
            self._send(asset.read_bytes(),mime=mimetypes.guess_type(str(asset))[0] or 'application/octet-stream')
        elif p=='/fase2': self._send((ROOT/'fase2.html').read_bytes(),mime='text/html; charset=utf-8')
        elif p=='/premium-direto': self._send((ROOT/'premium_direto.html').read_bytes(),mime='text/html; charset=utf-8')
        elif (m:=re.fullmatch(r'/api/premium-direto/status/(pedido-[0-9a-f]{16})',p)):
            from premium_direct import status_handler
            return status_handler(self,m.group(1))
        elif p=='/teste-foto': self._send((ROOT/'teste_foto.html').read_bytes(),mime='text/html; charset=utf-8')
        elif (m:=re.fullmatch(r'/api/photo-pilot/status/(piloto-[0-9a-f]{16})',p)):
            from photo_pilot import status_handler
            return status_handler(self,m.group(1))
        elif p=='/completar-fotos': self._send((ROOT/'completar_fotos.html').read_bytes(),mime='text/html; charset=utf-8')
        elif p=='/completar-premium': self._send((ROOT/'completar_premium.html').read_bytes(),mime='text/html; charset=utf-8')
        elif (m:=re.fullmatch(r'/premium/preview/(pedido-[0-9a-f]{16})',p)):
            from premium_complete import preview_handler
            return preview_handler(self,m.group(1))
        elif (m:=re.fullmatch(r'/api/premium/status/(pedido-[0-9a-f]{16})',p)):
            from premium_complete import status_handler
            return status_handler(self,m.group(1))
        elif p=='/api/premium/last':
            from premium_complete import last_handler
            return last_handler(self)
        elif (m:=re.fullmatch(r'/fotos/preview/(pedido-[0-9a-f]{16})',p)):
            from fotos_complete import preview_handler
            return preview_handler(self,m.group(1))
        elif (m:=re.fullmatch(r'/api/fotos/status/(pedido-[0-9a-f]{16})',p)):
            from fotos_complete import status_handler
            return status_handler(self,m.group(1))
        elif p=='/completar-vitrine': self._send((ROOT/'completar_vitrine.html').read_bytes(),mime='text/html; charset=utf-8')
        elif p=='/completar-perfil': self._send((ROOT/'completar_perfil.html').read_bytes(),mime='text/html; charset=utf-8')
        elif p=='/api/vitrine/last':
            from vitrine_complete import last_import_handler
            return last_import_handler(self)
        elif p=='/api/fase2/last':
            from fase2_api import last_brief_handler
            last_brief_handler(self)
        elif p=='/revisar': self._send((ROOT/'revisar.html').read_bytes(),mime='text/html; charset=utf-8')
        elif p=='/galeria_celular.js': self._send((ROOT/'galeria_celular.js').read_bytes(),mime='text/javascript; charset=utf-8')
        elif p=='/api/plans': self._send(json.dumps(PLANS,ensure_ascii=False))
        elif p=='/api/status': self._send(json.dumps({'ai_ready':available() and mode()!='off','ai_mode':mode(),'ai_model':__import__('os').environ.get('STAYVISION_GEMINI_MODEL',DEFAULT_MODEL) if available() else None,'public_server':False,'payments_enabled':False,'commercial_rehearsal':True,'plans_with_photo_api':['fotos','perfil','vitrine','premium'],'real_plan_checkout_enabled':__import__('real_plan_checkout').enabled(),'one_real_e2e_enabled':__import__('real_plan_checkout').pilot_mode(),'release':'STAYVISION_V3_30_R1_PILOTO_AUTO_CONTROLADO','image_ai_enabled':image_enabled(),'image_ai_model':image_model() if image_enabled() else None,'images_remaining':image_remaining(),'edit_goal':edit_goal(),
                            'photo_quality_engine':'SV_PHOTO_QUALITY_3_2','visual_calls':{'piloto_uma_foto':1,'perfil_amostra':1,'perfil_com_logo_aprovado':5,'perfil':6,'vitrine_reusando_perfil':10,'vitrine':16,'premium_reutilizando_vitrine_fotos':3,'premium_direto_1_a_8_fotos':'19 + quantidade de fotos','premium_completo_sem_reuso':27,'fotos':6}}))
        elif p=='/api/orders':
            jobs=sorted([d.name for d in OUT.iterdir() if d.is_dir() and JOB_RE.fullmatch(d.name)],reverse=True)
            results=[]
            for job in jobs[:100]:
                try:results.append(get_order(job))
                except (OSError,ValueError,KeyError):pass
            self._send(json.dumps(results,ensure_ascii=False))
        elif (m:=re.fullmatch(r'/api/orders/(pedido-[0-9a-f]{16})',p)):
            try:self._send(json.dumps(get_order(m.group(1)),ensure_ascii=False))
            except FileNotFoundError:self._send('{"error":"Pedido não encontrado."}',404)
        elif (m:=re.fullmatch(r'/preview/(pedido-[0-9a-f]{16})/(original|photo|feed|profile|cover|story|extra)/([1-9][0-9]?)',p)):
            job,kind,number=m.group(1),m.group(2),int(m.group(3))
            relative={'original':f'00_originais/original_{number:02d}.jpg',
                      'photo':f'01_fotos_tratadas/foto_profissional_{number:02d}.jpg',
                      'feed':f'03_vitrine_digital/feed_{number:02d}_1080x1350.jpg',
                      'story':f'03_vitrine_digital/story_{number:02d}_1080x1920.jpg',
                      'extra':f'04_feed_premium/arte_extra_{number:02d}_1080x1350.png',
                      'profile':'02_perfil_express/previa_perfil.png',
                      'cover':f'02_perfil_express/capa_destaque_{number:02d}.png'}[kind]
            try:
                f=order_dir(job)/relative
                if not f.is_file():raise FileNotFoundError()
                self._send(f.read_bytes(),mime='image/png' if kind in ('profile','extra','cover') else 'image/jpeg')
            except FileNotFoundError:self._send('{"error":"Imagem não encontrada."}',404)
        elif (m:=re.fullmatch(r'/preview/(pedido-[0-9a-f]{16})/instagram/(perfil|feed|banner)',p)):
            job,kind=m.group(1),m.group(2)
            names={'perfil':'perfil_completo_1080x1920.png','feed':'grade_publicacoes_1080x1350.png','banner':'apresentacao_premium_2000x1250.png'}
            try:
                file=order_dir(job)/'06_previas_instagram'/names[kind]
                if not file.is_file():raise FileNotFoundError()
                self._send(file.read_bytes(),mime='image/png')
            except FileNotFoundError:self._send('{"error":"Prévia não encontrada."}',404)
        elif re.fullmatch(r'/download/(?:(?:aprovado-)?pedido|piloto)-[0-9a-f]{16}\.zip',p):
            from commerce_flow import is_commercial_job
            download_job=re.search(r'pedido-[0-9a-f]{16}',p)
            if download_job and is_commercial_job(download_job.group(0)):
                return self._send('{"error":"Entrega comercial protegida: use a galeria após aprovação."}',403)
            file=OUT/Path(p).name
            if file.exists(): self._send(file.read_bytes(),mime='application/zip',extra={'Content-Disposition':f'attachment; filename="{file.name}"'})
            else: self._send('{"error":"Arquivo não encontrado."}',404)
        else: self._send('{"error":"Rota não encontrada."}',404)
    def do_POST(self):
        route=urlparse(self.path).path
        if route=='/api/admin/login':
            from admin_panel import login
            return login(self)
        if route=='/api/cliente/checkout-real':
            from real_plan_checkout import customer_checkout
            return customer_checkout(self)
        if route=='/api/cliente/verificar-pagamento-real':
            from real_plan_checkout import customer_check
            return customer_check(self)
        if route=='/api/admin/plan-payment/check':
            from real_plan_checkout import admin_check
            return admin_check(self)
        if route=='/api/admin/pilot/create':
            from pilot_live_payment import admin_create
            return admin_create(self)
        if route=='/api/admin/pilot/check':
            from pilot_live_payment import admin_check
            return admin_check(self)
        if route=='/api/admin/logout':
            from admin_panel import logout
            return logout(self)
        if (m:=re.fullmatch(r'/api/admin/orders/(pedido-[0-9a-f]{16})/(demo-payment|start-production|review|revoke)',route)):
            from admin_panel import action
            return action(self,m.group(1),m.group(2))
        if route=='/api/cliente/verificar-pagamento-teste':
            from checkout_gateway import customer_verify
            return customer_verify(self)
        if route=='/api/cliente/checkout-teste':
            from checkout_gateway import customer_checkout
            return customer_checkout(self)
        if route=='/api/cliente/pedido':
            from commerce_flow import create_customer
            return create_customer(self)
        if route=='/api/operacao/verificar':
            from commerce_flow import verify_operator
            return verify_operator(self)
        if route=='/api/operacao/simular-pagamento':
            from commerce_flow import operator_payment
            return operator_payment(self)
        if route=='/api/operacao/iniciar-premium':
            from commerce_flow import operator_start
            return operator_start(self)
        if (m:=re.fullmatch(r'/api/orders/(pedido-[0-9a-f]{16})/delivery/revoke',route)):
            from admin_panel import authorized
            if not authorized(self):return self._send('{"error":"Entre no painel administrativo para revogar."}',401)
            origin=self.headers.get('Origin','')
            if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
                return self._send('{"error":"Origem não autorizada"}',403)
            from delivery_mobile import revoke
            revoke(m.group(1))
            return self._send('{"ok":true,"message":"Link revogado."}')
        if (m:=re.fullmatch(r'/api/orders/(pedido-[0-9a-f]{16})/review',route)):
            from admin_panel import authorized
            if not authorized(self):return self._send('{"error":"Entre no painel administrativo para revisar."}',401)
            return self.review_order(m.group(1))
        if route in ('/api/premium-direto/import','/api/premium-direto/finish'):
            from premium_direct import import_handler, finish_handler
            return import_handler(self) if route.endswith('/import') else finish_handler(self)
        if route in ('/api/photo-pilot/import','/api/photo-pilot/finish'):
            from photo_pilot import import_handler,finish_handler
            return import_handler(self) if route.endswith('/import') else finish_handler(self)
        if route=='/api/photo-diagnostics':
            # Pré-avaliação gratuita e local, ANTES de qualquer chamada Gemini/fal.ai.
            try:
                origin=self.headers.get('Origin','')
                if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
                    raise ValueError('Origem não autorizada.')
                if not self.headers.get('Content-Type','').lower().startswith('application/json'):
                    raise ValueError('Envie JSON com as imagens.')
                n=int(self.headers.get('Content-Length','0'))
                if not 2<=n<=MAX_POST:raise ValueError('Lote de fotos muito grande.')
                body=json.loads(self.rfile.read(n))
                images=body.get('images')
                if not isinstance(images,list) or not 1<=len(images)<=8:
                    raise ValueError('Envie de 1 a 8 fotos.')
                from photo_adapt import from_data_url
                from photo_quality import diagnose
                reports=[]
                for i,photo in enumerate(images,1):
                    if not isinstance(photo,dict):raise ValueError(f'Foto {i} inválida.')
                    report=diagnose(from_data_url(photo.get('data'),max_side=2400))
                    report['photo_number']=i
                    reports.append(report)
                self._send(json.dumps({'ok':True,'diagnoses':reports,'api_calls':0,
                    'notice':'O diagnóstico não utiliza IA e não substitui aprovação humana. ' 
                             'Fotos gravemente borradas podem não ser recuperáveis.'},ensure_ascii=False))
            except (TypeError,ValueError,OverflowError,KeyError) as ex:
                self._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
            return
        if route=='/api/premium/import':
            from premium_complete import import_handler
            return import_handler(self)
        if route=='/api/premium/finish':
            from premium_complete import finish_handler
            return finish_handler(self)
        if route=='/api/fotos/import':
            from fotos_complete import prepare_handler
            return prepare_handler(self)
        if route=='/api/fotos/finish':
            from fotos_complete import finish_handler
            return finish_handler(self)
        if route=='/api/vitrine/import':
            from vitrine_complete import prepare_handler
            return prepare_handler(self)
        if route=='/api/vitrine/finish':
            from vitrine_complete import finish_handler
            return finish_handler(self)
        if route=='/api/perfil/import-sample':
            from profile_complete import prepare_sample_handler
            return prepare_sample_handler(self)
        if route=='/api/perfil/finish':
            from profile_complete import finish_handler
            return finish_handler(self)
        if route=='/api/fase2/brief':
            from fase2_api import create_brief_handler
            return create_brief_handler(self)
        if route=='/api/fase2/recheck':
            from fase2_api import recheck_brief_handler
            return recheck_brief_handler(self)
        if route=='/api/fase2/sample':
            from fase2_api import sample_handler
            return sample_handler(self)
        if route=='/api/brief-preview': return self.preview_brief()
        if route != '/api/generate': return self._send('{"error":"Rota inválida."}',404)
        try:
            if not self.headers.get('Content-Type','').lower().startswith('application/json'):
                return self._send('{"error":"Conteúdo inválido: esperado application/json."}',415)
            origin=self.headers.get('Origin','')
            if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
                return self._send('{"error":"Origem não autorizada para este aplicativo local."}',403)
            n=int(self.headers.get('Content-Length','0'))
            if not(100<n<=MAX_POST): return self._send('{"error":"Pedido muito grande; máximo 70 MB."}',413)
            o=json.loads(self.rfile.read(n))
            plan=o.get('plan','')
            if plan not in PLANS: return self._send('{"error":"Plano inválido."}',400)
            if not image_enabled():
                return self._send(json.dumps({'error':'GPT Image desligado. Nesta versão nenhum plano gera artes com templates.'},ensure_ascii=False),503)
            if not (available() and mode()!='off'):
                return self._send(json.dumps({'error':'Gemini obrigatório: configure GEMINI_API_KEY antes da geração.'},ensure_ascii=False),503)
            pictures=o.get('images',[])
            if not isinstance(pictures,list) or not(0<=len(pictures)<=8) or (plan in ('fotos','vitrine','premium') and not pictures): return self._send('{"error":"Fotos são obrigatórias para este plano; Perfil Express aceita zero fotos."}',400)
            job='pedido-'+secrets.token_hex(8); folder=OUT/job; up=folder/'input'; up.mkdir(parents=True)
            paths=[]
            from photo_adapt import from_data_url, to_jpeg
            for i,picture in enumerate(pictures,1):
                if not isinstance(picture,dict):raise ValueError(f'Foto {i} inválida.')
                raw=picture.get('data','')
                im=from_data_url(raw,max_side=2400)
                name=str(picture.get('name') or '')
                slug=re.sub(r'[^A-Za-z0-9_-]+','_',Path(name).stem)[:42] or 'foto'
                path=up/f'upload_{i:02d}_{slug}.jpg'
                to_jpeg(im,path)
                paths.append(path)
            logo_path=None
            logo=o.get('logo_image')
            if logo is not None:
                if plan=='fotos':raise ValueError('Fotos Business não produz identidade visual.')
                if not isinstance(logo,dict):raise ValueError('Logotipo inválido.')
                logo_path=up/'logo_existente.jpg'
                to_jpeg(from_data_url(logo.get('data'),logo=True),logo_path)
            sample_only = o.get('sample_only') is True
            if sample_only and plan!='perfil':raise ValueError('Amostra de uma arte somente para Perfil Express.')
            from image_ai import preflight
            preflight(count_visual_calls(plan,len(paths),sample_only))
            arch=build(folder/'entrega',plan,o.get('brand'),o.get('instagram'),o.get('contact'),paths,sample_only=sample_only,activity=o.get('activity',''),preserve_existing_logo=bool(logo_path),logo_reference_path=logo_path)
            file=OUT/(job+'.zip'); arch.replace(file)
            info=json.loads((folder/'entrega'/'INFO_PEDIDO.json').read_text(encoding='utf-8'))
            self._send(json.dumps({'ok':True,'url':f'/download/{file.name}','review_url':f'/revisar?job={job}','job':job,'photos':len(paths),'photo_edit_engine':info.get('photo_edit_engine'),'ai_provider':info.get('generated_text_source'),'ai_notes':info.get('ai_notes',[]),'message':'Amostra NÃO entregável' if sample_only else 'Material gerado. Revise antes de entregar.'},ensure_ascii=False))
        except (ValueError,KeyError,TypeError,OverflowError) as e:
            self._send(json.dumps({'error':str(e)},ensure_ascii=False),400)
        except RuntimeError as e:
            self._send(json.dumps({'error':str(e)},ensure_ascii=False),503)
        except Exception as e:
            print('ERRO DE PRODUÇÃO:',repr(e),file=sys.stderr)
            self._send('{"error":"Erro interno ao processar o pedido. Consulte o terminal."}',500)
    def preview_brief(self):
        """Exclusivamente regras locais, sem Gemini, fal.ai ou creditos."""
        from engine import create_brief,normalize_instagram,normalize_contact,limit
        try:
            origin=self.headers.get('Origin','')
            if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
                return self._send('{"error":"Origem nao autorizada."}',403)
            n=int(self.headers.get('Content-Length','0'))
            if not 2<=n<=12000:raise ValueError('Dados invalidos.')
            data=json.loads(self.rfile.read(n))
            brand=limit(data.get('brand',''),45)
            if len(brand)<2:raise ValueError('Informe o nome da empresa.')
            ig=normalize_instagram(data.get('instagram'))
            contact=normalize_contact(data.get('contact'))
            names=data.get('names',[])
            if not isinstance(names,list) or len(names)>8:raise ValueError('Fotos invalidas.')
            # So nomes, sem dados de imagem nem upload.
            from pathlib import Path as _Path
            sample=[_Path(re.sub(r'[^A-Za-z0-9_.-]','_',str(s)[:90])) for s in names]
            base=create_brief(brand,ig,contact,sample,activity=data.get('activity',''))
            self._send(json.dumps({'ok':True,'mode':'REGRAS_LOCAIS_SEM_IA',
                'sector_guess':base['segment'],'activity_provided':base.get('activity_provided',False),'tagline_example':base['tagline'],
                'highlight_examples':base['highlights'],
                'message':'Previa textual gratuita por regras. Nao analisou pixels, nao usou Gemini ou GPT Image e nao aprovou a identidade.'},ensure_ascii=False))
        except (ValueError,KeyError,TypeError,OverflowError) as ex:
            self._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)

    def review_order(self,job):
        try:
            origin=self.headers.get('Origin','')
            if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
                return self._send('{"error":"Origem não autorizada."}',403)
            n=int(self.headers.get('Content-Length','0'))
            if n<2 or n>10000:return self._send('{"error":"Dados inválidos."}',400)
            value=json.loads(self.rfile.read(n))
            decision=value.get('decision')
            if decision not in ('approved','rejected'):raise ValueError('Decisão inválida.')
            checks=value.get('checks',{})
            if not isinstance(checks,dict):raise ValueError('Checklist inválido.')
            checks={k:checks.get(k) is True for k in REVIEW_CHECKS}
            notes=str(value.get('notes',''))[:1500]
            if decision=='approved' and not all(checks.values()):
                raise ValueError('Todos os quatro itens precisam estar aprovados.')
            info=get_order(job)
            from commerce_flow import is_commercial_job, is_paid
            if decision=='approved' and is_commercial_job(job) and not is_paid(job):
                raise ValueError('Pedido comercial sem confirmação de pagamento; aprovação bloqueada.')
            if decision=='approved' and info.get('brand_conflict') and len(notes.strip())<15:
                raise ValueError('Divergencia entre marca e fotos: registre nas observacoes como a identidade foi conferida.')
            if decision=='approved' and info['missing']:
                raise ValueError('Não é possível aprovar este pedido: '+ '; '.join(info['missing']))
            state={'status':'APROVADO' if decision=='approved' else 'REPROVADO',
                   'checks':checks,'notes':notes,'reviewed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'review_type':'revisão interna manual; sem verificação automática de fidelidade'}
            folder=order_dir(job)
            (folder/'REVISAO_INTERNA.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
            archive=OUT/f'aprovado-{job}.zip'
            from delivery_mobile import create as create_delivery, revoke as revoke_delivery
            revoke_delivery(job)
            if decision=='approved':
                with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
                    for f in folder.rglob('*'):
                        if f.is_file():z.write(f,f.relative_to(folder))
            elif archive.exists():archive.unlink()
            delivery_link=create_delivery(job) if decision=='approved' else None
            self._send(json.dumps({'ok':True,'job':job, 'status':state['status'],'delivery_link':delivery_link,
                 'approved_download':f'/download/aprovado-{job}.zip' if decision=='approved' else None},ensure_ascii=False))
        except (FileNotFoundError,ValueError,TypeError,KeyError,OverflowError) as ex:
            self._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
        except Exception as ex:
            print('ERRO DE REVISAO:',repr(ex),file=sys.stderr)
            self._send('{"error":"Erro interno no registro de revisão."}',500)
    def log_message(self,fmt,*args):
        msg=fmt%args
        msg=re.sub(r'(/(?:entrega|api/entrega|midia|salvar)/)[A-Za-z0-9_-]{40,80}',r'\1[LINK_PRIVADO]',msg)
        msg=re.sub(r'(/(?:acompanhar|api/cliente/status)/)[A-Za-z0-9_-]{43}',r'\1[LINK_PRIVADO]',msg)
        print('[Local]',msg)

if __name__=='__main__':
    if os.environ.get('SV_PUBLIC_ORIGIN'):
        raise RuntimeError('Nao exponha app.py: use python web_public.py com controles publicos.')
    port=8786
    from commerce_flow import ADMIN_CODE, SESSION_MARK
    print('\nSTAYVISION V3.30 — AMBIENTE LOCAL')
    if __import__('auto_delivery').enabled():
        print('PILOTO REAL R$1: um pedido, uma foto, no maximo uma IA; auditoria e galeria automaticas sob condicoes.')
    print('PAINEL ADMIN: http://127.0.0.1:8786/painel')
    print('SITE INICIAL: http://127.0.0.1:8786/')
    print('FORMULARIO PREMIUM: http://127.0.0.1:8786/comprar')
    print('SESSAO DO SERVIDOR (nao e senha): '+SESSION_MARK)
    from admin_credentials import configured
    print('LOGIN ADMIN:', 'USUARIO/SENHA CONFIGURADOS' if configured() else 'LEGADO: CODIGO DO OPERADOR')
    if not configured():print('CODIGO DO OPERADOR (nao compartilhar): '+ADMIN_CODE)
    from semi_auto_queue import start_background
    start_background()
    from real_plan_checkout import start_background as start_reconciliation
    start_reconciliation()
    from checkout_gateway import start_background as start_sandbox_reconciliation
    start_sandbox_reconciliation()
    from auto_delivery import start_background as start_auto_delivery
    start_auto_delivery()
    print('Servidor SOMENTE local. Nao publicar na internet. Feche com Ctrl+C.\n')
    ThreadingHTTPServer(('127.0.0.1',port),LocalServer).serve_forever()
