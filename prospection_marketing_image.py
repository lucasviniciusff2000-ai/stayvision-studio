"""Imagem pública de demonstração ANTES/DEPOIS para abordagens StayVision.
Usa somente material de portfólio já presente na implantação; não usa FAL nem APIs externas.
Uma composição ilustrativa não representa resultado entregue para uma empresa específica.
"""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parent
PHOTO = ROOT / "assets" / "hero_food_premium.webp"

def _font(size, bold=True):
    candidate = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for name in (candidate if bold else candidate[::-1]):
        try: return ImageFont.truetype(name,size)
        except (OSError,ValueError):pass
    return ImageFont.load_default()

def _crop(im, size):
    return ImageOps.fit(im,size,method=Image.Resampling.LANCZOS,centering=(0.5,0.5))

def _panel(canvas, source, xy, size, dull=False):
    image=_crop(source,size)
    if dull:
        image=ImageEnhance.Color(image).enhance(0.47)
        image=ImageEnhance.Contrast(image).enhance(0.67)
        image=ImageEnhance.Brightness(image).enhance(0.72)
        image=image.filter(ImageFilter.GaussianBlur(1.2))
    mask=Image.new("L",size,0)
    painter=ImageDraw.Draw(mask)
    painter.rounded_rectangle((0,0,size[0]-1,size[1]-1),radius=25,fill=255)
    canvas.paste(image,xy,mask)
    return

@lru_cache(maxsize=1)
def before_after_jpeg():
    with Image.open(PHOTO) as src:
        image=ImageOps.exif_transpose(src).convert("RGB")
    out=Image.new("RGB",(1200,675),(13,16,22))
    dr=ImageDraw.Draw(out)
    # Identidade escura / laranja StayVision Business
    dr.rounded_rectangle((29,24,1170,112),radius=19,fill=(29,34,44))
    dr.text((55,37),"STAYVISION",font=_font(38),fill=(255,255,255))
    dr.text((315,47),"BUSINESS",font=_font(24),fill=(255,146,52))
    dr.text((852,55),"COMPARATIVO VISUAL",font=_font(18),fill=(232,229,216))
    size=(548,410)
    _panel(out,image,(30,134),size,dull=True)
    _panel(out,image,(622,134),size,dull=False)
    dr.rounded_rectangle((45,151,195,209),radius=14,fill=(28,28,34))
    dr.rounded_rectangle((638,151,802,209),radius=14,fill=(241,142,34))
    dr.text((73,161),"ANTES",font=_font(27),fill=(255,255,255))
    dr.text((657,161),"DEPOIS",font=_font(27),fill=(24,19,16))
    dr.rounded_rectangle((550,314,651,369),radius=20,fill=(255,146,52))
    dr.text((578,319),">",font=_font(35),fill=(26,22,18))
    dr.rounded_rectangle((30,561,1170,651),radius=17,fill=(29,34,44))
    dr.text((50,575),"Fotos que valorizam seus produtos",font=_font(28),fill=(255,255,255))
    dr.text((51,614),"SIMULAÇÃO ILUSTRATIVA • A diferença acima é apenas uma demonstração visual.",font=_font(14,bold=False),fill=(194,199,208))
    b=BytesIO()
    out.save(b,format="JPEG",quality=84,optimize=True,progressive=True)
    return b.getvalue()
