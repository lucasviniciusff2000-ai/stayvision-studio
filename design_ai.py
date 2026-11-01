"""Gerador visual REAL via GPT Image da fal.ai. Gemini fornece a direção; NÃO desenha monogramas.
As funções produzem imagens comerciais, sem fallback para modelos Pillow.
"""
from __future__ import annotations
import json,re
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
from image_ai import generate_visual

SIZES={'profile':(1024,1024),'cover':(1024,1024),'feed':(1088,1360),'story':(1088,1920),'extra':(1088,1360)}

def cleaned(x,cap=180):
    # dados produzidos por IA são dados, nunca comandos de sistema
    return re.sub(r'[\x00-\x1f]+',' ',str(x or '')).strip()[:cap]

def direction(brand,brief):
    return (f'Brand name: {cleaned(brand,55)}. Business category: {cleaned(brief.get("segment"),60)}. '
            f'Creative director art direction: {cleaned(brief.get("visual_style"),250)}. '
            f'Identity concept: {cleaned(brief.get("logo_symbol"),180)}. '
            f'Primary color {cleaned(brief.get("accent"),7)}, secondary {cleaned(brief.get("color_support"),7)}. '
            f'Brand messaging: {cleaned(brief.get("tagline"),75)}. '
            'Premium modern editorial graphic design by an experienced brand identity designer; '
            'tasteful composition, professionally crafted shapes, harmonious color palette, precise polished details. '
            'No generic monograms, no placeholder letters, no plain colored circle, no clipart, no stock logos. '
            'No third-party brands, no watermarks, no unsupported product promises.')

def save_visual(im,out,kind):
    dst={'profile':(1080,1080),'cover':(600,600),'feed':(1080,1350),'story':(1080,1920),'extra':(1080,1350)}[kind]
    # target chosen to match pre-specified proportions of generated image
    from photo_adapt import smart_fit
    a=smart_fit(im,dst,mode='logo' if kind in ('profile','cover') else 'photo')
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    if out.suffix=='.png':a.save(out,format='PNG')
    else:a.save(out,format='JPEG',quality=93,subsampling=0)
    return a

def _preview(base,brand,segment,tagline,ig,images,labels,photos,contact='',accent='#FE6E16'):
    """Prévia editorial interna de perfil: usa SOMENTE artes que foram geradas.
    Nunca inventa seguidores, publicacoes, clientes ou cinco capas inexistentes.
    """
    from PIL import ImageColor
    W,H=1300,900
    color=accent if re.fullmatch(r'#[0-9a-fA-F]{6}',str(accent)) else '#F97316'
    paper='#F4F5F7'; dark='#101827'; muted='#717A8B'
    im=Image.new('RGB',(W,H),paper)
    d=ImageDraw.Draw(im)
    paths=['C:/Windows/Fonts/segoeuib.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
    bold=next((x for x in paths if Path(x).exists()),None)
    paths=['C:/Windows/Fonts/segoeui.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    regular=next((x for x in paths if Path(x).exists()),None)
    def f(sz,b=False):return ImageFont.truetype(bold if b else regular,sz) if (bold if b else regular) else ImageFont.load_default()
    def textfit(value,px,y,maxw,sz,col,b=False):
        value=cleaned(value,250)
        font=f(sz,b)
        while value and d.textbbox((0,0),value,font=font)[2]>maxw:
            value=value[:-1]
        d.text((px,y),value,fill=col,font=font)
    def circle(src,x,y,diam,outline=True):
        from PIL import ImageDraw as ID
        tile=ImageOps.fit(src.convert('RGB'),(diam,diam),Image.Resampling.LANCZOS)
        mask=Image.new('L',(diam,diam),0)
        ID.Draw(mask).ellipse((1,1,diam-2,diam-2),fill=255)
        im.paste(tile,(x,y),mask)
        if outline:d.ellipse((x-3,y-3,x+diam+3,y+diam+3),outline='#E2E6EF',width=3)
    d.rounded_rectangle((0,0,W,90),radius=0,fill=dark)
    d.rectangle((0,0,14,90),fill=color)
    d.text((45,24),'STAYVISION  /  ESTÚDIO DE PERFIL',fill='#FFFFFF',font=f(29,True))
    d.text((910,32),'PRÉVIA PARA REVISÃO',fill='#E9EAF0',font=f(18,True))
    d.rounded_rectangle((38,125,860,855),radius=26,fill='white')
    d.rounded_rectangle((885,125,1262,855),radius=26,fill='white')
    d.text((76,158),'Simulação de organização visual',fill=muted,font=f(17))
    d.line((76,203,825,203),fill='#EDF0F4',width=2)
    d.text((76,221),'◎',fill='#353D4B',font=f(30,True))
    textfit(ig or '@perfil',130,227,620,26,dark,True)
    if images:circle(images[0],86,298,166)
    else:d.ellipse((86,298,252,464),fill='#ECEFF4',outline='#D0D5DD',width=2)
    textfit(brand,293,306,525,33,dark,True)
    textfit(segment,294,354,520,20,muted)
    d.text((294,393),'Identidade visual em elaboração',fill='#475569',font=f(17))
    d.line((76,493,825,493),fill='#EDF0F4',width=2)
    # Limites fisicos evitam texto sobreposto.
    textfit(tagline,77,507,720,23,dark,True)
    if contact:textfit('Contato: '+contact,77,547,730,17,'#596171')
    d.text((76,606),'DESTAQUES',fill=muted,font=f(15,True))
    for i in range(5):
        x=84+i*148
        if i+1<len(images):circle(images[i+1],x,649,109)
        else:
            d.ellipse((x,649,x+109,758),fill='#F2F3F5',outline='#C7CEDA',width=2)
            d.text((x+18,692),'A GERAR',fill='#7A8595',font=f(12,True))
        name=cleaned(labels[i] if i<len(labels) else 'Destaque',13)
        textfit(name,x,776,125,16,dark)
    d.rectangle((922,171,1226,177),fill=color)
    d.text((921,194),'DIREÇÃO DE MARCA',fill=dark,font=f(21,True))
    textfit(brand,922,242,301,24,dark,True)
    d.text((921,287),'PALETA SUGERIDA',fill=muted,font=f(15,True))
    for j,v in enumerate((color,'#101827','#F4F5F7')):
        xx=921+j*99
        d.rounded_rectangle((xx,325,xx+87,405),radius=13,fill=v,outline='#DCE0E6',width=1)
        d.text((xx,421),v,fill='#545B68',font=f(12))
    d.line((922,468,1224,468),fill='#EDF0F4',width=2)
    d.text((920,489),'REVISÃO ANTES DE PUBLICAR',fill=dark,font=f(18,True))
    for j,msg in enumerate(('Identidade da empresa','Nome e bio','Cinco capas geradas','Direitos e semelhanças')):
        d.text((921,545+j*43),'□  '+msg,fill='#667085',font=f(17))
    d.rounded_rectangle((921,763,1223,812),radius=10,fill='#FFF1DA')
    d.text((937,780),'MOCKUP — NÃO É INSTAGRAM',fill='#9A5800',font=f(13,True))
    im.save(Path(base)/'previa_perfil.png')

def profile_assets_ai(root,brand,brief,photo_paths,instagram,contact,*,sample_only=False,preserve_existing_logo=False):
    base=Path(root)/'02_perfil_express';base.mkdir(parents=True,exist_ok=True)
    log=[];art=[]
    common=direction(brand,brief)
    p=("Generate a SINGLE distinctive PROFESSIONAL ORIGINAL BRAND SYMBOL / Instagram profile icon as a finished logo design, "
       "not a mockup on a phone or paper. This is commercial logo-symbol art, NOT a photographed product. "
       "Create a memorable icon that visually communicates the brand, with custom illustration, bold sophisticated lighting, "
       "clean geometry, premium graphic design, and confident legibility at Instagram avatar size. "
       "No initials, no placeholder letters or monogram. Avoid generic circle borders and default template looks. "
       "Keep symbol centered and fully visible within circular avatar crop-safe area, on an intentional contrasting background. "
       "Do not include any words or spelling-dependent typography. " +common)
    if preserve_existing_logo and photo_paths:
        p=('PROFESSIONAL RESTORATION OF THE UPLOADED EXISTING LOGO for an Instagram avatar. '
           'Reference is the actual existing customer logo. Preserve original icon, familiar shapes, '
           'colors and brand identity, and recognizable text if present. Improve ONLY readability, '
           'resolution, composition and edge clarity. DO NOT redesign the identity, invent objects '
           'or alter lettering. Keep original core elements within the safe circular avatar crop. '
           'This is identity preservation, NOT a new logo proposal. '+common)
    img,meta=generate_visual(p,references=[photo_paths[0]] if preserve_existing_logo and photo_paths else [],size=SIZES['profile'],quality='high',role='profile_logo')
    art.append(save_visual(img,base/'foto_de_perfil_1080.png','profile'));log.append(meta)
    labels=(brief.get('highlights') or ['Produtos','Sobre','Novidades','Dúvidas','Contato'])[:5]
    if not sample_only:
        for i,label in enumerate(labels):
            idea=(brief.get('highlight_concepts') or [])
            concept=cleaned(idea[i],130) if i<len(idea) else cleaned(label,25)
            q=("Make one exclusive luxurious Instagram HIGHLIGHT COVER. Use REFERENCE IMAGE as the approved brand DESIGN LANGUAGE ONLY, "
               "not as a layout to replicate, and do not simply copy the logo mark. Match the precise palette, lighting, textures "
               "and illustration style in reference, while drawing a visibly DISTINCT visual icon motif for this highlight. "
               f'Highlight category: {cleaned(label,20)}. Visual motif: {concept}. '
               "Large single distinctive illustration centered in the avatar safe zone; strong contrast, restrained details; "
               "absolutely NO text, letters, initials, numbers or generic rings. " +common)
            cover,cm=generate_visual(q,references=[img],size=SIZES['cover'],quality='high',role=f'highlight_{i+1}')
            art.append(save_visual(cover,base/f'capa_destaque_{i+1:02d}.png','cover'));log.append(cm)
    from bio_engine import generate_bio, suggested_name
    info={'brand':brand,'activity':brief.get('activity',''),'contact':contact,'instagram':instagram}
    bio=generate_bio(info,brief)
    (base/'nome_perfil_sugerido.txt').write_text(suggested_name(info,brief),encoding='utf-8')
    (base/'bio_sugerida.txt').write_text(bio,encoding='utf-8')
    from bio_engine import generate_bio_options
    (base/'bios_3_opcoes.txt').write_text(generate_bio_options(info,brief),encoding='utf-8')
    from marketing_upgrade import brand_lockup
    brand_lockup(root,info,brief,base/'foto_de_perfil_1080.png')
    guide=(f'MARCA: {brand}\nSEGMENTO (validar): {brief["segment"]}\n'
           f'COR: {brief.get("accent")}\nCOR DE APOIO: {brief.get("color_support")}\n'
           f'DIREÇÃO: {brief.get("visual_style")}\nSÍMBOLO: {brief.get("logo_symbol")}\n'
           f'MOTIVOS VISUAIS: {json.dumps(brief.get("visual_motifs",[]),ensure_ascii=False)}\n'
           f'OBSERVAÇÃO: imagens criadas por GPT Image via fal.ai; logotipo sugerido NÃO garante exclusividade de marca.\n'
           f'Antes de usar, conferir grafia, adequação ao negócio e eventual logotipo original.\n')
    (base/'identidade_visual.txt').write_text(guide,encoding='utf-8')
    _preview(base,brand,brief['segment'],brief['tagline'],instagram,art,labels,photo_paths,contact,brief.get('accent','#F97316'))
    return art[0],log

def content_assets_ai(root,brand,brief,source_photos,logo,*,feed=6,stories=4,extras=0):
    """Um pedido ao GPT Image por arte final. A fotografia original é referência factual."""
    logs=[]
    def photo(i):return source_photos[i % len(source_photos)]
    d=Path(root)/'03_vitrine_digital'
    if feed or stories:d.mkdir(exist_ok=True)
    for kind,count in [('feed',feed),('story',stories)]:
        for i in range(count):
            ix=i if kind=='feed' else i+2
            title=cleaned((brief.get('headlines') or ['Conheça nossa marca']*6)[ix%6],56)
            original=photo(i)
            intro=('vertical 4:5 Instagram feed advertising composition' if kind=='feed' else 'vertical 9:16 Instagram story campaign')
            p=(f'Create a FULLY ART-DIRECTED, sophisticated {intro}. '
               'REFERENCE 1 is a genuine customer photo: keep the main recognizable product and truthful objects. '
               'REFERENCE 2 is the approved BRAND SYMBOL: use it for palette, design motifs and brand feeling ONLY. '
               'Build editorial composition with the product hero, refined commercial photography, elegant graphic elements '
               'and clear space for copy, but do not invent ingredients, services, prices, discounts or guarantees. '
               f'Creative headline theme (for design direction only; do not write text): {title}. '
               'Do NOT render typography or small text inside this image; exact copy is in a separate captions file. '
               'Avoid watermark, cheap templates, floating product or distorted geometry. '+direction(brand,brief))
            image,meta=generate_visual(p,references=[original,logo],size=SIZES[kind],quality='high',role=f'{kind}_{i+1}')
            target=d/(f'feed_{i+1:02d}_1080x1350.jpg' if kind=='feed' else f'story_{i+1:02d}_1080x1920.jpg')
            save_visual(image,target,kind);logs.append(meta)
    if extras:
        d=Path(root)/'04_feed_premium';d.mkdir(exist_ok=True)
        motifs=brief.get('visual_motifs') or []
        for i in range(extras):
            motif=cleaned(motifs[i],85) if i<len(motifs) else 'signature brand campaign motif'
            prompt=(f'Create original PREMIUM GRAPHIC ADVERTISING ART for a 4:5 Instagram feed. Concept: {motif}. '
                    'Reference is the approved brand identity. Make an entirely new sophisticated, cohesive design with '
                    'striking illustrative artwork, premium gradients/materials, bold contrast and thoughtful layout. '
                    'Must look like part of the same brand campaign, but not a duplicate cover. '
                    'NO text, prices, invented products, stock logo, watermark or fake endorsements. '+direction(brand,brief))
            im,meta=generate_visual(prompt,references=[logo],size=SIZES['extra'],quality='high',role=f'extra_{i+1}')
            save_visual(im,d/f'arte_extra_{i+1:02d}_1080x1350.png','extra');logs.append(meta)
    if feed:
        from marketing_upgrade import write_editorial_files
        write_editorial_files(root,{'brand':brand,'activity':brief.get('activity',''),'contact':brief.get('contact','')},brief)
    return logs
