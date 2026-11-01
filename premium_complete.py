"""StayVision 2.9: premium = Vitrine comprovada + Fotos comprovadas + 3 extras autorizadas.

A importação é gratuita; só generate_extras usa fal.ai. Sem simulação de
trabalho pago, sem retry após iniciar tentativa, sem publicação ou cobrança.
"""
from __future__ import annotations
import base64, hashlib, io, json, re, secrets, shutil, threading, unicodedata, zipfile
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw,ImageFont

LOCK=threading.Lock()
ACTIVE=set()
BATCH_LOCK=threading.Lock()
TAG=re.compile(r'^pedido-[0-9a-f]{16}$')
MAX_COMPRESSED=30_000_000
MAX_TOTAL_UNCOMPRESSED=145_000_000
EXTRAS=3
VIT_FILES=[
 'INFO_PEDIDO.json','05_controle_de_qualidade/briefing_criativo.json',
 '02_perfil_express/foto_de_perfil_1080.png',
 *[f'02_perfil_express/capa_destaque_{i:02d}.png' for i in range(1,6)],
 '02_perfil_express/previa_perfil.png','02_perfil_express/bio_sugerida.txt',
 '02_perfil_express/identidade_visual.txt',
 *[f'03_vitrine_digital/feed_{i:02d}_1080x1350.jpg' for i in range(1,7)],
 *[f'03_vitrine_digital/story_{i:02d}_1080x1920.jpg' for i in range(1,5)],
 '03_vitrine_digital/legendas_prontas_para_revisao.txt',
 '03_vitrine_digital/textos_stories.txt',
 '03_vitrine_digital/previa_vitrine.png',
]
FOTO_FILES=[
 'INFO_PEDIDO.json','05_controle_de_qualidade/briefing_criativo.json',
 *[f'01_fotos_tratadas/foto_profissional_{i:02d}.jpg' for i in range(1,7)]
]

def store():
    from app import OUT
    p=OUT/'premium_reuso_29';p.mkdir(parents=True,exist_ok=True)
    return p

def output_dir():
    from app import OUT
    return OUT

def load_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path,obj):
    p=Path(path);tmp=p.with_name(p.name+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)

def _norm(text):
    return re.sub(r'[^a-z0-9]+','',unicodedata.normalize('NFKD',str(text)).encode('ascii','ignore').decode().lower())

def _unpack(data,kind):
    if not isinstance(data,str) or not re.match(r'^data:application/(?:zip|x-zip-compressed|octet-stream);base64,',data):
        raise ValueError(f'Selecione o ZIP de {kind}.')
    try: raw=base64.b64decode(data.split(',',1)[1],validate=True)
    except Exception:raise ValueError(f'ZIP de {kind} inválido.')
    if len(raw)>MAX_COMPRESSED:raise ValueError(f'ZIP de {kind} acima de 30 MB.')
    return raw

def inspect_zip(raw,required,expected,source):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist();names={i.filename for i in infos if not i.is_dir()}
        if len(infos)>150 or any(i.filename.startswith(('/', '\\')) or '..' in Path(i.filename).parts or '\\' in i.filename for i in infos):
            raise ValueError(f'ZIP de {source} tem caminhos inválidos.')
        if sum(i.file_size for i in infos)>MAX_TOTAL_UNCOMPRESSED:raise ValueError('ZIP expandido excede o limite de segurança.')
        if not set(required).issubset(names):raise ValueError(f'O ZIP de {source} está incompleto. Importe uma entrega final, não uma amostra.')
        info=json.loads(z.read('INFO_PEDIDO.json'))
        if info.get('plan')!=expected or info.get('sample_only'):
            raise ValueError(f'Este arquivo não é uma entrega completa de {source}.')
        values={k:z.read(k) for k in names if k in set(required)}
        if source=='Vitrine':
            optional={
                '02_perfil_express/nome_perfil_sugerido.txt':1_500_000,
                '02_perfil_express/previa_perfil.html':1_500_000,
                '02_perfil_express/previa_bio_no_navegador.html':1_500_000,
                '02_perfil_express/bios_3_opcoes.txt':100_000,
                '02_perfil_express/logo_horizontal_escuro_1600x600.png':8_000_000,
                '02_perfil_express/logo_horizontal_claro_1600x600.png':8_000_000,
                '05_controle_de_qualidade/planejamento_editorial.json':200_000,
            }
            for name,size in optional.items():
                if name in names and z.getinfo(name).file_size<size:values[name]=z.read(name)
        return info,values

def _verify_jpg_png(data,limit_px=32_000_000):
    with Image.open(io.BytesIO(data)) as im:
        if im.width*im.height>limit_px or min(im.size)<300:raise ValueError('Uma arte tem resolução inválida.')
        im.verify()

def _get(tag):
    if not TAG.fullmatch(str(tag)):raise ValueError('Identificador inválido.')
    folder=store()/tag
    if not (folder/'estado.json').is_file():raise FileNotFoundError('Lote não localizado.')
    return folder

def _state(folder):return load_json(folder/'estado.json')

def _public(s):
    keys=('id','job','brand','status','photos_received','edited_photos','ai_compositions','photos_available','feed','stories','covers','extras_ready','extras_needed','attempts','calls_this_stage','errors')
    result={k:s.get(k) for k in keys};result['preview']='/premium/preview/'+s['id']
    result['draft_download']='/download/'+s['job']+'.zip'
    if s['status']=='REVISAO_NECESSARIA':result['review']='/revisar?job='+s['job']
    return result

def _safe_image(root,relative,raw):
    if relative.lower().endswith(('.jpg','.jpeg','.png','.webp')):_verify_jpg_png(raw)
    target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)

def _make_preview(root,state):
    """Real assets only; all posts/stories retain native aspect ratio and headlines."""
    img=Image.new('RGB',(1330,3200),'#14100e');d=ImageDraw.Draw(img)
    def font(size,bold=False):
        for p in (['C:/Windows/Fonts/arialbd.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if bold else ['C:/Windows/Fonts/arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']):
            try:return ImageFont.truetype(p,size)
            except OSError:pass
        return ImageFont.load_default()
    def t(x,y,text,sz=28,color='#f6e9df',bold=False):d.text((x,y),text,font=font(sz,bold),fill=color)
    def tile(filename,xy,w,h):
        p=root/filename
        if p.exists():
            with Image.open(p) as im:
                ph=ImageOps.fit(im.convert('RGB'),(w,h),method=Image.Resampling.LANCZOS)
                img.paste(ph,xy)
        else:d.rounded_rectangle((xy[0],xy[1],xy[0]+w,xy[1]+h),radius=10,fill='#302018')
    d.rectangle((0,0,1330,108),fill='#25160e')
    t(45,34,'STAYVISION BUSINESS  /  FEED PREMIUM',34,'#ff983e',True)
    t(50,135,state['brand'][:45],47,'#ffffff',True)
    t(50,200,'PREVIA CONSOLIDADA  •  ARQUIVOS REAIS',23,'#d0b9aa')
    # The actual prior identity is visible, not inferred from a label.
    tile('02_perfil_express/foto_de_perfil_1080.png',(1100,125),164,164)
    t(50,270,'PERFIL EXPRESS  •  5 CAPAS REAPROVEITADAS',23,'#ff983e',True)
    for i in range(5):tile(f'02_perfil_express/capa_destaque_{i+1:02d}.png',(50+i*250,315),168,168)
    t(50,525,'6 POSTS REAPROVEITADOS DA VITRINE',27,'#ff983e',True)
    for i in range(6):
        tile(f'03_vitrine_digital/feed_{i+1:02d}_1080x1350.jpg',(45+(i%3)*425,575+(i//3)*512),399,499)
    t(50,1610,'6 IMAGENS  •  5 TRATAMENTOS + 1 COMPOSICAO IA',24,'#ff983e',True)
    for i in range(6):tile(f'01_fotos_tratadas/foto_profissional_{i+1:02d}.jpg',(45+i*210,1665),196,240)
    t(50,1930,'4 STORIES REAPROVEITADOS DA VITRINE',26,'#ff983e',True)
    for i in range(4):tile(f'03_vitrine_digital/story_{i+1:02d}_1080x1920.jpg',(45+i*318,1985),290,516)
    t(50,2545,'3 ARTES EXTRAS PREMIUM',27,'#ff983e',True)
    for i in range(3):
        p=f'04_feed_premium/arte_extra_{i+1:02d}_1080x1350.png';x=45+i*425
        if (root/p).exists():tile(p,(x,2600),399,499)
        else:
            d.rounded_rectangle((x,2600,x+399,3099),radius=14,outline='#95592d',width=3)
            t(x+28,2835,'PENDENTE DE GERACAO',20,'#d7b19a',True)
    t(50,3142,'Revisao humana obrigatoria  •  Nenhuma publicacao ou pagamento automatico',18,'#cba78d')
    img.save(root/'PREVIA_PREMIUM.png',optimize=True)

def _make_archive(root,job):
    out=output_dir()/(job+'.zip');tmp=out.with_suffix('.zip.tmp')
    with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for item in sorted(root.rglob('*')):
            if item.is_file():z.write(item,item.relative_to(root))
    tmp.replace(out)
    return out

def prepare_from_bytes(vitrine_raw,fotos_raw):
    """Reusable offline test entry point. Never calls a provider."""
    fingerprint=hashlib.sha256(hashlib.sha256(vitrine_raw).digest()+hashlib.sha256(fotos_raw).digest()).hexdigest()
    for old in store().iterdir():
        if old.is_dir() and (old/'estado.json').is_file():
            try:
                prior=_state(old)
                if prior.get('source_pair_sha256')==fingerprint:
                    return prior  # Same ZIPs: preserve existing status, never create a new paid job.
            except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError):pass
    vi,vfiles=inspect_zip(vitrine_raw,VIT_FILES,'vitrine','Vitrine')
    ph,ffiles=inspect_zip(fotos_raw,FOTO_FILES,'fotos','Fotos Business')
    if not _norm(vi.get('brand')) or _norm(vi.get('brand'))!=_norm(ph.get('brand')):
        raise ValueError('Os ZIPs são de empresas diferentes. Confira os nomes antes de combinar os pedidos.')
    if str(vi.get('activity','')).casefold()!=str(ph.get('activity','')).casefold():
        raise ValueError('Os ramos informados são diferentes. Revise a empresa antes de unir os arquivos.')
    if int(vi.get('generative_design_count',0))<16:raise ValueError('Vitrine sem 10 artes e identidade comprovadas.')
    if ph.get('photo_edit_engine')!='generative_image_ai' or int(ph.get('generative_photo_count',0))<6:
        raise ValueError('Fotos Business incompleto: não há seis imagens geradas por IA.')
    n=int(ph.get('photo_edits',ph.get('photos_received',0)));creative=int(ph.get('creative_compositions',0))
    if not (3<=n<=6 and n+creative==6):raise ValueError('Número de tratamentos/composições inconsistente.')
    job='pedido-'+secrets.token_hex(8)
    lot=store()/job;lot.mkdir(parents=True,exist_ok=False)
    from app import OUT
    root=OUT/job/'entrega';root.mkdir(parents=True,exist_ok=False)
    try:
        for name,raw in vfiles.items():
            if name not in ('INFO_PEDIDO.json','05_controle_de_qualidade/briefing_criativo.json'):_safe_image(root,name,raw)
        for name,raw in ffiles.items():
            if name.startswith('01_fotos_tratadas/'):_safe_image(root,name,raw)
        with zipfile.ZipFile(io.BytesIO(fotos_raw)) as z:
            for k in z.namelist():
                if re.fullmatch(r'00_originais/original_\d{2}\.jpg',k) or re.fullmatch(r'05_controle_de_qualidade/(?:antes_depois|referencia_composicao)_\d{2}\.jpg',k) or re.fullmatch(r'05_controle_de_qualidade/AVISO_COMPOSICAO_\d{2}\.txt',k):
                    if z.getinfo(k).file_size>12_000_000:raise ValueError('Uma imagem ou aviso é grande demais.')
                    _safe_image(root,k,z.read(k))
        qc=root/'05_controle_de_qualidade';qc.mkdir(exist_ok=True)
        (qc/'briefing_criativo.json').write_bytes(vfiles['05_controle_de_qualidade/briefing_criativo.json'])
        (qc/'fonte_vitrine.json').write_bytes(vfiles['INFO_PEDIDO.json'])
        (qc/'fonte_fotos.json').write_bytes(ffiles['INFO_PEDIDO.json'])
        trace={'vitrine_sha256':hashlib.sha256(vitrine_raw).hexdigest(),'fotos_sha256':hashlib.sha256(fotos_raw).hexdigest(),
               'vitrine_plan':'vitrine','fotos_plan':'fotos','provider_calls_during_import':0,
               'source_artworks_reused':16,'source_photographs_reused':6,'additional_artworks_required':3,
               'genuine_edited_photos':n,'ai_compositions':creative,'approval_required':True}
        write_json(qc/'rastreamento_reuso.json',trace)
        state={'id':job,'job':job,'brand':vi['brand'],'status':'PREPARADO_SEM_COBRANCA','photos_received':n,'edited_photos':n,
               'ai_compositions':creative,'photos_available':6,'feed':6,'stories':4,'covers':5,'extras_ready':0,'extras_needed':3,
               'attempts':0,'calls_this_stage':0,'errors':[],'created_utc':datetime.now(timezone.utc).isoformat(),
               'human_approval_required':True,'no_auto_retry':True,'source_pair_sha256':fingerprint}
        info=dict(vi)
        info.update({'plan':'premium','plan_name':'Feed Premium','price_test_brl':399.90,
            'photos_received':n,'photo_edits':n,'creative_compositions':creative,'premium_photos_included':6,
            'generative_photo_count':6,'generative_design_count':16,'photo_edit_engine':'generative_image_ai',
            'premium_extras_completed':0,'calls_this_run':0,'expected_api_calls':3,'sample_only':False,
            'brand_engine':'gpt_image_2_5_fal_ai','premium_status':'AGUARDANDO_3_ARTES_EXTRAS',
            'source_vitrine_reused':True,'source_fotos_reused':True,'payment_connected':False,'human_approval_required':True})
        write_json(root/'INFO_PEDIDO.json',info)
        (qc/'relatorio.txt').write_text('STAYVISION / FEED PREMIUM — RASCUNHO\n'
            'Identidade visual + 6 posts + 4 stories reaproveitados do ZIP Vitrine.\n'
            f'6 fotos reaproveitadas do ZIP Fotos: {n} edicoes de fotos reais e {creative} composicao(oes) de IA.\n'
            'Três artes adicionais ainda NÃO GERADAS. Importação GRATUITA, nenhuma nova chamada paga.\n'
            'Até oito fotos significa limite máximo, não oito fotografias tratadas quando o cliente enviou cinco.\n'
            'Aprovação humana obrigatória; não publicar ou cobrar automaticamente.\n',encoding='utf-8')
        (root/'LEIA_ANTES_DE_ENTREGAR.txt').write_text('RASCUNHO, NÃO ENTREGAR AO CLIENTE.\nFaltam 3 artes extras da versão Premium.\n'
             f'Há {n} fotos reais tratadas e {creative} composição IA, não 8 tratamentos de fotos.\n'
             'Verifique produtos, marcas, textos, preços e direitos antes de aprovar.\n',encoding='utf-8')
        write_json(lot/'estado.json',state)
        _make_preview(root,state)
        _make_archive(root,job)
        return state
    except Exception:
        shutil.rmtree(lot,ignore_errors=True);shutil.rmtree(OUT/job,ignore_errors=True)
        raise

def _reply(h,obj,code=200):h._send(json.dumps(obj,ensure_ascii=False),code)

def _read(h,maxsize=82_000_000):
    if not h.headers.get('Content-Type','').lower().startswith('application/json'):raise ValueError('Requisição JSON necessária.')
    origin=h.headers.get('Origin','')
    if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):raise ValueError('Origem não autorizada.')
    size=int(h.headers.get('Content-Length','0'))
    if size<2 or size>maxsize:raise ValueError('Arquivos muito grandes.')
    return json.loads(h.rfile.read(size))

def import_handler(h):
    try:
        v=_read(h)
        s=prepare_from_bytes(_unpack(v.get('vitrine_zip'),'Vitrine Digital'),_unpack(v.get('fotos_zip'),'Fotos Business'))
        _reply(h,{'ok':True,**_public(s),'message':'Perfil + Vitrine + Fotos reunidos ou recuperados, sem chamadas IA. Confira status antes de gerar extras.'})
    except (ValueError,KeyError,TypeError,zipfile.BadZipFile,OverflowError,json.JSONDecodeError) as e:_reply(h,{'error':str(e)},400)
    except Exception as e:
        print('[premium] import error',type(e).__name__,str(e)[:180]);_reply(h,{'error':'Falha ao importar os ZIPs. Sem uso de créditos.'},500)

def status_handler(h,tag):
    try:
        root=_get(tag);s=_state(root)
        with BATCH_LOCK:alive=tag in ACTIVE
        if s['status']=='EM_PRODUCAO' and not alive:
            s['status']='INTERROMPIDO_SEM_REPETICAO';s['errors'].append('Servidor reiniciado. Confira painel fal.ai. Não repetir chamadas.')
            write_json(root/'estado.json',s)
        _reply(h,{'ok':True,**_public(s)})
    except (ValueError,FileNotFoundError):_reply(h,{'error':'Lote premium não localizado.'},404)

def preview_handler(h,tag):
    try:
        folder=_get(tag)
        h._send((output_dir()/tag/'entrega'/'PREVIA_PREMIUM.png').read_bytes(),mime='image/png')
    except (ValueError,FileNotFoundError):h._send('{"error":"Prévia não encontrada."}',404)

def _extra_concept(n):
    return [
      ('Detalhes de perto','Macro editorial dos detalhes REAIS que a foto apresenta, sem inventar materiais, produtos ou funcionalidades.'),
      ('Uma nova perspectiva','Composição publicitária alternada: ângulo, luz e espaço negativo diferentes das seis peças da Vitrine.'),
      ('Conheça a marca','Peça institucional de encerramento, com a identidade aprovada e área apropriada para CTA posterior.'),
    ][n]

def generate_extras(folder,gen=None):
    """Called after status is EM_PRODUCAO. Test runner may pass a zero-cost generator."""
    from image_ai import generate_visual
    from vitrine_complete import editorial_finish
    from app import audit_artifacts
    gen=gen or generate_visual
    state=_state(folder);job=state['job'];root=output_dir()/job/'entrega';qa=root/'05_controle_de_qualidade'
    rawmeta=[]
    try:
        with Image.open(root/'02_perfil_express/foto_de_perfil_1080.png') as log:
            logo=log.convert('RGB').copy()
        briefs=load_json(qa/'briefing_criativo.json')
        brief=briefs.get('direction',{})
        for i in range(3):
            state=_state(folder)
            state['attempts']=i+1;state['calls_this_stage']=i+1
            write_json(folder/'estado.json',state)
            source=root/'00_originais'/f'original_{(i%state["photos_received"])+1:02d}.jpg'
            if not source.exists():source=root/'01_fotos_tratadas'/f'foto_profissional_{i+1:02d}.jpg'
            theme,angle=_extra_concept(i)
            prompt=(f'Create distinct, original high-end creative campaign photo for real business {state["brand"]}. '
                  f'Creative focus: {theme}. {angle} Reference photo depicts actual customer products. '
                   'Preserve exactly the recognizable original subject, number of visible items, colors, ' 
                  'shapes, real-world details, logos and any visible labels. The subject may be a ' 
                  'service, person, object or place, not necessarily food or beverage. ' 
                  'Use the logo solely to guide color palette and identity; avoid giant logo-symbol repetition. ' 
                  'No invented products, labels, prices, offers, people, claims, written text or watermarks. '
                  f'Color palette: {brief.get("accent","#FF6E16")} and harmonized complementary tones. '
                  'Premium commercial photography, polished art direction, realistic texture and powerful clear subject. '
                  'Leave room at the bottom for a precise externally applied headline; no visible text.')
            image,log=gen(prompt,references=[source,logo],size=(1088,1360),quality='high',role=f'premium_extra_{i+1}')
            if image is None:raise RuntimeError('Fal.ai não retornou imagem.')
            extra=root/'04_feed_premium';extra.mkdir(exist_ok=True)
            # Editorial finish expects JPEG; convert only AFTER professional typography.
            jpeg=extra/f'_working_extra_{i+1:02d}.jpg'
            ImageOps.fit(image.convert('RGB'),(1080,1350),Image.Resampling.LANCZOS).save(jpeg,quality=95)
            editorial_finish(jpeg,'feed',theme,state['brand'],brief.get('accent','#FF6E16'),logo)
            with Image.open(jpeg) as finalized:
                finalized.save(extra/f'arte_extra_{i+1:02d}_1080x1350.png',format='PNG',optimize=True)
            jpeg.unlink(missing_ok=True)
            rawmeta.append(log)
            state['extras_ready']=i+1;state['extras_needed']=2-i
            write_json(folder/'estado.json',state)
        state=_state(folder)
        data=load_json(root/'INFO_PEDIDO.json')
        data.update({'generative_design_count':19,'premium_extras_completed':3,'calls_this_run':3,
                     'premium_status':'REVISAO_HUMANA_OBRIGATORIA'})
        write_json(root/'INFO_PEDIDO.json',data)
        write_json(qa/'edicao_de_imagens.json',{'image_engine':'fal_gpt_image_2_5',
             'premium_extra_attempts':3,'premium_extra_completed':3,'source_artworks_reused':16,
             'photos_reused':6,'gemini_calls_this_stage':0,'details':rawmeta,
             'human_approval_required':True})
        (qa/'relatorio.txt').write_text(
             'STAYVISION / FEED PREMIUM — PARA REVISÃO\n'
             'Vitrine reutilizada: 1 logo, 5 capas, 6 posts, 4 stories, bio e legendas.\n'
             f'Fotos reutilizadas: {state["edited_photos"]} edições de fotos reais e {state["ai_compositions"]} composição(ões) de IA.\n'
             '3 artes extras novas geradas via fal.ai, sem novo Gemini.\n'
             'PREÇO DE REFERÊNCIA DO PLANO: R$ 399,90 (checkout desligado).\n'
             'ATENÇÃO: conferir fidelity de produto/rótulos, textos e direitos. Revisão humana obrigatória.\n',encoding='utf-8')
        (root/'LEIA_ANTES_DE_ENTREGAR.txt').write_text('PACOTE COMPLETO PARA REVISÃO INTERNA; NÃO ENTREGAR SEM APROVAR.\n'
            f'Contém {state["edited_photos"]} fotos originais tratadas + {state["ai_compositions"]} composição IA; não há 8 originais tratados.\n'
            'Foram geradas 3 artes adicionais Premium. Conferir fidelidade de produtos, ofertas, rótulos, marcas e direitos.\n',encoding='utf-8')
        issues=audit_artifacts(root,'premium',data)
        if issues:raise RuntimeError('Auditoria detectou problemas: '+'; '.join(issues))
        _make_preview(root,state)
        _make_archive(root,job)
        state['status']='REVISAO_NECESSARIA';state['extras_ready']=3;state['extras_needed']=0
        write_json(folder/'estado.json',state)
    except Exception as e:
        state=_state(folder);state['status']='INTERROMPIDO_SEM_REPETICAO';state['errors'].append(str(e)[:260]);write_json(folder/'estado.json',state)
        print('[premium] interrompido - sem retry:',repr(e))
    finally:
        with BATCH_LOCK:ACTIVE.discard(job)
        LOCK.release()

def finish_handler(h):
    try:
        d=_read(h,5000)
        if d.get('confirm')!='AUTORIZO_TRES_ARTES':raise ValueError('Confirmação para três chamadas ausente.')
        folder=_get(str(d.get('id','')));state=_state(folder)
        from image_ai import preflight,enabled
        if not enabled():raise ValueError('Fal.ai desativada. Reinicie no modo 6.')
        if state['status']!='PREPARADO_SEM_COBRANCA':raise ValueError('Este lote já iniciou ou terminou. Nunca repetir automaticamente.')
        preflight(3)
        if not LOCK.acquire(blocking=False):raise ValueError('Outra produção Premium está ativa. Não reenviar.')
        try:
            with BATCH_LOCK:
                state=_state(folder)
                if state['status']!='PREPARADO_SEM_COBRANCA':raise ValueError('Lote já utilizado.')
                state['status']='EM_PRODUCAO';write_json(folder/'estado.json',state);ACTIVE.add(state['job'])
            threading.Thread(target=generate_extras,args=(folder,),daemon=True).start()
        except Exception:
            LOCK.release();raise
        _reply(h,{'ok':True,'id':state['id'],'status':'EM_PRODUCAO','message':'Geração iniciada. Recupere o progresso, nunca reinicie o lote.'},202)
    except FileNotFoundError:_reply(h,{'error':'Lote não encontrado.'},404)
    except (ValueError,RuntimeError,TypeError) as e:_reply(h,{'error':str(e)},400)

def last_handler(h):
    try:
        folders=sorted((p for p in store().iterdir() if p.is_dir() and (p/'estado.json').exists()),key=lambda p:p.stat().st_mtime,reverse=True)
        if not folders:raise ValueError('Ainda não há Premium importado.')
        state=_state(folders[0]);_reply(h,{'ok':True,**_public(state)})
    except (ValueError,KeyError,TypeError) as e:_reply(h,{'error':str(e)},400)
