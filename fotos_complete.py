"""Fase 2.8: Fotos Business, 3 a 6 referências para seis peças com estado persistente.

- Importação e validação local (zero IA, zero cobrança).
- Inicia com 3 a 6 fotos, com opt-in explícito para 6 chamadas autorizadas.
- Fotos fornecidas são tratadas; vagas restantes viram composições rotuladas como IA.
- Uma tentativa por fotografia; sem repetição automática, inclusive em erros.
- Entrega em ZIP marcado PARA REVISAO, nunca liberação automática ao cliente.
"""
from __future__ import annotations
import base64
import hashlib
import io
import os
import json
import re
import secrets
import threading
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

WORKER_LOCK = threading.Lock()
BATCH_LOCK = threading.Lock()
ACTIVE_BATCHES = set()
MAX_IMAGE_BYTES = 8_000_000
MAX_POST = 74_000_000
JOB_ID = re.compile(r'^pedido-[a-f0-9]{16}$')
SECTOR_NAMES = {'bebidas':'Bebidas / delivery','hamburgueria':'Hamburgueria','pizzaria':'Pizzaria','gastronomia':'Alimentação','moda':'Moda','beleza':'Beleza','servicos':'Serviços','pets':'Animais / pet shop','tecnologia':'Tecnologia','fitness':'Academia e fitness','imoveis':'Imóveis','automotivo':'Automotivo','saude':'Saúde','educacao':'Educação','generico':'Produtos em geral'}


def _store():
    from app import OUT
    d=OUT/'fotos_business_27';d.mkdir(parents=True,exist_ok=True)
    return d


def _get(tag):
    if not isinstance(tag,str) or not JOB_ID.fullmatch(tag):raise ValueError('Código de lote inválido.')
    root=_store()/tag
    if not (root/'estado.json').is_file():raise FileNotFoundError('Importação não localizada.')
    return root


def _write(path, obj):
    path=Path(path)
    temp=path.with_name(path.name+'.temp')
    temp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
    temp.replace(path)


def _load(root):return json.loads((root/'estado.json').read_text(encoding='utf-8'))


def _sector(activity):
    s=str(activity).casefold()
    if any(x in s for x in ('bebid','drink','copão','copao','whisky','whiskey','bar ','coquetel')):return 'bebidas'
    if 'hamb' in s or 'burger' in s or 'lanche' in s:return 'hamburgueria'
    if 'pizza' in s:return 'pizzaria'
    if any(x in s for x in ('comida','restaurante','gastron','alimento','doce','bolo','padaria')):return 'gastronomia'
    if any(x in s for x in ('moda','roupa','vestu','calçado','calcado','boutique')):return 'moda'
    if any(x in s for x in ('beleza','cabelo','unha','cosmético','cosmetico','estética')):return 'beleza'
    if any(x in s for x in ('pet','animal','cachorr','gato','veterin','banho e tosa')):return 'pets'
    if any(x in s for x in ('tech','tecnol','celular','computador','eletrôn','eletron','informát')):return 'tecnologia'
    if any(x in s for x in ('academia','fitness','treino','muscula','pilates')):return 'fitness'
    if any(x in s for x in ('imob','imóve','imove','apartamento','corretor')):return 'imoveis'
    if any(x in s for x in ('automot','oficina','mecân','mecan','veículo','veiculo','carros')):return 'automotivo'
    if any(x in s for x in ('odonto','dentist','saúde','saude','clínic','clinic','fisioterapia')):return 'saude'
    if any(x in s for x in ('escola','educa','curso','aula','idioma')):return 'educacao'
    if any(x in s for x in ('serviço','servico','clínica','clinica','odont','imob','reforma')):return 'servicos'
    return 'generico'


def _image(blob):
    from photo_adapt import from_data_url
    # Aceita qualquer proporção e inclusive imagens pequenas. A nitidez passa por revisão humana.
    return from_data_url(blob,max_side=2400)


def _f(size,bold=False):
    paths=('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','C:/Windows/Fonts/arialbd.ttf') if bold else ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','C:/Windows/Fonts/arial.ttf')
    for p in paths:
        try:return ImageFont.truetype(p,size)
        except OSError:continue
    return ImageFont.load_default()


def _preview(root,state):
    # Somente fotos originais: a prévia grátis não imita fotografias tratadas.
    out=Image.new('RGB',(1040,895),'#110e0d');d=ImageDraw.Draw(out)
    d.text((35,24),'STAYVISION  /  FOTOS BUSINESS',font=_f(28,True),fill='#ff9c55')
    d.text((35,68),'CONFERÊNCIA GRATUITA  •  ORIGINAIS SEM EDIÇÃO IA',font=_f(16),fill='#f7e1d3')
    for i in range(6):
        x=35+(i%3)*340;y=112+(i//3)*367
        d.rounded_rectangle((x,y,x+310,y+341),radius=12,fill='#241915')
        if i<state['count']:
            with Image.open(root/'originais'/f'original_{i+1:02d}.jpg') as original:
                thumb=ImageOps.contain(original.convert('RGB'),(290,290),Image.Resampling.LANCZOS)
            out.paste(thumb,(x+(310-thumb.width)//2,y+10+(290-thumb.height)//2))
            d.text((x+15,y+303),f'FOTO {i+1:02d}  •  ORIGINAL',font=_f(16,True),fill='white')
        else:
            d.text((x+28,y+132),'COMPOSICAO IA',font=_f(18,True),fill='#cda18a')
            d.text((x+28,y+162),'SOMENTE APOS AUTORIZAR',font=_f(13),fill='#dfb799')
    out.save(root/'previa_originais.jpg',quality=87,optimize=True)


def _reply(server,payload,code=200):return server._send(json.dumps(payload,ensure_ascii=False),code)


def _read_request(server):
    if not server.headers.get('Content-Type','').lower().startswith('application/json'):
        raise ValueError('Envie JSON.')
    origin=server.headers.get('Origin','')
    if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
        raise ValueError('Origem não permitida.')
    n=int(server.headers.get('Content-Length','0'))
    if not 2<=n<=MAX_POST:raise ValueError('Pedido grande demais.')
    return json.loads(server.rfile.read(n))


def prepare_handler(server):
    """Caminho sem IA, não consulta Gemini nem fal.ai."""
    try:
        data=_read_request(server)
        brand=re.sub(r'\s+',' ',str(data.get('brand') or '')).strip()[:75]
        activity=re.sub(r'\s+',' ',str(data.get('activity') or '')).strip()[:100]
        photos=data.get('images')
        if len(brand)<2:raise ValueError('Informe o nome da empresa.')
        if not isinstance(photos,list) or not 1<=len(photos)<=6:raise ValueError('Envie de 1 a 6 fotos.')
        from photo_quality import diagnose
        loaded=[];sha=[];quality_reports=[]
        for i,photo in enumerate(photos,1):
            if not isinstance(photo,dict):raise ValueError(f'Foto {i} inválida.')
            im=_image(photo.get('data'))
            digest=hashlib.sha256(im.resize((48,48),Image.Resampling.LANCZOS).tobytes()).hexdigest()
            if digest in sha:raise ValueError(f'Foto {i} duplicada. Envie fotos distintas para evitar cobrança repetida.')
            loaded.append(im);sha.append(digest)
            quality_reports.append(diagnose(im))
        tag='pedido-'+secrets.token_hex(8)
        root=_store()/tag
        (root/'originais').mkdir(parents=True)
        for i,im in enumerate(loaded,1):
            im.thumbnail((2200,2200),Image.Resampling.LANCZOS)
            im.save(root/'originais'/f'original_{i:02d}.jpg',quality=93,optimize=True)
        state={'id':tag,'brand':brand,'activity':activity,'sector':_sector(activity),'count':len(loaded),'photo_edits':len(loaded),'creative_compositions':6-len(loaded),'status':'PREPARADO','attempts':0,'done':0,'max_attempts':6,
               'errors':[],'image_log':[],
               'photo_quality_warnings':[f'Foto {i+1}: '+warning for i,report in enumerate(quality_reports) for warning in report['warnings']],
               'photo_quality_reports':quality_reports,
               'created_utc':datetime.now(timezone.utc).isoformat(),
               'human_approval_required':True,'source_images':'user_uploaded','provider_called':False}
        _write(root/'estado.json',state)
        _preview(root,state)
        _reply(server,{'ok':True,**_public(state),'preview':f'/fotos/preview/{tag}',
                       'message':'Prévia montada com ORIGINAIS. Nenhuma edição de IA executada.'})
    except (ValueError,TypeError,KeyError,OverflowError) as ex:_reply(server,{'error':str(ex)},400)
    except Exception as ex:
        print('[fotos] Falha na importação:',type(ex).__name__,str(ex)[:180]);_reply(server,{'error':'Não foi possível importar as fotos. Confira os arquivos.'},500)


def _public(state):
    # Never include secrets, prompts or long provider details in browser.
    return {k:state.get(k) for k in ('id','brand','activity','sector','count','photo_edits','creative_compositions','status','attempts','done','max_attempts','errors','provider_called','photo_quality_warnings','photo_quality_reports')}


def status_handler(server,tag):
    try:
        root=_get(tag);state=_load(root)
        # If the old server exited, a background worker is no longer running.
        # Never resume/retry charged attempts automatically after a restart.
        if state['status'] in ('EM_PRODUCAO','MONTANDO_ENTREGA') and tag not in ACTIVE_BATCHES:
            state['status']='INTERROMPIDO_SEM_REPETICAO'
            state['errors'].append('Processo anterior foi encerrado. Confira o painel fal.ai antes de decidir sobre o lote.')
            _write(root/'estado.json',state)
        out={'ok':True,**_public(state),'preview':f'/fotos/preview/{tag}'}
        if state['status']=='REVISAO_NECESSARIA':
            out.update({'download':f'/download/{tag}.zip','review':f'/revisar?job={tag}'})
        _reply(server,out)
    except (ValueError,FileNotFoundError):_reply(server,{'error':'Lote não encontrado.'},404)




def _creative_prompt(state, index, count):
    """One new composition of *existing* products; no fictional goods, pricing or claims."""
    angles=[
        'Editorial hero arrangement with controlled side lighting, shallow depth of field and refined authentic texture.',
        'High-end close-up product composition with natural condensation, believable shadows, elegant complementary background.',
        'Dynamic premium advertising camera angle that remains physically plausible, uncluttered and photorealistic.',
    ]
    return (
        f'Create a NEW, original premium commercial PRODUCT PHOTOGRAPHY COMPOSITION for {state["brand"]}. '
        f'The business category is {state["activity"] or state["sector"]}. '
        'Use ONLY the actual products shown in the uploaded reference photos. '
        'Carefully preserve their true packaging, number of cups, liquid colors, sizes, fill levels and visible labels. '
        'Do NOT invent new products, ingredients, bottle brands, text, prices, offers, trademarks, or endorsements. '
        'Use a clearly DIFFERENT arrangement, framing and studio background from the reference: '
        + angles[index % len(angles)] + ' '
        'Avoid duplicated or floating products, fake typography and distorted geometry. '
        'Single realistic, attractive premium commercial photo, not a collage or graphic banner. '
        'This is a new AI-created composition based on real reference photos, NOT a faithful photo retouch.'
    )


def _reference_comparison(before, after, target):
    """Purposefully NOT labeled before/after: the right frame is an AI-created scene."""
    canvas=Image.new('RGB',(1160,675),'#f1eee9')
    from PIL import ImageDraw,ImageOps
    for i,im in enumerate((before,after)):
        thumb=ImageOps.contain(im.convert('RGB'),(550,575),Image.Resampling.LANCZOS)
        x=15+i*580+(550-thumb.width)//2
        y=75+(575-thumb.height)//2
        canvas.paste(thumb,(x,y))
    draw=ImageDraw.Draw(canvas)
    draw.text((18,17),'REFERENCIA ORIGINAL',font=_f(25,True),fill='#29221a')
    draw.text((596,17),'NOVA COMPOSICAO POR IA',font=_f(23,True),fill='#29221a')
    canvas.save(target,'JPEG',quality=91,optimize=True)


def _job(root):
    state=_load(root)
    job=state['id']
    from app import OUT,audit_artifacts
    from engine import load_photo,save_jpg,photo_comparison,PLANS
    from image_ai import edit_photo, model
    from photo_quality import diagnose, prepare_reference, inspect_result, save_report
    deliver=OUT/job/'entrega'
    orig=deliver/'00_originais';edited=deliver/'01_fotos_tratadas';qa=deliver/'05_controle_de_qualidade'
    for directory in (orig,edited,qa):directory.mkdir(parents=True,exist_ok=True)
    try:
        n=state['count']
        # Copy only actual uploaded originals; do not fabricate a sixth source.
        for i in range(1,n+1):
            source=root/'originais'/f'original_{i:02d}.jpg'
            (orig/f'original_{i:02d}.jpg').write_bytes(source.read_bytes())
        for i in range(1,7):
            state=_load(root)
            # Reserve exactly one chargeable attempt BEFORE calling fal.ai.
            state['attempts']=i;state['provider_called']=True
            state['current_photo']=i
            _write(root/'estado.json',state)
            target=edited/f'foto_profissional_{i:02d}.jpg'
            if i<=n:
                src=load_photo(orig/f'original_{i:02d}.jpg')
                diagnosis=diagnose(src)
                prepared,pre_report=prepare_reference(src,diagnosis)
                # Guardar original e pré-tratamento separadamente: nada é vendido como restauração mágica.
                prepare_dir=qa/'referencias_preparadas';prepare_dir.mkdir(exist_ok=True)
                save_jpg(prepared,prepare_dir/f'referencia_{i:02d}.jpg')
                observation='Foto original de celular. '+(' '.join(diagnosis['warnings']) or 'Preservar integralmente conteúdo autêntico.')
                processed,meta=edit_photo(prepared,state['brand'],observation,sector=state['sector'])
                save_jpg(processed,target)
                photo_comparison(src,processed,qa/f'antes_depois_{i:02d}.jpg')
                inspection=inspect_result(src,processed)
                save_report(qa/f'qualidade_foto_{i:02d}.json',{'preparation':pre_report,'final_check':inspection})
                meta['quality_review_status']=inspection['status']
                meta['quality_review_flags']=inspection['review_flags']
                meta['deliverable_type']='real_photo_edit'
                meta['source_photo']=f'original_{i:02d}.jpg'
            else:
                from image_ai import generate_visual
                # Ground new scene in up to two of this customer's REAL products.
                # The reference selection is deterministic for auditability.
                src_numbers=sorted({(i-n-1)%n+1, (i-n)%n+1})
                paths=[orig/f'original_{ix:02d}.jpg' for ix in src_numbers]
                prompt=_creative_prompt(state,i-n-1,n)
                processed,meta=generate_visual(prompt,references=paths,size=(1024,1024),quality='high',role='creative_product_composition')
                save_jpg(processed,target)
                with Image.open(paths[0]) as reference:
                    _reference_comparison(reference,processed,qa/f'referencia_composicao_{i:02d}.jpg')
                meta['deliverable_type']='ai_created_composition'
                meta['source_photos']=[p.name for p in paths]
                (qa/f'AVISO_COMPOSICAO_{i:02d}.txt').write_text(
                    'COMPOSICAO CRIATIVA GERADA POR IA, nao e tratamento da fotografia original.\n'
                    'Conferir rigorosamente produto, cores, quantidades e rotulos.\n',encoding='utf-8')
            meta['deliverable_index']=i
            state=_load(root)
            state['done']=i
            state['image_log'].append(meta)
            _write(root/'estado.json',state)
        state['status']='MONTANDO_ENTREGA';_write(root/'estado.json',state)
        (qa/'briefing_criativo.json').write_text(json.dumps({
            'provider':'local','note':'Fotos Business sem consulta Gemini extra',
            'activity':state['activity'],'sector':state['sector'],
            'image_provider':'fal.ai','image_model':model(),
            'deliverables':{'photo_edits':n,'ai_created_compositions':6-n},
            'ai_reference_policy':'Somente referencias fornecidas pelo cliente'},
            ensure_ascii=False,indent=2),encoding='utf-8')
        (qa/'edicao_de_imagens.json').write_text(json.dumps({
            'image_engine':'fal_gpt_image_2_5','images_generated':6,
            'photo_edits':n,'creative_compositions':6-n,'expected_visual_calls':6,
            'billing':'verificar painel fal.ai','details':state['image_log'],
            'approval_status':'REVISAO_NECESSARIA','quality_module':'SV_PHOTO_QUALITY_3_2'},ensure_ascii=False,indent=2),encoding='utf-8')
        (qa/'relatorio.txt').write_text(
            'STAYVISION BUSINESS / FOTOS BUSINESS\n'
            f'{n} foto(s) real(is) editada(s) por IA e {6-n} NOVA(S) COMPOSICAO(OES) IA.\n'
            'Seis pecas visuais no total, usando seis chamadas GPT Image via fal.ai.\n'
            'Comparativos ANTES/DEPOIS somente das fotos reais editadas.\n'
            'Comparativos REFERENCIA/COMPOSICAO nas imagens criativas; nao sao antes/depois.\n'
            'Diagnosticos e preparacao local: ver qualidade_foto_XX.json (sem custo de IA).\n'
            'Fotos gravemente borradas não possuem detalhes suficientes para restauração fiel.\n'
            'Revisao humana OBRIGATORIA: verificar fidelidade de produto, formatos, copos, '
            'cores, gelo, conteudo, embalagens e marcas.\n'
            'Sem PIX, checkout ou publicacao automatica. Nao entregar antes da aprovacao.\n',
            encoding='utf-8')
        (deliver/'LEIA_ANTES_DE_ENTREGAR.txt').write_text(
            f'FOTOS BUSINESS — {n} fotografia(s) real(is) tratada(s) e '
            f'{6-n} composicao(oes) nova(s) criada(s) por IA.\n'
            '6 imagens entregues; comparativos verdadeiros apenas das fotos editadas.\n'
            'Composicoes IA nao representam fotos originais reais.\n'
            'Os resultados precisam de REVISAO HUMANA. Nao publicar produtos alterados.\n',encoding='utf-8')
        info={'plan':'fotos','plan_name':PLANS['fotos']['name'],
              'price_test_brl':PLANS['fotos']['price'],
              'brand':state['brand'],'instagram':'','contact':'','activity':state['activity'],
              'photos_received':n,'photo_edits':n,'creative_compositions':6-n,
              'photo_edit_engine':'generative_image_ai','generative_photo_count':6,
              'generative_design_count':0,'expected_api_calls':6,'image_engine':'fal_gpt_image_2_5',
              'generated_text_source':'local','brand_engine':'not_applicable',
              'sample_only':False,'human_approval_required':True,'brand_conflict':False,
              'creative_quality_flags':[], 'payment_connected':False,'public_upload_enabled':False}
        _write(deliver/'INFO_PEDIDO.json',info)
        issues=audit_artifacts(deliver,'fotos',info)
        if issues:raise RuntimeError('Auditoria incompleta: '+', '.join(issues))
        archive=OUT/(job+'.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
            for p in sorted(deliver.rglob('*')):
                if p.is_file():z.write(p,p.relative_to(deliver))
        state['status']='REVISAO_NECESSARIA';state.pop('current_photo',None)
        _write(root/'estado.json',state)
    except Exception as ex:
        # No retry after interruption/timeout. State and whatever completed remain on disk.
        state=_load(root);state['status']='INTERROMPIDO_SEM_REPETICAO';state['errors'].append(str(ex)[:250]);
        _write(root/'estado.json',state)
        print('[fotos] Geração interrompida, sem retry:',repr(ex))
    finally:
        with BATCH_LOCK:ACTIVE_BATCHES.discard(job)
        WORKER_LOCK.release()


def finish_handler(server):
    try:
        data=_read_request(server)
        tag=str(data.get('id') or '')
        root=_get(tag)
        state=_load(root)
        if data.get('confirm')!='AUTORIZO_SEIS_FOTOS':raise ValueError('Confirmação explícita ausente.')
        if state['status']!='PREPARADO':raise ValueError('Lote já iniciado ou encerrado. Sem repetição automática.')
        if not 3<=state['count']<=6:raise ValueError('Para gerar seis pecas, envie de 3 a 6 fotos diferentes.')
        from image_ai import preflight, enabled
        if not enabled():raise ValueError('Modo gratuito ativo. Reinicie no modo 5 e autorize seis chamadas da fal.ai.')
        preflight(6)
        # Simultaneous starts blocked even when different browsers send same request.
        if not WORKER_LOCK.acquire(blocking=False):raise ValueError('Há outro lote em processamento. Aguarde concluir antes de iniciar outro.')
        try:
            with BATCH_LOCK:
                if tag in ACTIVE_BATCHES:raise ValueError('Lote já iniciado.')
                latest=_load(root)
                if latest['status']!='PREPARADO':raise ValueError('Lote já iniciado.')
                latest['status']='EM_PRODUCAO';_write(root/'estado.json',latest)
                ACTIVE_BATCHES.add(tag)
            threading.Thread(target=_job,args=(root,),daemon=True).start()
        except Exception:
            WORKER_LOCK.release();raise
        _reply(server,{'ok':True,'status':'EM_PRODUCAO','id':tag,'message':'Lote iniciado uma vez. Consulte o progresso; não tente repetir.'},202)
    except FileNotFoundError:_reply(server,{'error':'Importação não encontrada.'},404)
    except (ValueError,RuntimeError,TypeError) as ex:_reply(server,{'error':str(ex)},400)


def preview_handler(server,tag):
    try:
        root=_get(tag)
        server._send((root/'previa_originais.jpg').read_bytes(),mime='image/jpeg')
    except (ValueError,FileNotFoundError):server._send('{"error":"Prévia não encontrada."}',404)
