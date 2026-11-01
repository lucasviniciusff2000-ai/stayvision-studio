"""StayVision Business 3.0 — pós-produção editorial e identidade, sem APIs pagas.

Não comprova fatos comerciais: usa somente ramo declarado e textos previamente
revisados pelo Gemini. Arquivos finais exigem revisão humana.
"""
from __future__ import annotations
import json, re, unicodedata
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROLES = ('APRESENTAÇÃO', 'O QUE OFERECEMOS', 'DETALHES', 'IDENTIDADE', 'INSPIRAÇÃO', 'CONTATO')
RISKY = re.compile(r'(?i)\b(?:gr[aá]tis|24\s*h|garantid[ao]s?|promoc[aã]o|desconto|agilidade|r[aá]pid[ao]s?|rapidez|garantir\s+a\s+sua\s+bebida|frete\s*gr[aá]tis|n[uú]mero\s*1|melhor\s*do\s*brasil|imperd[ií]vel|lan[cç]amento|acabou\s*de\s*chegar|estoque\s*limitado|agende\s*hoje|atendimento\s*24\s*horas)\b|\b\d+\s*%|R\$\s*\d+', re.I)
BANNED_GENERIC = ('cada detalhe faz parte', 'nossa identidade, nossos produtos',
                  'uma apresentação pensada', 'conheça os produtos da nossa marca',
                  'veja mais opções e novidades', 'um universo de possibilidades',
                  'produtos de qualidade', 'saiba mais sobre nossa proposta')


def trim(value, length=250):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:length]


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').casefold()) if not unicodedata.combining(c))


def topic(info, brief):
    """Descrição derivada só do ramo informado; não inventa serviços ou estoque."""
    activity=trim(info.get('activity') or brief.get('activity'),85)
    sector=brief.get('sector','generico')
    words={
        'bebidas':'bebidas e combinações', 'hamburgueria':'hambúrgueres',
        'pizzaria':'pizzas', 'gastronomia':'gastronomia',
        'moda':'peças e acessórios', 'beleza':'beleza e cuidados',
        'servicos':'serviços', 'pets':'produtos e serviços pet',
        'fitness':'atividades físicas', 'imoveis':'imóveis',
        'tecnologia':'tecnologia', 'automotivo':'serviços automotivos',
        'saude':'cuidados e atendimento', 'educacao':'educação e cursos',
        'generico':'o que fazemos'
    }
    candidate=words.get(sector,'o que fazemos')
    if not activity:return candidate
    # Um ramo descritivo dado pelo cliente é mais específico que a categoria geral.
    return activity[:70].rstrip(' .,:;')


def _safe_copy(text, info, *, minlen=25):
    s=trim(text,350)
    if len(s)<minlen or RISKY.search(s):return False
    if any(v in fold(s) for v in BANNED_GENERIC):return False
    # Não atribuir entrega se o cliente não declarou essa modalidade.
    activity=fold(info.get('activity',''))
    if re.search(r'\b(?:delivery|entreg(?:a|amos|ue|ue[s]?))\b',fold(s)) and not re.search(r'delivery|entreg',activity):return False
    if 'whatsapp' in fold(s) and 'whatsapp' not in activity and 'whatsapp' not in fold(info.get('contact','')):return False
    return True


def campaign(info, brief):
    """Seis pautas diferentes. Captions IA são aceitas apenas com filtro editorial básico."""
    name=trim(info.get('brand'),60)
    sector=brief.get('sector','generico')
    subject=topic(info,brief)
    common=trim(brief.get('tagline'),75)
    headlines=list(brief.get('headlines') or [])
    captions=list(brief.get('captions') or [])
    details=list(brief.get('details') or [])
    # Fallback universal pelo ramo declarado: não afirma falsamente qualidades, disponibilidade ou serviços.
    fallback=[
        f'{name} em foco: {subject}. Conheça a proposta e acompanhe o que compartilhamos por aqui.',
        f'Quer conhecer mais sobre {subject}? Veja as referências deste perfil e fale com a equipe para informações.',
        f'Os detalhes fazem diferença na apresentação de {subject}. Veja os registros e conte o que chamou sua atenção.',
        f'Uma identidade que conversa com quem procura {subject}. Este é o jeito que a {name} escolheu se apresentar.',
        f'{common or "Uma nova maneira de olhar para o que fazemos."} Explore as imagens e descubra mais sobre a nossa proposta.',
        f'Gostou do que viu? Entre em contato pelo canal indicado no perfil e pergunte sobre {subject}.',
    ]
    titles=[
        f'Conheça a {name}',f'{subject[:37].capitalize()} em destaque', 'Veja de perto',
        'O estilo da marca','Inspire-se com a gente','Vamos conversar?'
    ]
    result=[];used_titles=set();used_captions=set()
    for i,role in enumerate(ROLES):
        rawtitle=trim(headlines[i] if i<len(headlines) else '',56)
        title=rawtitle if rawtitle and len(rawtitle)>5 and not RISKY.search(rawtitle) else titles[i]
        if RISKY.search(title) or fold(title) in used_titles or fold(title) in ('nossa marca','novidades da vitrine','produtos em destaque'):
            title=titles[i]
        used_titles.add(fold(title))
        candidate=trim(captions[i] if i<len(captions) else '',250)
        if not _safe_copy(candidate,info) or fold(candidate) in used_captions:
            candidate=trim(details[i] if i<len(details) else '',140)
            if not _safe_copy(candidate,info):candidate=fallback[i]
        used_captions.add(fold(candidate))
        # CTA distinto por objetivo, a legenda não garante estoque e não inventa promoções.
        if i==5: cta='Confira o contato do perfil.'
        elif i==1: cta='Pergunte pelas opções no contato do perfil.'
        elif i==2: cta='Veja mais detalhes nas imagens.'
        else: cta='Acompanhe o perfil para conhecer mais.'
        if not re.search(r'(?i)\b(?:perfil|contato|fale|converse|acompanhe|confira|veja|peça|saiba|entre em contato)\b',candidate):
            candidate=candidate.rstrip(' .!')+'. '+cta
        result.append({'number':i+1,'role':role,'title':title[:56], 'caption':candidate,
                       'source':'briefing_validado' if candidate != fallback[i] else 'fallback_editorial',
                       'briefing_title':rawtitle})
    return result


def stories(info,brief):
    posts=campaign(info,brief)
    name=trim(info.get('brand'),50)
    subject=topic(info,brief)
    return [
      {'number':1,'role':'GANCHO','title':f'{name} em destaque','body':f'Conheça mais sobre {subject}.','cta':'Veja o próximo story'},
      {'number':2,'role':'APRESENTAÇÃO','title':posts[1]['title'],'body':posts[1]['caption'][:115],'cta':'Confira os detalhes'},
      {'number':3,'role':'VALOR','title':posts[2]['title'],'body':posts[2]['caption'][:115],'cta':'Conheça o perfil'},
      {'number':4,'role':'AÇÃO','title':'Vamos conversar?','body':f'Dúvidas sobre {subject}?','cta':'Fale pelo contato do perfil'},
    ]


def write_editorial_files(root,info,brief):
    root=Path(root)
    base=root/'03_vitrine_digital';base.mkdir(parents=True,exist_ok=True)
    items=campaign(info,brief); sts=stories(info,brief)
    tag=trim(brief.get('hashtags'),100)
    contact=trim(info.get('contact'),75)
    parts=[]
    for x in items:
        lines=[f"POST {x['number']:02d}: {x['role']}",x['title'],x['caption']]
        if contact:lines.append('Contato: '+contact)
        if tag:lines.append(tag)
        parts.append('\n'.join(lines))
    (base/'legendas_prontas_para_revisao.txt').write_text('\n\n'.join(parts)+'\n',encoding='utf-8')
    storytext='\n\n'.join(f"STORY {s['number']:02d} · {s['role']}\nTÍTULO: {s['title']}\nTEXTO: {s['body']}\nAÇÃO: {s['cta']}" for s in sts)
    (base/'textos_stories.txt').write_text(storytext+'\n',encoding='utf-8')
    manifest={'source':'direcao Gemini + validacao editorial local', 'roles':[p['role'] for p in items],
              'headline_unique':len({fold(p['title']) for p in items})==6,
              'caption_unique':len({fold(p['caption']) for p in items})==6,
              'sector':brief.get('sector','generico'), 'review_required':True,'posts':items,'stories':sts}
    qa=root/'05_controle_de_qualidade';qa.mkdir(exist_ok=True)
    (qa/'planejamento_editorial.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return items,sts


def brand_lockup(root,info,brief,source_image):
    """Logo horizontal editorial em PNG, gerado localmente sem chamar fal.ai.

    É uma proposta baseada no símbolo recebido; NÃO é um arquivo vetorial,
    nem prova de direito autoral ou originalidade.
    """
    base=Path(root)/'02_perfil_express';base.mkdir(parents=True,exist_ok=True)
    name=trim(info.get('brand'),65) or 'Marca'
    act=trim(info.get('activity'),72)
    c=str(brief.get('accent','#FF6E16'))
    if not re.fullmatch(r'#[0-9A-Fa-f]{6}',c):c='#FF6E16'
    fontbold=next((p for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','C:/Windows/Fonts/segoeuib.ttf'] if Path(p).exists()),None)
    fontreg=next((p for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','C:/Windows/Fonts/segoeui.ttf'] if Path(p).exists()),None)
    def font(n,bold=False):
        p=fontbold if bold else fontreg
        return ImageFont.truetype(p,n) if p else ImageFont.load_default()
    with Image.open(source_image) if isinstance(source_image,(str,Path)) else source_image.copy() as src:
        from photo_adapt import smart_fit
        symbol=smart_fit(src,(440,440),mode='logo')
    # Fundo escuro é deliberado: não remover fundo com IA para evitar danificar a marca.
    for variant,bg,fg,muted in [('escuro','#12131B','#FFFFFF','#CFD2DC'),('claro','#F5F5F2','#15151A','#4B5563')]:
        can=Image.new('RGB',(1600,600),bg);d=ImageDraw.Draw(can)
        can.paste(symbol,(65,80))
        d.rectangle((538,115,547,485),fill=c,width=9)
        size=86
        while size>34 and d.textbbox((0,0),name,font=font(size,True))[2]>990:size-=2
        d.text((600,205),name,font=font(size,True),fill=fg)
        if act:
            size=31
            while size>19 and d.textbbox((0,0),act,font=font(size))[2]>960:size-=1
            d.text((604,325),act,font=font(size),fill=muted)
        d.rectangle((602,420,870,427),fill=c)
        can.save(base/f'logo_horizontal_{variant}_1600x600.png',format='PNG',optimize=True)
    return ['02_perfil_express/logo_horizontal_escuro_1600x600.png','02_perfil_express/logo_horizontal_claro_1600x600.png']


def optimize_existing_package(root):
    """Atualização sem consumo de créditos dos textos e logo de um ZIP já produzido."""
    root=Path(root)
    info=json.loads((root/'INFO_PEDIDO.json').read_text(encoding='utf-8'))
    qa=root/'05_controle_de_qualidade'
    meta=json.loads((qa/'briefing_criativo.json').read_text(encoding='utf-8'))
    brief=meta['direction']
    from bio_engine import generate_bio, generate_bio_options, suggested_name, write_html_preview
    base=root/'02_perfil_express'
    if base.exists() and (base/'foto_de_perfil_1080.png').exists():
        (base/'bio_sugerida.txt').write_text(generate_bio(info,brief),encoding='utf-8')
        (base/'bios_3_opcoes.txt').write_text(generate_bio_options(info,brief),encoding='utf-8')
        (base/'nome_perfil_sugerido.txt').write_text(suggested_name(info,brief),encoding='utf-8')
        brand_lockup(root,info,brief,base/'foto_de_perfil_1080.png')
        if all((base/f'capa_destaque_{i:02d}.png').exists() for i in range(1,6)):
            write_html_preview(root,info,brief)
    if (root/'03_vitrine_digital').is_dir():
        write_editorial_files(root,info,brief)
    return {'name':info.get('brand'),'plan':info.get('plan'),'review_required':True}
