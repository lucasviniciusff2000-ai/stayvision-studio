"""Previa editorial realista do perfil, gerada somente a partir dos materiais entregues.

Sem APIs, sem seguidores/links ficticios. Nao publica nada no Instagram.
Todos os caminhos sao prefixos fixos sob a pasta de um pedido local.
"""
from __future__ import annotations
import json, re, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

VERSION = '5.0'
BG = '#07090E'
INK = '#F5F4F1'
MUTED = '#A5A9B2'
FALLBACK = '#BD9058'


def _font(size, bold=False):
    choices = ([r'C:\Windows\Fonts\segoeuib.ttf',r'C:\Windows\Fonts\arialbd.ttf',
                '/usr/share/fonts/opentype/inter/Inter-Bold.otf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if bold else
               [r'C:\Windows\Fonts\segoeui.ttf',r'C:\Windows\Fonts\arial.ttf',
                '/usr/share/fonts/opentype/inter/Inter-Regular.otf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])
    for f in choices:
        if Path(f).is_file():return ImageFont.truetype(f,size)
    return ImageFont.load_default()


def _text(d,xy,s,size=26,color=INK,bold=False,max_width=None):
    s=str(s or '').strip()
    if not s:return
    f=_font(size,bold)
    if max_width:
        while size>15 and d.textbbox((0,0),s,font=f)[2]>max_width:
            size-=1;f=_font(size,bold)
        if d.textbbox((0,0),s,font=f)[2]>max_width:
            while s and d.textbbox((0,0),s+'…',font=f)[2]>max_width:s=s[:-1]
            s+='…'
    d.text(xy,s,font=f,fill=color)


def _fit(path,sz,mode='cover'):
    with Image.open(path) as im:
        im=ImageOps.exif_transpose(im).convert('RGB')
        return (ImageOps.fit(im,sz,method=Image.Resampling.LANCZOS,centering=(.5,.45)) if mode=='cover'
                else ImageOps.contain(im,sz,Image.Resampling.LANCZOS))


def _circle_photo(canvas,path,x,y,s,accent):
    mask=Image.new('L',(s,s));draw=ImageDraw.Draw(mask)
    draw.ellipse((3,3,s-4,s-4),fill=255)
    tile=_fit(path,(s,s))
    canvas.paste(tile,(x,y),mask)
    ImageDraw.Draw(canvas).ellipse((x-3,y-3,x+s+2,y+s+2),outline=accent,width=4)


def _brand_color(info):
    value=str((info.get('creative_direction') or {}).get('accent') or FALLBACK)
    if not re.fullmatch(r'#[0-9A-Fa-f]{6}',value):return FALLBACK
    return value


def _bio(folder):
    p=folder/'02_perfil_express'/'bio_sugerida.txt'
    return p.read_text(encoding='utf-8-sig').strip() if p.exists() else ''


def _plain(text):
    # Fontes Pillow nao cobrem a maioria dos emojis; remove apenas pictogramas.
    # A bio ORIGINAL com emojis continua disponivel na galeria para copiar.
    text=''.join(c for c in str(text) if not (0x1F000<=ord(c)<=0x1FFFF or 0x2600<=ord(c)<=0x27BF))
    return ' '.join(text.split()).strip(' •|')


def _posts(folder):
    p=folder/'03_vitrine_digital';q=folder/'04_feed_premium'
    posts=sorted(p.glob('feed_*_1080x1350.jpg')) if p.is_dir() else []
    extras=sorted(q.glob('arte_extra_*_1080x1350.png')) if q.is_dir() else []
    # A grade apresenta em primeiro lugar o post mais recente (ultimo da campanha).
    return list(reversed(posts+extras))[:9]


def _profile_canvas(folder,info,cover_posts=True):
    w,h=1060,2230
    im=Image.new('RGB',(w,h),BG);d=ImageDraw.Draw(im)
    brand=str(info.get('brand') or 'Sua marca')[:55]
    inst=str(info.get('instagram') or '@suamarca')[:70]
    contact=str(info.get('contact') or '').strip()
    accent=_brand_color(info)
    _text(d,(62,43),inst,41,INK,True,805)
    d.line((35,112,1024,112),fill='#292D38',width=2)
    avatar=folder/'02_perfil_express'/'foto_de_perfil_1080.png'
    _circle_photo(im,avatar,70,154,205,accent)
    # Contadores intencionalmente nao inventados.
    for cx,lab in [(392,'publicações'),(642,'seguidores'),(874,'seguindo')]:
        _text(d,(cx,191),'—',38,INK,True)
        _text(d,(cx-18,242),lab,23,MUTED)
    _text(d,(68,388),brand,37,INK,True,895)
    activity=str(info.get('activity') or '')
    if activity:_text(d,(69,438),activity.capitalize(),25,MUTED,max_width=900)
    bio=_bio(folder)
    ypos=485
    for line in bio.splitlines()[:4]:
        clean=_plain(line)
        if not clean:continue
        _text(d,(70,ypos),clean,27,INK,max_width=905)
        ypos+=41
    if contact and ypos<710:
        _text(d,(70,ypos+5),'Contato: '+contact,23,'#C3C9D7',max_width=896)
        ypos+=43
    y_high=max(747,ypos+35)
    covers=sorted((folder/'02_perfil_express').glob('capa_destaque_*.png'))[:5]
    labels=list((info.get('creative_direction') or {}).get('highlights') or [])[:5]
    labels=(labels+['Produtos','Novidades','Sobre','Contato','Mais'])[:5]
    for i,cover in enumerate(covers):
        x=82+i*198
        _circle_photo(im,cover,x,y_high,115,accent)
        title=labels[i]
        bb=d.textbbox((0,0),title,font=_font(22))
        _text(d,(x+57-(bb[2]-bb[0])/2,y_high+130),title,22,'#DFE0E4',max_width=170)
    bar_y=y_high+210
    d.line((38,bar_y,1024,bar_y),fill='#303644',width=2)
    _text(d,(172,bar_y+19),'▦  PUBLICAÇÕES',25,INK,True)
    _text(d,(686,bar_y+19),'▹  REELS',25,MUTED)
    grid_y=bar_y+72; tile_w=326; tile_h=360; gap=5
    slots=_posts(folder)
    for idx,path in enumerate(slots):
        row,col=divmod(idx,3)
        x=36+col*(tile_w+gap);y=grid_y+row*(tile_h+gap)
        if y+tile_h>h-26:break
        tile=_fit(path,(tile_w,tile_h),'cover')
        im.paste(tile,(x,y))
    if not slots:
        d.rounded_rectangle((65,grid_y+25,1004,grid_y+320),radius=18,fill='#161A22',outline='#313743')
        _text(d,(125,grid_y+130),'Publicações ainda não incluídas neste plano',27,MUTED,max_width=810)
    return im


def _render_feed(folder, out):
    images=_posts(folder)
    if not images:return None
    W,H=1100,1350
    im=Image.new('RGB',(W,H),'#0A0B11');d=ImageDraw.Draw(im)
    _text(d,(57,45),'PRÉVIA DA GRADE',38,INK,True)
    _text(d,(57,102),'Ordem sugerida de publicação • simulação, não postagem real',20,MUTED)
    tile=337;gap=10;start=54
    for i,p in enumerate(images):
        r,c=divmod(i,3)
        im.paste(_fit(p,(tile,tile)),(start+c*(tile+gap),175+r*(tile+gap)))
    _text(d,(57,1261),'STAYVISION  /  ESTÚDIO DE PERFIL',25,'#A8A1AF',True)
    out.parent.mkdir(parents=True,exist_ok=True)
    im.save(out,optimize=True)
    return out


def _banner(folder,info,phone,out):
    W,H=2000,1250
    accent=_brand_color(info)
    im=Image.new('RGB',(W,H),'#0A0A0E');d=ImageDraw.Draw(im)
    # Suave iluminacao no fundo, coerente em nichos diferentes.
    glow=Image.new('RGBA',(W,H),(0,0,0,0));gd=ImageDraw.Draw(glow)
    gd.ellipse((800,-440,2450,1120),fill=(*tuple(bytes.fromhex(accent[1:])),26))
    glow=glow.filter(ImageFilter.GaussianBlur(130));im=Image.alpha_composite(im.convert('RGBA'),glow).convert('RGB');d=ImageDraw.Draw(im)
    # Apresentacao no smartphone
    d.rounded_rectangle((80,37,781,1220),radius=88,fill='#020406',outline='#434852',width=12)
    inner=phone.copy();inner.thumbnail((656,1125),Image.Resampling.LANCZOS)
    mask=Image.new('L',inner.size,0);md=ImageDraw.Draw(mask);md.rounded_rectangle((0,0,*[n-1 for n in inner.size]),radius=49,fill=255)
    im.paste(inner,(103,67),mask)
    d.rounded_rectangle((297,78,570,102),radius=19,fill='#000000')
    # Coluna direita: marca+produto real (nunca imagens inventadas).
    x=915
    _text(d,(x,112),'SEU INSTAGRAM, SUA IDENTIDADE',32,accent,True,1015)
    _text(d,(x,180),str(info.get('brand') or 'Sua marca'),94,INK,True,1010)
    d.line((x,317,1860,317),fill=accent,width=5)
    tagline=str((info.get('creative_direction') or {}).get('tagline') or 'Sua marca em destaque.')
    _text(d,(x,350),tagline,35,'#D4D1D8',max_width=950)
    hero=sorted((folder/'01_fotos_tratadas').glob('foto_profissional_*.jpg'))
    if not hero:
        hero=sorted((folder/'03_vitrine_digital').glob('feed_*.jpg'))
    if hero:
        panel=(925,442,1892,1020)
        d.rounded_rectangle(panel,radius=36,fill='#181A22',outline='#484047',width=2)
        photo=_fit(hero[min(4,len(hero)-1)],(916,528),'cover')
        pm=Image.new('L',(916,528),0);pd=ImageDraw.Draw(pm);pd.rounded_rectangle((0,0,915,527),radius=32,fill=255)
        im.paste(photo,(950,467),pm)
    _text(d,(920,1085),'PERFIL  ·  BIO  ·  DESTAQUES  ·  PUBLICAÇÕES',29,'#F3EEF2',True,980)
    _text(d,(920,1144),'Prévia ilustrativa da identidade e das artes entregues. Não é uma conta publicada.',21,MUTED,max_width=970)
    out.parent.mkdir(parents=True,exist_ok=True)
    im.save(out,optimize=True)
    return out


def create_previews(folder):
    """Gera previews locais; sem rede e sem alteracao de fotos, bios ou posts."""
    folder=Path(folder)
    info=json.loads((folder/'INFO_PEDIDO.json').read_text(encoding='utf-8'))
    if info.get('plan') not in ('perfil','vitrine','premium') or info.get('sample_only'):
        return []
    required=[folder/'02_perfil_express'/'foto_de_perfil_1080.png',folder/'02_perfil_express'/'bio_sugerida.txt']
    if not all(p.is_file() for p in required):raise ValueError('Faltam foto de perfil ou bio para montar a apresentação.')
    out=folder/'06_previas_instagram';out.mkdir(parents=True,exist_ok=True)
    phone=_profile_canvas(folder,info)
    f1=out/'perfil_completo_1080x1920.png'
    frame=Image.new('RGB',(1080,1920),'#0E1016')
    frame.paste(phone.resize((1030,1797),Image.Resampling.LANCZOS),(25,43))
    ImageDraw.Draw(frame).text((40,1862),'SIMULAÇÃO DE PERFIL  ·  NÃO PUBLICADO',font=_font(23,True),fill='#B2B7C5')
    frame.save(f1,optimize=True)
    created=[f1]
    if _posts(folder):
        p=_render_feed(folder,out/'grade_publicacoes_1080x1350.png')
        if p:created.append(p)
        created.append(_banner(folder,info,phone,out/'apresentacao_premium_2000x1250.png'))
    return created

if __name__=='__main__':
    import sys
    paths=create_previews(Path(sys.argv[1]))
    print('Prévias geradas sem APIs:',*[str(p) for p in paths],sep='\n')
