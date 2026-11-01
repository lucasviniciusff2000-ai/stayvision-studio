"""Finalizar Perfil Express a partir de uma AMOSTRA REAL já paga.
Importa apenas os 3 arquivos específicos do ZIP, sem extrair caminhos arbitrários.
Gera 5 capas GPT Image e uma apresentação editorial original usando seus arquivos.
Não chama Gemini outra vez; reserva tentativas pagas antes de dispará-las.
"""
from __future__ import annotations
import base64, io, json, os, re, secrets, zipfile
from pathlib import Path
from threading import Lock
from PIL import Image,ImageDraw,ImageFont,ImageOps

LOCK=Lock()
NEEDED=('INFO_PEDIDO.json','05_controle_de_qualidade/briefing_criativo.json','02_perfil_express/foto_de_perfil_1080.png')
LABELS_DEFAULT=['Produtos','Novidades','Pedidos','Sobre','Contato']

def safe_text(x,n=100):
    return re.sub(r'[\r\n\t ]+',' ',str(x or '')).strip()[:n]

def _font(n,bold=False):
    names=([r'C:\Windows\Fonts\segoeuib.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if bold else [r'C:\Windows\Fonts\segoeui.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])
    return ImageFont.truetype(next((f for f in names if Path(f).is_file()),'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),n)

def _center_crop(img,size):
    from photo_adapt import smart_fit
    return smart_fit(img,size,mode='logo')

def _circle(base,source,x,y,diam,accent):
    mk=Image.new('L',(diam,diam),0);dd=ImageDraw.Draw(mk);dd.ellipse((2,2,diam-3,diam-3),fill=255)
    base.paste(_center_crop(source,(diam,diam)),(x,y),mk)
    ImageDraw.Draw(base).ellipse((x-4,y-4,x+diam+4,y+diam+4),outline=accent,width=4)

def _fit_text(d,txt,x,y,maxw,font_size,fill,bold=False):
    text=safe_text(txt,160)
    while font_size>=13:
        ff=_font(font_size,bold)
        if d.textbbox((0,0),text,font=ff)[2]<=maxw:break
        font_size-=1
    d.text((x,y),text,font=ff,fill=fill)

def write_bio(info,brief):
    from bio_engine import generate_bio
    return generate_bio(info,brief)


def professional_preview(dst,brand,instagram,activity,contact,direction,logo,covers,labels):
    """Prévia HONESTA: 1 logo+5 capas. Não fabrica fotos de feed nem seguidores."""
    W,H=1300,900
    im=Image.new('RGB',(W,H),'#09090B');d=ImageDraw.Draw(im)
    accent=str(direction.get('accent','#FF6E16')).upper()
    if not re.fullmatch('#[0-9A-F]{6}',accent):accent='#FF6E16'
    d.rounded_rectangle((19,19,1281,880),radius=28,fill='#121215',outline='#783A19',width=3)
    d.rounded_rectangle((19,19,1281,102),radius=24,fill='#21130F')
    d.rectangle((19,76,1281,102),fill='#21130F')
    d.text((58,42),'STAYVISION  ·  PERFIL EXPRESS',font=_font(26,True),fill='#FFFFFF')
    d.text((970,49),'PRÉVIA  ·  REVISÃO',font=_font(16,True),fill='#F8AD7B')
    _circle(im,logo,69,159,195,accent)
    _fit_text(d,instagram,298,156,900,39,'#FFFFFF',True)
    _fit_text(d,brand+'  |  '+safe_text(activity,60),300,215,880,21,'#EAE5E0',True)
    # Texto igual ao arquivo final; remove apenas emojis no PNG caso fonte não tenha glifos.
    from bio_engine import preview_plain
    lines=write_bio({'brand':brand,'activity':activity,'contact':contact,'instagram':instagram},direction).splitlines()
    for j,line in enumerate(lines[:4]):
        _fit_text(d,preview_plain(line),300,249+j*37,920,22,'#F3D8C1' if j==0 else '#D5CFCA',j==0)
    d.line((60,408,1240,408),fill='#553222',width=2)
    d.text((65,427),'DESTAQUES DA MARCA',font=_font(23,True),fill='#FFFFFF')
    for i,(cover,label) in enumerate(zip(covers,labels)):
        x=86+i*242
        _circle(im,cover,x,494,154,accent)
        _fit_text(d,label,x-13,666,187,21,'#EFE7E1',True)
    d.line((60,723,1240,723),fill='#553222',width=2)
    d.text((65,746),'IDENTIDADE COERENTE  ·  5 CAPAS ORIGINAIS  ·  BIO PARA INSTAGRAM',font=_font(23,True),fill='#FFB572')
    d.text((65,801),'Conceito para aprovação. Não é um perfil publicado, não representa seguidores ou avaliações.',font=_font(17),fill='#BAB0A7')
    im.save(dst,format='PNG',optimize=True)

def parse_sample(content):
    if not isinstance(content,str) or not content.startswith('data:application/zip;base64,'):
        raise ValueError('Envie o ZIP da amostra já gerada pelo aplicativo.')
    raw=base64.b64decode(content.split(',',1)[1],validate=True)
    if len(raw)>15_000_000:raise ValueError('ZIP acima de 15 MB.')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if not all(k in z.namelist() for k in NEEDED):raise ValueError('ZIP sem as informações ou a imagem da amostra.')
        if any(z.getinfo(n).file_size>6_000_000 for n in NEEDED):raise ValueError('Arquivo do pacote acima do limite.')
        info=json.loads(z.read(NEEDED[0]));brief=json.loads(z.read(NEEDED[1]));photo=z.read(NEEDED[2])
    if info.get('plan')!='perfil' or not info.get('sample_only') or info.get('brand_engine')!='gpt_image_2_5_fal_ai':
        raise ValueError('Use um ZIP de amostra real do Perfil Express produzido com GPT Image.')
    if brief.get('provider')!='gemini' or not isinstance(brief.get('direction'),dict):
        raise ValueError('O pacote não possui briefing Gemini válido.')
    flags=brief['direction'].get('quality_flags') or []
    if flags or brief['direction'].get('brand_mismatch_review'):
        raise ValueError('O briefing da amostra tem alertas pendentes: corrigir antes das cinco capas.')
    with Image.open(io.BytesIO(photo)) as pi:
        pi.verify()
    with Image.open(io.BytesIO(photo)) as pi:
        im=pi.convert('RGB')
    if min(im.size)<600:raise ValueError('Logo da amostra sem resolução suficiente.')
    return info,brief,im

def _store_dir():
    from app import OUT
    folder=OUT/'perfil_finalizacoes';folder.mkdir(exist_ok=True)
    return folder

def _state_path(tag):return _store_dir()/tag/'estado.json'

def prepare_sample_handler(h):
    """Importa ZIP anterior, não consulta Gemini ou fal.ai."""
    from fase2_api import _payload
    try:
        o=_payload(h,max_n=21_000_000)
        info,brief,logo=parse_sample(o.get('zip_data'))
        tag=secrets.token_hex(10)
        path=_store_dir()/tag;path.mkdir()
        logo.save(path/'logo_aprovado.png')
        (path/'briefing.json').write_text(json.dumps(brief,ensure_ascii=False),encoding='utf-8')
        (path/'info.json').write_text(json.dumps(info,ensure_ascii=False),encoding='utf-8')
        labels=list(brief['direction'].get('highlights') or LABELS_DEFAULT)[:5]
        labels=(labels+LABELS_DEFAULT)[:5]
        state={'status':'PRONTO','attempted':[],'completed':[],'brand':info['brand']}
        _state_path(tag).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
        from image_ai import enabled,remaining
        h._send(json.dumps({'ok':True,'id':tag,'brand':info['brand'],'instagram':info.get('instagram',''),
            'segment':brief['direction'].get('segment',''),'highlights':labels,'remaining':remaining(),'image_ai_enabled':enabled(),
            'message':'Amostra aprovada importada. 0 créditos consumidos na importação.'},ensure_ascii=False))
    except (ValueError,KeyError,TypeError,zipfile.BadZipFile,OverflowError) as ex:
        h._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
    except Exception as ex:
        print('PERFIL IMPORT ERRO:',type(ex).__name__)
        h._send(json.dumps({'error':'Não foi possível importar o ZIP. Nenhuma chamada paga foi iniciada.'}),500)

def finish_handler(h):
    from fase2_api import _payload
    try:
        o=_payload(h,max_n=8000)
        tag=str(o.get('id',''))
        if not re.fullmatch(r'[a-f0-9]{20}',tag):raise ValueError('Identificador inválido.')
        if o.get('confirm')!='AUTORIZO_CINCO_CAPAS':raise ValueError('Confirmação de cinco chamadas ausente.')
        folder=(_store_dir()/tag).resolve()
        if not folder.is_relative_to(_store_dir().resolve()) or not (folder/'estado.json').exists():
            raise ValueError('Amostra importada não encontrada.')
        from image_ai import enabled,remaining,preflight
        if not enabled():raise ValueError('Fal.ai desligada. Inicie no modo de 5 chamadas autorizadas.')
        # Reserve a operação ANTES da primeira chamada e nunca permita repetição automática.
        with LOCK:
            state=json.loads((folder/'estado.json').read_text())
            if state['status']!='PRONTO':raise ValueError('Esta importação já foi utilizada. Não repetir chamadas; confira resultados.')
            preflight(5)
            state['status']='EM_PRODUCAO'
            (folder/'estado.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
        result=finish_profile(folder,state)
        h._send(json.dumps({'ok':True,**result},ensure_ascii=False))
    except (ValueError,KeyError,TypeError) as ex:
        h._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
    except RuntimeError as ex:
        h._send(json.dumps({'error':str(ex)+' Confira o painel da fal.ai; não repita o pedido automaticamente.'},ensure_ascii=False),503)
    except Exception as ex:
        print('PERFIL COMPLETE ERROR',type(ex).__name__)
        h._send(json.dumps({'error':'Falha na conclusão. Uma chamada pode ter sido cobrada; verifique o painel e os arquivos antes de repetir.'}),500)

def finish_profile(folder,state):
    """Produz exatamente as cinco capas sem regenerar o logo. Sob teste, gere mock só via patch externo."""
    from design_ai import generate_visual,save_visual,direction
    # A função de prévia do pacote é específica desta etapa, não a prévia branca antiga.
    from app import OUT
    from image_ai import remaining
    info=json.loads((folder/'info.json').read_text(encoding='utf-8'))
    meta=json.loads((folder/'briefing.json').read_text(encoding='utf-8'))
    brief=meta['direction']
    labels=list(brief.get('highlights') or LABELS_DEFAULT)[:5]
    labels=(labels+LABELS_DEFAULT)[:5]
    job='pedido-'+secrets.token_hex(8)
    state['job']=job
    _state_path(folder.name).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    root=OUT/job/'entrega';base=root/'02_perfil_express';base.mkdir(parents=True,exist_ok=True)
    from PIL import Image
    logo=Image.open(folder/'logo_aprovado.png').convert('RGB')
    save_visual(logo,base/'foto_de_perfil_1080.png','profile')
    logs=[{'role':'profile_logo','reused':True,'source':'amostra_anterior','charged_new_call':False}]
    image_refs=[logo]
    try:
        for i,label in enumerate(labels):
            # Reserva individual ANTES da chamada; caso falhe não aciona novamente por acidente.
            state['attempted'].append(i+1)
            _state_path(folder.name).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
            concepts=brief.get('highlight_concepts') or []
            concept=safe_text(concepts[i] if i<len(concepts) else label,120)
            prompt=('Premium original Instagram highlight cover in the same approved brand identity as the reference logo. '
                'The supplied image is the approved client visual identity, not a screenshot to imitate. '
                'Preserve the brand palette, energy, illustration materials, and polish. '
                'Make ONE large distinctive, realistic icon illustration for category '+safe_text(label,24)+'. '
                'Concept '+concept+'. This cover must be visibly DIFFERENT from the other categories and clearly readable at small size. '
                'Centered circular crop-safe icon, professional light and crisp texture; NO lettering, text, watermark, stock icons, '
                'price tags, external logos or social media UI. '+direction(info['brand'],brief))
            img,log=generate_visual(prompt,references=image_refs,size=(1024,1024),quality='high',role=f'cover_{i+1}')
            save_visual(img,base/f'capa_destaque_{i+1:02d}.png','cover')
            logs.append(log)
            state['completed'].append(i+1)
            _state_path(folder.name).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
        caps=[Image.open(base/f'capa_destaque_{i+1:02d}.png').convert('RGB') for i in range(5)]
        professional_preview(base/'previa_perfil.png',info['brand'],info.get('instagram',''),info.get('activity',''),info.get('contact',''),brief,logo,caps,labels)
        bio=write_bio(info,brief)
        (base/'bio_sugerida.txt').write_text(bio,encoding='utf-8')
        from bio_engine import generate_bio_options
        (base/'bios_3_opcoes.txt').write_text(generate_bio_options(info,brief),encoding='utf-8')
        from marketing_upgrade import brand_lockup
        brand_lockup(root,info,brief,base/'foto_de_perfil_1080.png')
        from bio_engine import suggested_name
        (base/'nome_perfil_sugerido.txt').write_text(suggested_name(info,brief),encoding='utf-8')
        from bio_engine import write_html_preview
        write_html_preview(root,info,brief)
        (base/'identidade_visual.txt').write_text('Marca existente preservada: símbolo reaproveitado da amostra aprovada.\nDireção: '+safe_text(brief.get('visual_style'),250)+'\nCores: '+safe_text(brief.get('accent'))+' / '+safe_text(brief.get('color_support'))+'\nVerificar legibilidade, logo e uso comercial antes de publicar.\n',encoding='utf-8')
        qa=root/'05_controle_de_qualidade';qa.mkdir(exist_ok=True)
        (qa/'briefing_criativo.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
        (qa/'edicao_de_imagens.json').write_text(json.dumps({'image_engine':'fal_gpt_image_2_5','images_generated_in_this_run':5,'reused_profile_logo':True,'details':logs,'human_approval_required':True},ensure_ascii=False,indent=2),encoding='utf-8')
        (qa/'relatorio.txt').write_text('PERFIL EXPRESS — ENTREGA COMPLETA PARA REVISÃO\nLogotipo anterior reaproveitado, 5 capas geradas via fal.ai.\nBio e prévia visual incluídas. Nenhum feed, story ou postagem incluída neste plano.\nRevisão humana obrigatória; pagamento desligado.\n',encoding='utf-8')
        info=dict(info);info.update({'plan':'perfil','plan_name':'Perfil Express','sample_only':False,'photos_received':0,'generative_design_count':6,'brand_engine':'gpt_image_2_5_fal_ai','photo_edit_engine':'not_applicable','generative_photo_count':0,'source_sample_reused':True,'expected_api_calls':5,'payment_connected':False,'marketing_upgrade_version':'3.0','creative_quality_flags':brief.get('quality_flags',[]),'brand_conflict':bool(brief.get('brand_mismatch_review'))})
        (root/'INFO_PEDIDO.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        from app import audit_artifacts
        issues=audit_artifacts(root,'perfil',info)
        if issues:raise RuntimeError('Auditoria encontrou problemas: '+'; '.join(issues))
        import zipfile
        dst=OUT/(job+'.zip')
        with zipfile.ZipFile(dst,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for p in root.rglob('*'):
                if p.is_file():z.write(p,p.relative_to(root))
        state['status']='COMPLETO_PENDENTE_REVISAO'
        _state_path(folder.name).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
        return {'job':job,'download':'/download/'+job+'.zip','review':'/revisar?job='+job,'covers':5,'image_calls_this_run':5}
    except Exception:
        state['status']='FALHA_CONFERIR_HISTORICO'
        _state_path(folder.name).write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
        raise
