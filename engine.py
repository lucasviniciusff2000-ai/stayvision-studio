"""StayVision Business | Motor de fotos e design + briefing opcional via Gemini."""
from __future__ import annotations
import os, io, json, math, re, shutil, textwrap, zipfile, unicodedata
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = 32_000_000
PLANS = {
    'fotos': {'name':'Fotos Business', 'price':59.90, 'photos':6, 'brand':False, 'feed':0, 'stories':0, 'premium':0},
    'perfil': {'name':'Perfil Express', 'price':149.90, 'photos':0, 'brand':True, 'feed':0, 'stories':0, 'premium':0},
    'vitrine': {'name':'Vitrine Digital', 'price':249.90, 'photos':0, 'brand':True, 'feed':6, 'stories':4, 'premium':0},
    'premium': {'name':'Feed Premium', 'price':399.90, 'photos':8, 'brand':True, 'feed':6, 'stories':4, 'premium':3},
}

# Biblioteca local inicial de direção criativa: sem API ou custo por chamada.
# Não há classificação visual automática: o setor só é identificado pelos nomes
# da marca e dos arquivos, com revisão manual exigida quando for incerto.
SECTORS = {
    'pizzaria': {
        'label':'Pizzaria', 'keys':['pizzaria','pizza','calabresa','pepperoni','pizz'], 'accent':'#D76523',
        'tagline':'Uma boa escolha começa pelo sabor.',
        'headlines':['Um convite ao sabor','Escolha sua próxima pizza','O sabor em primeiro plano','Seu momento pede pizza','Uma fatia de vontade','Que tal pizza hoje?'],
        'highlights':['Cardápio','Sabores','Pedidos','Clientes','Contato'],
        'hashtags':'#Pizza #Pizzaria #Sabores',
        'details':['Escolha o sabor que combina com o momento.','Uma foto que dá vontade de escolher.','Conheça nossas opções e escolha a sua.','Confira as novidades e fale com a equipe.','Seu próximo pedido começa por aqui.','Descubra mais no nosso perfil.']
    },
    'hamburgueria': {
        'label':'Hamburgueria', 'keys':['hamburguer','hamburger','burger','lanche','lanches','xsalada','sanduiche','cheeseburger'], 'accent':'#D77C28',
        'tagline':'O próximo desejo tem sabor de lanche.',
        'headlines':['Deu vontade de hambúrguer?','Olha só esse lanche','Seu momento de sabor','Um lanche que chama atenção','Escolha seu próximo favorito','Bateu aquela fome?'],
        'highlights':['Cardápio','Lanches','Pedidos','Clientes','Contato'],
        'hashtags':'#Hamburguer #Lanches #Hamburgueria',
        'details':['Conheça nossas opções de lanches.','Um lanche para entrar na sua lista.','Confira o cardápio e escolha o seu.','Quer saber mais? Entre em contato.','Seu próximo pedido pode começar agora.','Confira o perfil e conheça nossas opções.']
    },
    'gastronomia': {
        'label':'Gastronomia', 'keys':['restaurante','bistro','sabor','food','comida','gastronomia','delivery','cozinha','cafe','cafeteria','padaria','acai','confeitaria','doce','bolo','sushi'], 'accent':'#CC6E34',
        'tagline':'Sabores para descobrir e compartilhar.',
        'headlines':['Um convite ao sabor','Deu vontade de provar?','Seu momento mais gostoso','Escolha o que dá vontade','Uma pausa com sabor','O próximo sabor te espera'],
        'highlights':['Cardápio','Opções','Pedidos','Clientes','Contato'],
        'hashtags':'#Gastronomia #Comida #Sabores',
        'details':['Conheça nossas opções.','Tem sempre uma boa razão para escolher algo gostoso.','Confira mais opções no nosso perfil.','Entre em contato e saiba mais.','Que tal descobrir seu próximo favorito?','Veja as novidades por aqui.']
    },
    'beleza': {
        'label':'Beleza e bem-estar', 'keys':['beleza','make','maquiagem','cosmetico','estetica','salon','salao','barbearia','hair','cabelo','manicure','unha','spa','skincare'], 'accent':'#985A89',
        'tagline':'Seu estilo merece atenção aos detalhes.',
        'headlines':['Seu estilo, em destaque','Os detalhes fazem diferença','Cuide do seu momento','Novas inspirações para você','Um novo olhar para o estilo','Conheça nossas opções'],
        'highlights':['Serviços','Trabalhos','Agenda','Clientes','Contato'],
        'hashtags':'#Beleza #Estilo #BemEstar',
        'details':['Conheça os serviços e opções disponíveis.','Explore mais inspirações no nosso perfil.','O seu estilo também conta uma história.','Fale com a equipe para saber mais.','Confira nossos trabalhos.','Uma nova inspiração para você.']
    },
    'moda': {
        'label':'Moda e acessórios', 'keys':['moda','roupa','loja','fashion','vestir','boutique','calcado','joia','bolsa','tenis','acessorio'], 'accent':'#7B5B9D',
        'tagline':'Estilo para mostrar quem você é.',
        'headlines':['Seu estilo em destaque','Escolha seu próximo look','Os detalhes do seu estilo','Descubra novas combinações','Uma nova inspiração','Peças para conhecer'],
        'highlights':['Produtos','Novidades','Looks','Clientes','Contato'],
        'hashtags':'#Moda #Estilo #Look',
        'details':['Confira as peças e novidades.','Seu próximo look pode começar aqui.','Veja outras opções no nosso perfil.','Conheça nossas escolhas de estilo.','Entre em contato e descubra mais.','Explore as novidades.']
    },
    'servicos': {
        'label':'Serviços e negócios', 'keys':['studio','escritorio','consultoria','servico','reforma','assessoria','agencia'], 'accent':'#315B88',
        'tagline':'Uma marca para conhecer de perto.',
        'headlines':['Conheça nossa marca','Apresentação que faz diferença','Seu próximo contato começa aqui','Conheça o que fazemos','Uma nova forma de apresentar','Nossa marca em destaque'],
        'highlights':['Serviços','Sobre','Projetos','Dúvidas','Contato'],
        'hashtags':'#Negocios #Servicos #Marca',
        'details':['Descubra mais sobre nosso trabalho.','Conheça o que apresentamos por aqui.','Veja informações e novidades no perfil.','Estamos disponíveis para conversar.','Conheça mais da nossa marca.','Entre em contato e saiba mais.']
    },
    'bebidas': {
        'label':'Bebidas e conveniência','keys':['copao','copaoflash','flash','bebida','drink','copo','coquetel','energetico','adega'],
        'accent':'#FF6E16','tagline':'O sabor acende cada momento.',
        'headlines':['Descubra os sabores','Um brinde ao momento','Seu copão, seu estilo','Mais energia para celebrar','Sua pausa ganha sabor','Um toque de diversão'],
        'highlights':['Sabores','Opções','Pedidos','Novidades','Contato'],
        'hashtags':'#Bebidas #Sabores #Copao',
        'details':['Veja as opções disponíveis.','Uma identidade que combina com a sua vibe.','Conheça o cardápio.','Compartilhe bons momentos.','Confira nossas novidades.','Entre em contato para saber mais.']
    },
    'pets': {
        'label':'Pet shop e cuidados pet', 'keys':['pet shop','petshop','banho e tosa','veterinaria','veterinario','caes e gatos','ração','racao','animais de estimacao'],
        'accent':'#1A837A','tagline':'Cuidado e carinho para os pets.',
        'headlines':['Um mundo pensado para pets','Cuidados que importam','Detalhes que fazem diferença','Conheça nosso espaço','Pets em destaque','Fale com a equipe'],
        'highlights':['Serviços','Produtos','Fotos','Sobre','Contato'],
        'hashtags':'#Pets #MundoPet #CuidadosPet',
        'details':['Conheça o universo pet.','Veja nossa proposta e nossos registros.','Confira os detalhes visíveis nas fotos.','Saiba mais sobre nosso trabalho.','Explore o que mostramos no perfil.','Entre em contato para informações.']
    },
    'tecnologia': {
        'label':'Tecnologia e eletrônicos','keys':['tecnologia','eletronico','smartphone','celular','informatica','computador','notebook','acessorios tech','assistencia tecnica'],
        'accent':'#295C9C','tagline':'Tecnologia perto do que você precisa.',
        'headlines':['Tecnologia em foco','Veja nossas opções','Detalhes de perto','Conheça a marca','Explorando possibilidades','Fale com a equipe'],
        'highlights':['Produtos','Serviços','Opções','Sobre','Contato'],'hashtags':'#Tecnologia #Eletronicos #Tech',
        'details':['Conheça nossa proposta.','Explore os itens apresentados.','Confira detalhes reais nas imagens.','Veja nossa identidade.','Explore referências e ideias.','Pergunte mais pelo contato do perfil.']
    },
    'fitness': {
        'label':'Treino e bem-estar','keys':['academia','fitness','personal trainer','musculacao','treinamento fisico','pilates','treino funcional','crossfit'],
        'accent':'#206B63','tagline':'Movimento para novas possibilidades.',
        'headlines':['Movimento que inspira','Conheça nossa proposta','Detalhes do nosso espaço','Nossa identidade','Inspiração para se mover','Entre em contato'],
        'highlights':['Serviços','Treinos','Fotos','Sobre','Contato'],'hashtags':'#Fitness #Movimento #Treino',
        'details':['Explore nossa proposta.','Veja a atividade informada no perfil.','Confira registros e ambientes reais.','Conheça nossa identidade.','Movimento é parte da nossa história.','Converse para saber mais.']
    },
    'imoveis': {
        'label':'Imóveis e arquitetura','keys':['imobiliaria','corretor de imoveis','imoveis','arquitetura','arquiteto','design de interiores','decoracao'],
        'accent':'#416172','tagline':'Novas perspectivas para seus espaços.',
        'headlines':['Espaços que inspiram','Conheça o que apresentamos','Detalhes em foco','Nossa identidade','Referências para você','Entre em contato'],
        'highlights':['Projetos','Fotos','Serviços','Sobre','Contato'],'hashtags':'#Imoveis #Arquitetura #Ambientes',
        'details':['Explore nossos espaços e referências.','Veja as imagens com atenção.','Conheça detalhes visíveis no registro.','Descubra mais sobre nossa proposta.','Inspire-se com as referências do perfil.','Entre em contato para informações.']
    },
    'automotivo': {
        'label':'Serviços automotivos','keys':['automotivo','oficina mecanica','mecanica automotiva','lava rapido','estetica automotiva','auto center','pneus','carros'],
        'accent':'#2E566E','tagline':'Seu universo automotivo mais perto.',
        'headlines':['O universo automotivo','Nosso trabalho em foco','Detalhes reais','Conheça nosso espaço','Nosso jeito de fazer','Fale com a equipe'],
        'highlights':['Serviços','Trabalhos','Fotos','Sobre','Contato'],'hashtags':'#Automotivo #Carros #Servicos',
        'details':['Conheça a atividade da empresa.','Veja nossas referências reais.','Observe os detalhes nas imagens.','Saiba mais sobre nossa identidade.','Conheça a proposta do perfil.','Entre em contato para mais informações.']
    },
    'saude': {
        'label':'Saúde e cuidados','keys':['odontologia','dentista','fisioterapia','clinica de saude','clinica odontologica','consultorio','psicologia','saude'],
        'accent':'#287B83','tagline':'Informação e cuidado com responsabilidade.',
        'headlines':['Conheça nosso trabalho','O que fazemos','Nossa equipe e espaço','Nossa identidade','Informação para você','Entre em contato'],
        'highlights':['Serviços','Sobre','Dúvidas','Fotos','Contato'],'hashtags':'#Saude #Cuidados #BemEstar',
        'details':['Conheça o perfil e os serviços declarados.','Explore informações do trabalho.','Veja referências reais.','Saiba mais sobre o espaço.','Conteúdo informativo, sem promessas de resultados.','Entre em contato para mais informações.']
    },
    'educacao': {
        'label':'Educação e cursos','keys':['escola','curso','professor','educacao','idiomas','reforco escolar','aulas','ensino'],
        'accent':'#635B9F','tagline':'Conhecimento abre novas possibilidades.',
        'headlines':['Aprender faz parte','Conheça nossa proposta','Veja mais de perto','Nossa identidade','Ideias para explorar','Entre em contato'],
        'highlights':['Cursos','Serviços','Dúvidas','Sobre','Contato'],'hashtags':'#Educacao #Aprendizado #Cursos',
        'details':['Conheça nossa proposta educacional.','Explore o que apresentamos.','Veja detalhes das referências.','Descubra nossa identidade.','Novas ideias começam com uma pergunta.','Entre em contato para informações.']
    },
    'generico': {
        'label':'Negócio', 'keys':[], 'accent':'#385D9C',
        'tagline':'Descubra o que faz parte da nossa marca.',
        'headlines':['Conheça nossa marca','Um convite para descobrir','A marca em destaque','Veja mais de perto','Descubra nossas novidades','Uma nova maneira de apresentar'],
        'highlights':['Novidades','Produtos','Sobre','Dúvidas','Contato'],
        'hashtags':'#Empreendedorismo #Negocios #Novidades',
        'details':['Conheça o que preparamos para você.','Explore os detalhes da nossa marca.','Confira nossas novidades e informações.','Descubra mais pelo nosso perfil.','Fale com nossa equipe e saiba mais.','Veja mais sobre nossos produtos ou serviços.']
    }
}

def simplified(s):
    x=unicodedata.normalize('NFKD',str(s or '').lower())
    return ''.join(c for c in x if not unicodedata.combining(c))

def create_brief(brand, instagram, contact, photo_paths, activity=""):
    """Direção textual por pistas do nome/arquivos; não inspeciona pixels."""
    names=' '.join(Path(f).name for f in photo_paths)
    b=simplified(brand); n=simplified(names)
    activity=limit(activity,100)
    a=simplified(activity)
    # Ramo informado diretamente pelo cliente tem precedencia sobre nomes de arquivos.
    declared=[]
    if a:
        for cat,d in SECTORS.items():
            if cat=='generico':continue
            score=sum(10 for k in d['keys'] if k in a)
            if score:declared.append((score,cat))
    candidates=[]
    for cat,d in SECTORS.items():
        if cat=='generico': continue
        score=sum(3 for k in d['keys'] if k in b) + sum(1 for k in d['keys'] if k in n)
        if score: candidates.append((score,cat))
    _, sector=(max(declared) if declared else ((0,'generico') if a else max(candidates,default=(0,'generico'))))
    d=SECTORS[sector]
    return {'segment':d['label'],'sector':sector,'tagline':d['tagline'],
            'headlines':d['headlines'],'details':d['details'],'highlights':d['highlights'],
            'hashtags':d['hashtags'],'accent':d['accent'],
            'inference': ('ramo informado pelo cliente' if activity else ('nome da marca/arquivos' if sector!='generico' else 'genérica; identificação do ramo pendente de revisão')),
            'activity':activity,'activity_provided':bool(activity),'instagram':instagram,'contact':contact}

def normalize_instagram(s):
    s=limit(s,100).strip()
    if 'instagram.com/' in s.lower():
        s=s.split('instagram.com/',1)[-1].split('?')[0].strip('/')
    s=s.lstrip('@').strip('/')
    if not re.fullmatch(r'[A-Za-z0-9._]{1,30}',s): raise ValueError('Informe um @ de Instagram válido.')
    return '@'+s

def normalize_contact(s):
    s=limit(s,90)
    if not s or len(s)<5: raise ValueError('Informe um telefone, WhatsApp, e-mail ou site de contato.')
    if any(ord(c)<32 for c in s): raise ValueError('Contato inválido.')
    return s

def concise(s, max_chars=48):
    s=limit(s,max_chars+1)
    return s if len(s)<=max_chars else s[:max_chars-1]+'…'

FONTS = {
    'regular':['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/segoeui.ttf'],
    'bold':['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'C:/Windows/Fonts/arialbd.ttf', 'C:/Windows/Fonts/segoeuib.ttf'],
}

def font(sz, bold=False):
    for p in FONTS['bold' if bold else 'regular']:
        if Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

def limit(s, mx=100):
    return str(s or '').strip()[:mx]

def color(c):
    if re.fullmatch(r'#[0-9A-Fa-f]{6}',str(c or '')): return c
    return '#D87633'

def lighten(rgb, k=0.2):
    return tuple(int(x+(255-x)*k) for x in rgb)

def rgb(h): return tuple(bytes.fromhex(h.lstrip('#')))

def fit_cover(image, size, centering=(.5,.5)):
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=centering)

def wrap(draw, words, f, max_w, max_lines=3):
    lines=[]; line=''
    for word in (words or '').split():
        nxt=(line+' '+word).strip()
        if draw.textbbox((0,0),nxt,font=f)[2] <= max_w: line=nxt
        else:
            if line: lines.append(line)
            line=word
    if line: lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textbbox((0,0),lines[-1]+'…',font=f)[2] > max_w and len(lines[-1])>1: lines[-1]=lines[-1][:-1]
        lines[-1] += '…'
    return lines

def draw_lines(draw, txt, x, y, width, f, fill, spacing=14, max_lines=3):
    lines=wrap(draw,txt,f,width,max_lines)
    for l in lines:
        draw.text((x,y), l, font=f, fill=fill)
        y+=int(f.size*1.32)+spacing
    return y

def fit_one_line(draw, value, max_width, initial_size, min_size=15, bold=False):
    """Limit rendered text by pixel width; avoid overflow with long URLs or names."""
    value=str(value or '')
    for sz in range(initial_size, min_size-1, -1):
        f=font(sz, bold)
        if draw.textbbox((0,0),value,font=f)[2] <= max_width:
            return value, f
    f=font(min_size,bold)
    while value and draw.textbbox((0,0),value+'…',font=f)[2] > max_width:
        value=value[:-1]
    return value+'…',f

def load_photo(path):
    with Image.open(path) as temp:
        temp.load()
        image=ImageOps.exif_transpose(temp)
        if image.mode != 'RGB':
            if image.mode == 'RGBA':
                bg=Image.new('RGBA',image.size, '#ffffff'); bg.alpha_composite(image); image=bg.convert('RGB')
            else: image=image.convert('RGB')
    return image

def save_jpg(im,path): im.save(path, 'JPEG', quality=93, subsampling=0, optimize=True)

def photo_comparison(before, after, out):
    w,h=560,610
    p=Image.new('RGB',(w*2+26,h+65),'#f1eee9')
    for i,im in enumerate((before,after)):
        thumb=fit_cover(im,(w,h)); p.paste(thumb,(i*(w+26),65))
    d=ImageDraw.Draw(p)
    d.text((28,16),'ANTES',font=font(31,True),fill='#1b1d23')
    d.text((w+53,16),'DEPOIS • MODO PUBLICITÁRIO' if os.getenv('STAYVISION_VISUAL_STYLE')=='advertising' else 'DEPOIS • TRATAMENTO FIEL',font=font(26,True),fill='#1b1d23')
    save_jpg(p,out)

def report_plan(root, plan, count, brand, resolution_warnings, note, brief, ai_result):
    p=PLANS[plan]; qa=root/'05_controle_de_qualidade'; qa.mkdir(exist_ok=True)
    parts=[f'STAYVISION BUSINESS | RELATÓRIO DE PRODUÇÃO',f'Plano: {p["name"]} | preço hipotético de teste: R$ {p["price"]:.2f}',f'Empresa: {brand}',f'Fotos originais fornecidas: {count}',f'Capacidade de fotos tratadas no plano: até {p["photos"]}',f'Artes de feed: {p["feed"]}',f'Stories: {p["stories"]}',f'Artes extras premium: {p["premium"]}', '', 'REVISÃO HUMANA OBRIGATÓRIA ANTES DE ENTREGAR', '1. Conferir ingredientes, embalagens e detalhes reais.', '2. Conferir se as fotos não ficaram excessivamente saturadas.', '3. Conferir marca, arroba, textos, promessas e direitos de uso.', '4. Conferir arquivos e formatos para redes sociais.', '5. Confirmar pagamento no sistema comercial separado.', '', 'LIMITAÇÕES:', '- TODO material gráfico deve ser criado por GPT Image via fal.ai; sem fallback gráfico local.', '- Identidade, bio e textos são sugestões; exigem revisão humana antes da entrega.', '- Este pacote NÃO conecta automaticamente a pagamentos, site ou Railway.', '- Redes sociais mudam requisitos e interfaces: validar antes da publicação.']
    parts += [f'Ramo informado pelo cliente: {brief.get("activity") or "não informado"}', f'Ramo estimado: {brief["segment"]}',f'Método de inferência: {brief["inference"]}',f'Frase gerada automaticamente: {brief["tagline"]}',f'Instagram informado: {brief["instagram"]}',f'Contato informado: {brief["contact"]}', f'FONTE DA CRIAÇÃO: {ai_result.provider} / {ai_result.model}', 'A equipe deve conferir a adequação das frases, das imagens e do ramo antes da entrega.']
    parts += ['OBSERVAÇÕES DO MOTOR:'] + ai_result.notes
    if brief.get('visual_evidence'): parts += ['EVIDÊNCIAS VISUAIS:'] + brief['visual_evidence']
    if brief.get('uncertainties'): parts += ['INCERTEZAS:'] + brief['uncertainties']
    if p['photos'] and count < p['photos']:
        parts.append(f'Foram fornecidas {count} foto(s) reais: todas são tratadas no Premium direto; capacidade máxima é {p["photos"]}. NÃO inventar fotos ausentes.')
    parts += resolution_warnings+[note]
    (qa/'relatorio.txt').write_text('\n'.join(parts),encoding='utf-8')

def count_visual_calls(plan,n,sample_only=False):
    """Obrigatório autorizar todas as tentativas antes de gastar Gemini ou fal.ai."""
    if sample_only:
        if plan!='perfil':raise ValueError('Amostra única é exclusiva do Perfil Express.')
        return 1
    if plan=='fotos':return min(n,6)
    if plan=='perfil':return 6  # símbolo e cinco covers
    if plan=='vitrine':return 16 # símbolo, cinco covers, seis posts, quatro stories
    if plan=='premium':return 19+n # identidade 6 + posts 6 + stories 4 + extras 3 + N fotos reais
    raise ValueError('Plano inválido')

def build(order_dir, plan, brand, instagram, contact, photo_paths, sample_only=False, activity="", preapproved_creative=None, preserve_existing_logo=False,logo_reference_path=None):
    """Gemini cria briefing; GPT Image na fal.ai cria TODA arte visual, sem templates locais."""
    if plan not in PLANS:raise ValueError('Plano inválido.')
    if not (0<=len(photo_paths)<=8 and (len(photo_paths)>0 or plan=='perfil')):raise ValueError('Fotos obrigatórias para este plano; Perfil Express permite criar uma identidade sem logotipo.')
    if plan=='fotos' and len(photo_paths)>6:raise ValueError('Fotos Business aceita no máximo seis fotos.')
    if plan=='premium' and not 1<=len(photo_paths)<=8:raise ValueError('Plano Premium aceita entre 1 e 8 fotos originais.')
    brand=limit(brand,45)
    if len(brand)<2:raise ValueError('Nome da marca inválido.')
    instagram=normalize_instagram(instagram);contact=normalize_contact(contact)
    from image_ai import enabled,preflight,edit_photo,model
    from photo_quality import diagnose, prepare_reference, inspect_result, save_report
    from creative_ai import create as create_creative
    from design_ai import profile_assets_ai,content_assets_ai
    if not enabled():raise RuntimeError('GPT Image DESLIGADO. Não são produzidos modelos genéricos.')
    required_calls=count_visual_calls(plan,len(photo_paths),sample_only)
    preflight(required_calls)
    offline_brief=create_brief(brand,instagram,contact,photo_paths,activity=activity)
    creative_refs=photo_paths if photo_paths else ([logo_reference_path] if logo_reference_path is not None else [])
    ai_result=(preapproved_creative if preapproved_creative is not None else create_creative(brand,instagram,contact,creative_refs,offline_brief,activity=activity))
    if ai_result.provider!='gemini':
        raise RuntimeError('Gemini não está ativo. Interrompido ANTES da primeira chamada de imagem paga.')
    brief=ai_result.data
    flags=brief.get('quality_flags') or []
    root=Path(order_dir);root.mkdir(parents=True,exist_ok=True)
    orig_dir=root/'00_originais';orig_dir.mkdir(exist_ok=True)
    originals=[];source_photos=[];notes=[];photo_logs=[];design_logs=[];generated_photos=0;photo_diagnostics=[]
    for i,file in enumerate(photo_paths,1):
        im=load_photo(file)
        originals.append(im)
        quality_input=diagnose(im)
        photo_diagnostics.append(quality_input)
        for warning in quality_input['warnings']:
            notes.append(f'Imagem {i}: {warning}')
        path=orig_dir/f'original_{i:02d}.jpg'
        save_jpg(im,path);source_photos.append(im)
        if min(im.size)<700:notes.append(f'Imagem {i}: resolução pequena; revisar qualidade.')
    # Fotos Business: SOMENTE produção fotográfica; os demais têm motor de marca.
    if plan in ('fotos','premium'):
        dest=root/'01_fotos_tratadas';dest.mkdir(exist_ok=True)
        qa=root/'05_controle_de_qualidade';qa.mkdir(exist_ok=True)
        for i,im in enumerate(originals[:PLANS[plan]['photos']]):
            sector=os.environ.get('STAYVISION_TEST_SECTOR') or brief.get('sector','generico')
            obs=brief.get('photo_observations') or []
            diagnosis=photo_diagnostics[i]
            prepared,pre_log=prepare_reference(im,diagnosis)
            pre_dir=qa/'referencias_preparadas';pre_dir.mkdir(exist_ok=True)
            save_jpg(prepared,pre_dir/f'referencia_{i+1:02d}.jpg')
            observation=(obs[i] if i<len(obs) else '')+' '+(' '.join(diagnosis['warnings']))
            pro,log=edit_photo(prepared,brand,observation,sector)
            save_jpg(pro,dest/f'foto_profissional_{i+1:02d}.jpg')
            photo_comparison(im,pro,qa/f'antes_depois_{i+1:02d}.jpg')
            verdict=inspect_result(im,pro,sector=sector)
            save_report(qa/f'qualidade_foto_{i+1:02d}.json',{'preparation':pre_log,'final_check':verdict})
            log['quality_review_status']=verdict['status']
            log['quality_review_flags']=verdict['review_flags']
            photo_logs.append(log);generated_photos+=1
            # Premium: arte de feed usa fotos comerciais aprováveis como referência factual.
            source_photos[i]=pro
    if PLANS[plan]['brand']:
        logo_refs=([logo_reference_path] if logo_reference_path is not None else (originals if preserve_existing_logo else []))
        logo,meta=profile_assets_ai(root,brand,brief,logo_refs,instagram,contact,sample_only=sample_only, preserve_existing_logo=preserve_existing_logo)
        design_logs.extend(meta)
        if not sample_only and PLANS[plan]['feed']:
            design_logs.extend(content_assets_ai(root,brand,brief,source_photos,logo,
                    feed=PLANS[plan]['feed'],stories=PLANS[plan]['stories'],extras=PLANS[plan]['premium']))
    all_logs=photo_logs+design_logs
    notes.extend(['CONFERIR BRIEFING: '+x for x in flags])
    notes.append(f'Peças visuais produzidas por GPT Image via fal.ai: {len(all_logs)}/{required_calls}.')
    notes.append('Criatividade: Gemini; identidade, imagens e artes: GPT Image. NENHUM template genérico.')
    if sample_only:
        notes.append('AMOSTRA DE UMA ÚNICA IMAGEM. NÃO É PACOTE ENTREGÁVEL; geração das cinco capas PENDENTE.')
    notes.append('Fotos enviadas ao Gemini e fal.ai conforme fluxo autorizado. Revisão humana obrigatória.')
    if originals:
        qa=root/'05_controle_de_qualidade';qa.mkdir(exist_ok=True)
        save_report(qa/'diagnostico_entrada_fotos.json',{'engine':'SV_PHOTO_QUALITY_3_2','photos':photo_diagnostics,'api_calls':0,'notes':'Exame heurístico gratuito; não mede fidelidade factual.'})
    report_plan(root,plan,len(originals),brand,notes,
                'Sem checkout, PIX, publicação nem envio ao cliente. Rascunho interno.',brief,ai_result)
    qa=root/'05_controle_de_qualidade';qa.mkdir(exist_ok=True)
    (qa/'edicao_de_imagens.json').write_text(json.dumps({
        'image_engine':'fal_gpt_image_2_5','images_generated':len(all_logs),
        'photo_edits':generated_photos,'design_artworks':len(design_logs),
        'expected_visual_calls':required_calls,'details':all_logs,
        'billing':'consulte o painel fal.ai; limites contam chamadas, não USD',
        'approval_status':'INCOMPLETO_AMOSTRA' if sample_only else 'REVISAO_NECESSARIA'
    },ensure_ascii=False,indent=2),encoding='utf-8')
    (qa/'briefing_criativo.json').write_text(json.dumps({
        'provider':ai_result.provider,'model':ai_result.model,'notes':ai_result.notes,
        'usage':ai_result.usage,'direction':brief
    },ensure_ascii=False,indent=2),encoding='utf-8')
    info={'plan':plan,'plan_name':PLANS[plan]['name'],'price_test_brl':PLANS[plan]['price'],
          'brand':brand,'instagram':instagram,'contact':contact,'activity':limit(activity,100),
          'brand_and_copy_auto':True,'creative_direction':brief,'photos_received':len(originals),
          'public_upload_enabled':False,'payment_connected':False,'generated_text_source':ai_result.provider,
          'ai_model':ai_result.model,'ai_notes':ai_result.notes,'human_approval_required':True,
          'photo_edit_engine':'generative_image_ai' if generated_photos else 'not_applicable',
          'photo_edits':generated_photos,'creative_compositions':0,
          'premium_photos_included':generated_photos if plan=='premium' else 0,
          'photo_quality_engine':'SV_PHOTO_QUALITY_3_2',
          'generative_photo_count':generated_photos,'expected_api_calls':required_calls,
          'generative_design_count':len(design_logs),'brand_engine':'gpt_image_2_5_fal_ai',
          'content_engine':'gemini','sample_only':bool(sample_only),
          'brand_conflict':bool(brief.get('brand_mismatch_review')), 'creative_quality_flags':flags,
          'marketing_upgrade_version':'3.0' if PLANS[plan]['brand'] else None}
    (root/'INFO_PEDIDO.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    # Estudio V3.5: montar mockups finais offline, sem chamada extra a provedores.
    if PLANS[plan]['brand'] and not sample_only:
        from instagram_preview import create_previews, VERSION as PREVIEW_VERSION
        files=create_previews(root)
        if files:
            info['visual_preview_version']=PREVIEW_VERSION
            (root/'INFO_PEDIDO.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=root.parent/(root.name+'.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for file in root.rglob('*'):
            if file.is_file():z.write(file,file.relative_to(root))
    return archive
