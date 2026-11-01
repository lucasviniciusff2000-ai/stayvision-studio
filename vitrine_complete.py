"""StayVision: reaproveita Perfil Express real e gera somente 6 posts + 4 stories.

Não consulta Gemini, não recria logo/capas, nem tenta novamente a fal.ai.
Exige referências fotográficas do cliente para evitar invenção de produtos.
Painel INTERNO, somente localhost. A aprovação final continua humana.
"""
from __future__ import annotations
import base64, io, json, re, secrets, shutil, zipfile
from pathlib import Path
from threading import Lock
from PIL import Image, ImageDraw, ImageFont, ImageOps

LOCK = Lock()
HIGHLIGHTS = tuple(f'02_perfil_express/capa_destaque_{i:02d}.png' for i in range(1,6))
PROFILE_FILES = ('02_perfil_express/foto_de_perfil_1080.png', *HIGHLIGHTS,
                 '02_perfil_express/bio_sugerida.txt','02_perfil_express/identidade_visual.txt',
                 '02_perfil_express/previa_perfil.png')
REQUIRED = ('INFO_PEDIDO.json','05_controle_de_qualidade/briefing_criativo.json',*PROFILE_FILES)
LOCKED = 10


def _store():
    from app import OUT
    d=OUT/'vitrine_reuso_perfil';d.mkdir(parents=True,exist_ok=True)
    return d


def _info_path(tag):return _store()/tag/'estado.json'


def _json(p):return json.loads(Path(p).read_text(encoding='utf-8'))


def _save_json(p,obj):
    Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')


def _clean(txt,n=90):return re.sub(r'\s+',' ',str(txt or '')).strip()[:n]


def _read_image(blob,min_size=450):
    from photo_adapt import open_photo
    im=open_photo(blob,max_side=2400)
    # Arquivos finais de entregas anteriores continuam verificados por import_profile.
    if min_size and min(im.size)<min_size:raise ValueError('Arte final do pacote anterior com resolução insuficiente.')
    return im


def import_profile(zip_data):
    if not isinstance(zip_data,str) or not zip_data.startswith('data:application/zip;base64,'):
        raise ValueError('Selecione o ZIP do Perfil Express completo.')
    raw=base64.b64decode(zip_data.split(',',1)[1],validate=True)
    if len(raw)>25_000_000:raise ValueError('ZIP acima de 25 MB.')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=set(z.namelist())
        if not set(REQUIRED).issubset(names):raise ValueError('O ZIP precisa conter o Perfil Express finalizado: logo, 5 capas, bio e prévia.')
        if sum(z.getinfo(k).file_size for k in REQUIRED)>45_000_000:raise ValueError('Conteúdo descompactado excessivo.')
        info=json.loads(z.read('INFO_PEDIDO.json'))
        brief=json.loads(z.read('05_controle_de_qualidade/briefing_criativo.json'))
        if info.get('plan')!='perfil' or info.get('sample_only') or int(info.get('generative_design_count',0))<6:
            raise ValueError('Importe o ZIP do Perfil Express COMPLETO, não a primeira amostra.')
        if not isinstance(brief.get('direction'),dict) or brief.get('provider')!='gemini':
            raise ValueError('Briefing Gemini ausente no Perfil Express.')
        b=brief['direction']
        if b.get('quality_flags') or b.get('brand_mismatch_review'):
            raise ValueError('O briefing possui alertas pendentes, não gere peças novas.')
        if _clean(info.get('brand'),45)=='':raise ValueError('Marca não identificada.')
        optional=('02_perfil_express/bios_3_opcoes.txt',
                  '02_perfil_express/logo_horizontal_escuro_1600x600.png',
                  '02_perfil_express/logo_horizontal_claro_1600x600.png')
        blobs={k:z.read(k) for k in PROFILE_FILES}
        blobs.update({k:z.read(k) for k in optional if k in names})
    for k,v in blobs.items():
        if k.endswith('.png'):_read_image(v,min_size=300)
        elif len(v)>30_000:raise ValueError('Texto de perfil grande demais.')
    return info,brief,blobs


def _refs_from_payload(images,folder):
    if not isinstance(images,list) or not 1<=len(images)<=6:
        raise ValueError('Envie de 1 a 6 fotos REAIS de produtos da marca.')
    from photo_adapt import from_data_url, to_jpeg
    refs=[]
    for i,picture in enumerate(images,1):
        if not isinstance(picture,dict):raise ValueError(f'Foto {i} inválida.')
        im=from_data_url(picture.get('data'),max_side=1600)
        path=folder/f'produto_{i:02d}.jpg'
        to_jpeg(im,path,quality=94)
        refs.append(path)
    return refs


def _concepts(brief, info=None):
    """Use individualized briefing captions, not generic placeholder sentences."""
    from marketing_upgrade import campaign
    info=info or {'brand':'a marca','activity':brief.get('activity','')}
    return [{'title':x['title'],'theme':x['role'].lower(),'caption':x['caption']}
            for x in campaign(info,brief)]


def _font(size,bold=False):
    options=(['C:/Windows/Fonts/segoeuib.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if bold else
             ['C:/Windows/Fonts/segoeui.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])
    return ImageFont.truetype(next((s for s in options if Path(s).exists()),options[-1]),size)


def _crop(im,rect):return ImageOps.fit(im.convert('RGB'),(rect[2]-rect[0],rect[3]-rect[1]),Image.Resampling.LANCZOS)


def editorial_finish(path,kind,title,brand,accent,logo):
    """Tipografia de precisão sobre arte gerada, sem deformações de texto pelo modelo.
    Mantém o resultado do GPT Image como elemento principal. Evita ofertas inventadas.
    """
    target=Path(path)
    with Image.open(target) as source:img=source.convert('RGBA')
    w,h=img.size
    accent=accent if re.fullmatch(r'#[A-Fa-f0-9]{6}',str(accent)) else '#FF6E16'
    # Vinheta inferior gradual para a legibilidade de textos reais.
    mask=Image.new('L',(1,h),0);mp=mask.load()
    start=int(h*.57)
    for y in range(start,h):
        t=(y-start)/max(1,h-start)
        mp[0,y]=int(195*t*t)
    mask=mask.resize((w,h))
    shadow=Image.new('RGBA',(w,h),(0,0,0,0))
    shadow.paste((4,4,7,255),(0,0,w,h),mask)
    img=Image.alpha_composite(img,shadow)
    d=ImageDraw.Draw(img)
    px=int(w*.065);small=28 if kind=='feed' else 36
    d.rounded_rectangle((px,int(h*.79),px+int(w*.34),int(h*.795)+6),radius=3,fill=accent)
    branding=_clean(brand,38).upper()
    d.text((px,int(h*.81)),branding,font=_font(small,True),fill='#FFFFFF',stroke_width=1,stroke_fill='#121212')
    # Encaixar o titulo em duas linhas no máximo sem cortar as palavras.
    words=_clean(title,70).upper().split();lines=['']
    fsize=69 if kind=='feed' else 88
    maxw=int(w*.86)
    f=_font(fsize,True)
    for word in words:
        cand=(lines[-1]+' '+word).strip()
        if d.textbbox((0,0),cand,font=f)[2]>maxw and lines[-1] and len(lines)<2:lines.append(word)
        else:lines[-1]=cand
    while max(d.textbbox((0,0),ln,font=f)[2] for ln in lines)>maxw and fsize>38:
        fsize-=2;f=_font(fsize,True)
    title_y=int(h*.845)
    for ln in lines:
        d.text((px,title_y),ln,font=f,fill='#FFFFFF',stroke_width=2,stroke_fill='#160C09')
        title_y+=int(fsize*1.16)
    # A foto de perfil original é reaproveitada, sem criar um novo símbolo.
    lc=int(w*.13)
    icon=ImageOps.fit(logo.convert('RGBA'),(lc,lc),Image.Resampling.LANCZOS)
    mask2=Image.new('L',(lc,lc),0);ImageDraw.Draw(mask2).ellipse((1,1,lc-2,lc-2),fill=255)
    img.paste(icon,(w-lc-px,px),mask2)
    d=ImageDraw.Draw(img)
    d.ellipse((w-lc-px-2,px-2,w-px+2,px+lc+2),outline=accent,width=4)
    img.convert('RGB').save(target,'JPEG',quality=94,subsampling=0)


def create_feed_preview(path,info,brief,root):
    """Resumo com artes efetivamente geradas, sem seguidores inventados."""
    w,h=1180,1950
    canvas=Image.new('RGB',(w,h),'#0B0A0A');d=ImageDraw.Draw(canvas)
    accent=brief.get('accent','#F97316')
    if not re.fullmatch(r'#[A-Fa-f0-9]{6}',str(accent)):accent='#F97316'
    d.rectangle((0,0,w,110),fill='#18100D')
    d.text((40,34),'STAYVISION  /  VITRINE DIGITAL',fill='#F7F3F0',font=_font(32,True))
    d.text((40,135),_clean(info.get('brand'),45),fill='#FFFFFF',font=_font(42,True))
    d.text((42,193),_clean(info.get('instagram'),40),fill=accent,font=_font(27,True))
    bio=(root/'02_perfil_express/bio_sugerida.txt').read_text(encoding='utf-8').splitlines()
    from bio_engine import preview_plain
    for j,line in enumerate(bio[:4]):
        d.text((45,240+40*j),preview_plain(line)[:80],fill='#DBD0C6',font=_font(19))
    logo=Image.open(root/'02_perfil_express/foto_de_perfil_1080.png')
    mask=Image.new('L',(175,175));ImageDraw.Draw(mask).ellipse((2,2,173,173),fill=255)
    canvas.paste(_crop(logo,(0,0,175,175)),(954,144),mask)
    d.ellipse((950,140,1132,322),outline=accent,width=4)
    d.line((40,417,1140,417),fill='#58311D',width=3)
    d.text((42,442),'6 PUBLICAÇÕES DO FEED',fill=accent,font=_font(26,True))
    x0,gap=40,11;ww=(1100-2*gap)//3;hh=int(ww*1.25)
    for i in range(6):
        p=root/f'03_vitrine_digital/feed_{i+1:02d}_1080x1350.jpg'
        img=Image.open(p)
        x=x0+(i%3)*(ww+gap);y=500+(i//3)*(hh+gap)
        canvas.paste(_crop(img,(x,y,x+ww,y+hh)),(x,y))
    y=500+2*(hh+gap)+12
    d.text((40,y),'4 STORIES  ·  PREVIEW',fill=accent,font=_font(23,True))
    sy=y+45;tw=190;th=338
    for i in range(4):
        p=root/f'03_vitrine_digital/story_{i+1:02d}_1080x1920.jpg'
        pic=Image.open(p);x=40+i*235
        canvas.paste(_crop(pic,(x,sy,x+tw,sy+th)),(x,sy))
    d.text((40,h-64),'Conceito para revisão • sem métricas, vendas ou depoimentos fictícios.',fill='#BBAE9F',font=_font(19))
    canvas.save(path)


def prepare_handler(h):
    from fase2_api import _payload
    try:
        o=_payload(h,max_n=77_000_000)
        info,meta,files=import_profile(o.get('zip_data'))
        tag=secrets.token_hex(10)
        folder=_store()/tag;folder.mkdir()
        (folder/'perfil').mkdir();(folder/'produtos').mkdir()
        for name,raw in files.items():
            (folder/'perfil'/Path(name).name).write_bytes(raw)
        _save_json(folder/'info.json',info)
        _save_json(folder/'brief.json',meta)
        references=_refs_from_payload(o.get('images'),folder/'produtos')
        state={'status':'PRONTO','brand':info['brand'],'attempted':[],'completed':[],'photos':len(references)}
        _save_json(_info_path(tag),state)
        data={'ok':True,'id':tag,'brand':info['brand'],'instagram':info.get('instagram',''),
              'references':len(references),'planned_feed':6,'planned_stories':4,'new_calls':LOCKED,
              'themes':_concepts(meta['direction']), 'sector':meta['direction'].get('segment',''),
              'message':'Perfil e fotos importados. Nenhuma chamada ao Gemini ou fal.ai.'}
        h._send(json.dumps(data,ensure_ascii=False))
    except (ValueError,TypeError,KeyError,zipfile.BadZipFile,OverflowError,base64.binascii.Error) as ex:
        h._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
    except Exception as ex:
        print('VITRINE IMPORT',type(ex).__name__,str(ex)[:100])
        h._send(json.dumps({'error':'Erro na preparação, nenhum crédito foi consumido.'}),500)


def finish_handler(h):
    from fase2_api import _payload
    try:
        o=_payload(h,max_n=8000)
        tag=str(o.get('id',''))
        if not re.fullmatch(r'[a-f0-9]{20}',tag):raise ValueError('Importação inválida.')
        if o.get('confirm')!='AUTORIZO_DEZ_ARTES':raise ValueError('Confirme o limite de dez tentativas.')
        folder=(_store()/tag).resolve()
        if not folder.is_relative_to(_store().resolve()) or not (folder/'estado.json').exists():
            raise ValueError('Importação não encontrada.')
        from image_ai import enabled,preflight
        if not enabled():raise ValueError('fal.ai está desligada. Inicie no modo 4.')
        with LOCK:
            state=_json(folder/'estado.json')
            if state.get('status')!='PRONTO':raise ValueError('Este lote já foi utilizado ou iniciado. Não repetir automaticamente.')
            preflight(LOCKED)
            state['status']='EM_PRODUCAO'
            _save_json(folder/'estado.json',state)
        result=finish_vitrine(folder,state)
        h._send(json.dumps({'ok':True,**result},ensure_ascii=False))
    except (ValueError,TypeError,KeyError) as ex:h._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
    except RuntimeError as ex:h._send(json.dumps({'error':str(ex)+' Consulte o histórico fal.ai antes de repetir.'},ensure_ascii=False),503)
    except Exception as ex:
        print('VITRINE FAILURE',type(ex).__name__,str(ex)[:150])
        h._send(json.dumps({'error':'Falha. Confira o histórico fal.ai e o lote parcial; NÃO gere novamente automaticamente.'}),500)


def finish_vitrine(folder,state,*,test_generator=None):
    from app import OUT,audit_artifacts
    from design_ai import save_visual,direction
    from image_ai import generate_visual
    import secrets
    gen=test_generator or generate_visual
    info=_json(folder/'info.json')
    meta=_json(folder/'brief.json');brief=meta['direction']
    refs=sorted((folder/'produtos').glob('produto_*.jpg'))
    if not refs:raise RuntimeError('Nenhuma foto de produto enviada.')
    job='pedido-'+secrets.token_hex(8)
    state['job']=job;_save_json(folder/'estado.json',state)
    root=OUT/job/'entrega';(root/'02_perfil_express').mkdir(parents=True,exist_ok=True)
    for f in (*PROFILE_FILES, *('02_perfil_express/bios_3_opcoes.txt',
              '02_perfil_express/logo_horizontal_escuro_1600x600.png',
              '02_perfil_express/logo_horizontal_claro_1600x600.png')):
        if not (folder/'perfil'/Path(f).name).exists():continue
        shutil.copy2(folder/'perfil'/Path(f).name,root/f)
    # Atualiza BIO do pacote reutilizado sem nenhuma API ou nova geração de imagem.
    from bio_engine import generate_bio, suggested_name
    (root/'02_perfil_express/bio_sugerida.txt').write_text(generate_bio(info,brief),encoding='utf-8')
    from bio_engine import generate_bio_options
    (root/'02_perfil_express/bios_3_opcoes.txt').write_text(generate_bio_options(info,brief),encoding='utf-8')
    (root/'02_perfil_express/nome_perfil_sugerido.txt').write_text(suggested_name(info,brief),encoding='utf-8')
    from bio_engine import write_html_preview
    write_html_preview(root,info,brief)
    from profile_complete import professional_preview
    with Image.open(root/'02_perfil_express/foto_de_perfil_1080.png') as photo:
        covers=[Image.open(root/f'02_perfil_express/capa_destaque_{i:02d}.png').convert('RGB') for i in range(1,6)]
        labels=list(brief.get('highlights') or [])[:5]
        labels=(labels+['Produtos','Novidades','Pedidos','Sobre','Contato'])[:5]
        professional_preview(root/'02_perfil_express/previa_perfil.png',info['brand'],info.get('instagram',''),info.get('activity',''),info.get('contact',''),brief,photo,covers,labels)

    src=root/'00_originais';src.mkdir()
    for i,p in enumerate(refs,1):shutil.copy2(p,src/f'original_{i:02d}.jpg')
    logo=Image.open(root/'02_perfil_express/foto_de_perfil_1080.png').convert('RGB')
    assets=root/'03_vitrine_digital';assets.mkdir()
    logs=[];themes=_concepts(brief,info)
    from marketing_upgrade import stories as _story_plan
    story_plan=_story_plan(info,brief)
    try:
        for kind,num in [('feed',6),('story',4)]:
            for i in range(num):
                role=f'{kind}_{i+1}'
                state['attempted'].append(role)
                _save_json(folder/'estado.json',state)
                theme=(themes[i] if kind=='feed' else {'title':story_plan[i]['title'], 'theme':story_plan[i]['role'].lower()});ref=refs[(i if kind=='feed' else i+2)%len(refs)]
                layout='4:5 portrait grid-post' if kind=='feed' else '9:16 vertical story'
                # Render artístico original com a foto real, mas sem preço inventado ou textos distorcidos.
                p=(f'Create a unique premium {layout} brand campaign for this REAL business. '
                   f'Brand: {_clean(info.get("brand"),45)}. Business: {_clean(info.get("activity"),90)}. '
                   f'This is creative piece {role}, theme "{_clean(theme["title"],65)}" ({theme["theme"]}). '
                    'Reference 1 is the REAL client photograph. Respect the exact actual subject, whether ' 
                   'product, environment, service equipment or other business evidence. Keep real ' 
                   'colors, recognizable shapes, item counts, visible brand marks and factual details. ' 
                   'Never turn one niche into another or invent products, services, ingredients, ' 
                   'people, signage or branded packaging. ' 
                   'Reference 2 is the APPROVED brand icon: match its real colors and visual atmosphere, but do not '
                   'reproduce a giant avatar circle or a screenshot. Make this piece DISTINCT from other posts. '
                   'Use sophisticated studio photography, dimensional lighting, clear visual hierarchy, clever '
                   'editorial composition, suitable negative space. No readable typography, written words, numbers, '
                   'price tags, fake offers, discounts, ratings, claims or watermarks. '
                   'Deliver a finished visually striking image without any text overlay. '+direction(info['brand'],brief))
                img,log=gen(p,references=[ref,logo],size=(1088,1360) if kind=='feed' else (1088,1920),quality='high',role=role)
                out=assets/(f'feed_{i+1:02d}_1080x1350.jpg' if kind=='feed' else f'story_{i+1:02d}_1080x1920.jpg')
                save_visual(img,out,kind);editorial_finish(out,kind,theme['title'],info['brand'],brief.get('accent','#FF6E16'),logo);logs.append(log)
                state['completed'].append(role);_save_json(folder/'estado.json',state)
        from marketing_upgrade import write_editorial_files, brand_lockup
        write_editorial_files(root,info,brief)
        brand_lockup(root,info,brief,root/'02_perfil_express/foto_de_perfil_1080.png')
        create_feed_preview(assets/'previa_vitrine.png',info,brief,root)
        qc=root/'05_controle_de_qualidade';qc.mkdir(exist_ok=True)
        _save_json(qc/'briefing_criativo.json',meta)
        _save_json(qc/'edicao_de_imagens.json',{'source_profile_reused':True,'gemini_calls_this_run':0,
             'new_visual_attempts':len(state['attempted']),'new_visual_completed':len(state['completed']),
             'image_engine':'fal_gpt_image_2_5','human_approval_required':True,'details':logs})
        (qc/'relatorio.txt').write_text('STAYVISION — VITRINE DIGITAL\n6 arquivos de feed, 4 stories. Logo + 5 capas REAPROVEITADOS sem cobrança novamente.\n'
                  'Artes são composições comerciais com fotos de referência; revisar fidelidade, textos, descontos não prometidos e direitos.\n'
                  'NÃO houve nova consulta Gemini nesta etapa; pagamento desligado. Revisão humana obrigatória.\n',encoding='utf-8')
        info=dict(info)
        info.update({'plan':'vitrine','plan_name':'Vitrine Digital','sample_only':False,
             'photos_received':len(refs),'generative_design_count':16,'source_profile_reused':True,
             'expected_api_calls':10,'calls_this_run':10,'marketing_upgrade_version':'3.0','payment_connected':False,'photo_edit_engine':'not_applicable', 'price_test_brl':249.90})
        _save_json(root/'INFO_PEDIDO.json',info)
        problems=audit_artifacts(root,'vitrine',info)
        if problems:raise RuntimeError('Auditoria do pacote incompleta: '+'; '.join(problems))
        archive=OUT/(job+'.zip')
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for p in root.rglob('*'):
                if p.is_file():z.write(p,p.relative_to(root))
        state['status']='CONCLUIDO_PARA_REVISAO';_save_json(folder/'estado.json',state)
        return {'job':job,'download':'/download/'+job+'.zip','review':'/revisar?job='+job,
                'images_generated_now':10,'profile_reused':True,'gemini_calls_now':0}
    except Exception:
        state['status']='FALHA_VERIFICAR_COBRANCAS';_save_json(folder/'estado.json',state)
        raise


def last_import_handler(h):
    """Recupera a importação do Perfil Express após reiniciar do modo grátis para modo pago."""
    try:
        folders=sorted((f for f in _store().iterdir() if f.is_dir() and re.fullmatch(r'[a-f0-9]{20}',f.name) and (f/'estado.json').is_file()),
                       key=lambda f:f.stat().st_mtime,reverse=True)
        if not folders:raise ValueError('Nenhuma Vitrine preparada. Importe primeiro o ZIP e as fotos.')
        folder=folders[0];state=_json(folder/'estado.json')
        if state.get('status')!='PRONTO':
            raise ValueError('Última importação já iniciou ou concluiu um lote. Não é permitido gerar novamente automaticamente.')
        info=_json(folder/'info.json');meta=_json(folder/'brief.json')
        h._send(json.dumps({'ok':True,'id':folder.name,'brand':info['brand'],'instagram':info.get('instagram',''),
             'references':state['photos'],'sector':meta['direction'].get('segment',''),
             'themes':_concepts(meta['direction']),'new_calls':10,'planned_feed':6,'planned_stories':4,
             'message':'Importação recuperada sem consulta ao Gemini ou fal.ai.'},ensure_ascii=False))
    except (ValueError,KeyError,TypeError) as ex:
        h._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
