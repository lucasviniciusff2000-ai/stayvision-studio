"""Recebe fotos em proporções variadas e normaliza com segurança, sem chamadas a APIs.
Suporta JPG, PNG, WebP, GIF, BMP, TIFF e, quando pillow-heif presente, HEIC/HEIF/AVIF.
NUNCA tenta abrir dados não-imagem, nem promete qualidade inexistente.
"""
from __future__ import annotations
import base64, io, re, warnings
from pathlib import Path
from PIL import Image, ImageOps, ImageFilter, ImageFile, UnidentifiedImageError

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    if hasattr(pillow_heif,"register_avif_opener"):
        pillow_heif.register_avif_opener()
except ImportError:
    pass

# Impede descompressão abusiva; fotos muito grandes precisam ser comprimidas no navegador.
Image.MAX_IMAGE_PIXELS=80_000_000
FORMATS={'JPEG','PNG','WEBP','GIF','BMP','TIFF','HEIF','AVIF'}
MIME=re.compile(r'^data:image/(jpeg|jpg|png|webp|gif|bmp|x-ms-bmp|tiff|heic|heif|avif);base64,([A-Za-z0-9+/=]+)$',re.I)
MAX_BYTES=26_000_000
MAX_PIXELS=80_000_000


def open_photo(raw:bytes,*,max_side=2400,logo=False):
    """Mantém proporção e orientação EXIF; alpha vira fundo neutro para JPEG."""
    if not isinstance(raw,bytes) or not raw or len(raw)>MAX_BYTES:
        raise ValueError('Foto acima de 26 MB. Compacte o arquivo antes de enviar.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as src:
                if src.format not in FORMATS:
                    raise ValueError('Arquivo não é uma foto compatível (JPG, PNG, WebP, HEIC, TIFF, BMP ou GIF).')
                w,h=src.size
                if min(w,h)<1 or w*h>MAX_PIXELS:
                    raise ValueError('Foto extremamente grande. Reduza-a antes de enviar (até 80 megapixels).')
                # Primeiro quadro para GIF animado; não executamos animações.
                src.seek(0)
                im=ImageOps.exif_transpose(src).copy()
        if im.mode in ('RGBA','LA') or 'transparency' in im.info:
            im=im.convert('RGBA')
            bg=Image.new('RGBA',im.size, '#FFFFFF' if logo else '#F5F5F5')
            bg.alpha_composite(im)
            im=bg.convert('RGB')
        else:
            im=im.convert('RGB')
        if max(im.size)>max_side:
            im.thumbnail((max_side,max_side),Image.Resampling.LANCZOS)
        return im
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as ex:
        raise ValueError('Não foi possível abrir a foto. Confira o arquivo ou exporte como JPG/PNG.') from ex


def from_data_url(value,*,max_side=2400,logo=False):
    if not isinstance(value,str):raise ValueError('Imagem ausente ou inválida.')
    m=MIME.fullmatch(value)
    if not m:raise ValueError('Formato de imagem não reconhecido. Use JPG, PNG, WebP ou HEIC.')
    # Limite antes da decodificação.
    if len(m.group(2))>4*(MAX_BYTES//3+2):raise ValueError('Imagem acima de 26 MB.')
    try:raw=base64.b64decode(m.group(2),validate=True)
    except ValueError as ex:raise ValueError('Dados de imagem inválidos.') from ex
    return open_photo(raw,max_side=max_side,logo=logo)


def to_jpeg(im,path,quality=91):
    dest=Path(path); dest.parent.mkdir(parents=True,exist_ok=True)
    im.save(dest,'JPEG',quality=quality,optimize=True,subsampling=0)
    return dest


def smart_fit(im,size,*,mode='photo',upscale=True):
    """Garante dimensões exatas sem crop de informação importante.
    Em fotos com proporção diferente cria fundo desfocado; logos usam fundo liso.
    """
    target_w,target_h=map(int,size)
    if target_w<=0 or target_h<=0:raise ValueError('Destino inválido.')
    im=ImageOps.exif_transpose(im).convert('RGB')
    # Quase mesma proporção -> transformação simples sem cortes visíveis.
    if abs(im.width/im.height-target_w/target_h)/(target_w/target_h)<0.012:
        return im.resize((target_w,target_h),Image.Resampling.LANCZOS)
    if mode=='logo':
        canvas=Image.new('RGB',size,'#F7F7F7')
    else:
        canvas=ImageOps.fit(im,size,Image.Resampling.BILINEAR,centering=(.5,.5)).filter(ImageFilter.GaussianBlur(max(12,min(size)//32)))
        canvas=Image.blend(canvas,Image.new('RGB',size,'#343434'),.14)
    foreground=im.copy()
    # Margem de segurança; impedir corte de texto, cabeças, objetos e logotipos.
    factor=.86 if mode=='logo' else .94
    allowed=(max(1,int(target_w*factor)),max(1,int(target_h*factor)))
    foreground.thumbnail(allowed,Image.Resampling.LANCZOS)
    if upscale and (foreground.width<allowed[0] and foreground.height<allowed[1]):
        scale=min(allowed[0]/foreground.width,allowed[1]/foreground.height)
        if scale>1:foreground=foreground.resize((max(1,int(foreground.width*scale)),max(1,int(foreground.height*scale))),Image.Resampling.LANCZOS)
    canvas.paste(foreground,((target_w-foreground.width)//2,(target_h-foreground.height)//2))
    return canvas
