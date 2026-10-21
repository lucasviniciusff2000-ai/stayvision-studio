"""StayVision Photo Engine 2 — non-generative, architecture-preserving processing.

No network calls, no invented furnishings, no fabricated spatial detail. Neural
super-resolution is deliberately NOT claimed: missing pixels cannot be recovered
reliably by classical techniques. Original uploads remain untouched.
"""
from __future__ import annotations

from pathlib import Path
import math
import os
import cv2
import numpy as np
from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 55_000_000
STYLE_PARAMS = {
    'natural': {'shadow': .105, 'local': .16, 'chroma': 1.01, 'sharpen': .37},
    'claro': {'shadow': .175, 'local': .21, 'chroma': 1.01, 'sharpen': .40},
    'premium': {'shadow': .13, 'local': .20, 'chroma': 1.045, 'sharpen': .43},
}

class PhotoEngineError(ValueError):
    pass


def _read_rgb(source: Path):
    try:
        with Image.open(source) as f:
            f = ImageOps.exif_transpose(f)
            if f.width < 250 or f.height < 250:
                raise PhotoEngineError('A imagem é pequena demais para um anúncio imobiliário.')
            if f.width * f.height > 38_000_000:
                raise PhotoEngineError('Imagem excede o limite de 38 megapixels para processamento.')
            return np.asarray(f.convert('RGB'), dtype=np.uint8).copy()
    except (OSError, UnidentifiedImageError, ValueError) as e:
        if isinstance(e, PhotoEngineError): raise
        raise PhotoEngineError('Imagem recebida inválida ou corrompida.') from e


def _quality_metrics(rgb):
    h,w = rgb.shape[:2]
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    sampled=cv2.resize(gray,(min(w,900),min(h,900)),interpolation=cv2.INTER_AREA) if max(w,h)>900 else gray
    sharp=float(cv2.Laplacian(sampled,cv2.CV_32F).var())
    luma=float(np.mean(sampled))
    return {'largura':int(w),'altura':int(h),'luminancia_media':round(luma,1),
            'indice_nitidez_relativo':round(sharp,1),
            'aviso_resolucao':('Imagem de origem pequena: o tratamento não recupera detalhes que não foram capturados.'
                              if min(w,h)<900 else None)}


def _estimate_noise(y):
    # Noise estimation in nearly flat patches to avoid mistaking bricks/text for noise.
    thumb=cv2.resize(y,(min(y.shape[1],720),min(y.shape[0],720)),interpolation=cv2.INTER_AREA) if max(y.shape)>720 else y
    small=cv2.GaussianBlur(thumb,(3,3),0)
    residual=np.abs(thumb.astype(np.float32)-small.astype(np.float32))
    grad=cv2.Laplacian(small,cv2.CV_32F,ksize=3)
    flat=residual[np.abs(grad)<10]
    if len(flat)<150: flat=residual.reshape(-1)
    return float(np.percentile(flat,65))


def _neutral_white_balance(rgb):
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    y=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    mask=(hsv[:,:,1] < 55) & (y>60) & (y<225)
    if mask.mean() < .035: return rgb
    samples=rgb[mask].astype(np.float32)
    means=samples.mean(axis=0)
    if np.min(means)<20:return rgb
    target=float(np.mean(means))
    gain=np.clip(target/means,.955,1.045)
    if np.max(gain)-np.min(gain)<.008:return rgb
    return np.clip(rgb.astype(np.float32)*gain.reshape(1,1,3),0,255).astype('uint8')


def _denoise_rgb(rgb, noise):
    if noise < 1.3: return rgb,False
    # Deliberately mild; aggressive smoothing destroys tiles and fabric textures.
    h=float(np.clip(1.0+0.55*noise, 2.1,4.4))
    bgr=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
    out=cv2.fastNlMeansDenoisingColored(bgr,None,h,h*0.80,7,21)
    return cv2.cvtColor(out,cv2.COLOR_BGR2RGB),True


def _tone_luma(rgb,p):
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)
    l=lab[:,:,0]
    clahe=cv2.createCLAHE(clipLimit=1.5,tileGridSize=(8,8)).apply(l)
    # Texture-aware local tone: coarse illumination changes, no exaggerated halos.
    base=cv2.addWeighted(l,1.0-p['local'],clahe,p['local'],0)
    x=base.astype(np.float32)/255.0
    shadows=p['shadow'] * (1-x)**2 * np.sqrt(np.clip(x,0,1))
    highlights=.010 * np.maximum(x-.88,0)/.12
    mapped=np.clip((x+shadows-highlights)*255.0,0,255).astype('uint8')
    lab[:,:,0]=mapped
    return cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)


def _saturation(rgb,factor):
    if abs(factor-1)<1e-4: return rgb
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    sat=hsv[:,:,1].astype(np.float32)
    hsv[:,:,1]=np.clip(sat*factor,0,255).astype('uint8')
    return cv2.cvtColor(hsv,cv2.COLOR_HSV2RGB)


def _edge_sharpness(rgb,amount):
    # Work in YCrCb: edges of walls remain straight; chroma noise is not sharpened.
    ycc=cv2.cvtColor(rgb,cv2.COLOR_RGB2YCrCb)
    y=ycc[:,:,0].astype(np.float32)
    blurred=cv2.GaussianBlur(y,(0,0),.85)
    detail=y-blurred
    # Ignore tiny fluctuations (=noise) and avoid overshoot around strong edges.
    alpha=np.clip((np.abs(detail)-1.3)/5.5,0,1)
    out=np.clip(y+amount*alpha*np.clip(detail,-23,23),0,255)
    ycc[:,:,0]=out.astype(np.uint8)
    return cv2.cvtColor(ycc,cv2.COLOR_YCrCb2RGB)


def _detect_tilt(rgb):
    """Optional minimal automatic horizon levelling; only rotate on high confidence."""
    h,w=rgb.shape[:2]
    scale=min(1.0,1000/max(h,w))
    small=cv2.resize(rgb,(max(2,int(w*scale)),max(2,int(h*scale)))) if scale<1 else rgb
    gray=cv2.cvtColor(small,cv2.COLOR_RGB2GRAY)
    edges=cv2.Canny(gray,55,135)
    lines=cv2.HoughLinesP(edges,1,np.pi/1800,threshold=65,minLineLength=max(60,int(min(gray.shape)*.22)),maxLineGap=12)
    if lines is None:return 0.0
    angles=[];weights=[]
    for x1,y1,x2,y2 in lines[:,0]:
        dx=float(x2-x1);dy=float(y2-y1)
        angle=math.degrees(math.atan2(dy,dx))
        # Horizontal & vertical architectural lines should agree on their tilt.
        dist_h=((angle+90)%180)-90
        deviation=dist_h if abs(dist_h)<=12 else (dist_h-90 if dist_h>0 else dist_h+90)
        if abs(deviation)>4:continue
        length=math.hypot(dx,dy)
        if length>40:angles.append(deviation);weights.append(length)
    if len(angles)<6:return 0.0
    tilt=float(np.median(angles))
    consistency=float(np.mean(np.abs(np.asarray(angles)-tilt)<.8))
    if not (.6<=abs(tilt)<=2.0 and consistency>=.75): return 0.0
    return tilt


def _level(rgb,tilt):
    if abs(tilt)<.01:return rgb
    h,w=rgb.shape[:2]
    # Preserve dimensions; reflect borders so no fabricated white margins.
    mat=cv2.getRotationMatrix2D(((w-1)/2,(h-1)/2),tilt,1.0)
    return cv2.warpAffine(rgb,mat,(w,h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REFLECT_101)


def _optional_neural_superres(rgb: np.ndarray):
    """Real neural x2 upscaling if an operator supplies a compatible FSRCNN model.

    Disabled by default. Without a trained model we never label interpolation
    as artificial-intelligence super-resolution. This path needs opencv-contrib.
    """
    path = os.getenv('STAYVISION_PHOTO_SUPERRES_MODEL', '').strip()
    if not path: return rgb, 'não aplicada (sem modelo pré-treinado configurado)'
    model = Path(path)
    if not model.is_file() or model.suffix.lower() != '.pb':
        raise PhotoEngineError('Modelo neural configurado não foi encontrado no servidor.')
    if not hasattr(cv2, 'dnn_superres'):
        raise PhotoEngineError('O OpenCV instalado não inclui suporte à super-resolução neural.')
    h, w = rgb.shape[:2]
    if w*h > 1_800_000:
        return rgb, 'não aplicada (foto já grande; protegendo memória do servidor)'
    sr=cv2.dnn_superres.DnnSuperResImpl_create()
    try:
        sr.readModel(str(model))
        sr.setModel('fsrcnn', 2)
        up=sr.upsample(cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
        out=cv2.cvtColor(up,cv2.COLOR_BGR2RGB)
    except cv2.error as e:
        raise PhotoEngineError('Modelo de super-resolução incompatível ou corrompido.') from e
    return out, 'FSRCNN x2 (rede neural pré-treinada; pode criar artefatos e precisa de revisão)'


def enhance_photo_v2(source: Path, destination: Path, style: str='natural', auto_level: bool=False)->dict:
    if style not in STYLE_PARAMS:raise PhotoEngineError('Estilo de tratamento inválido.')
    rgb=_read_rgb(Path(source))
    original=_quality_metrics(rgb)
    # User receives a warning for low-res files rather than fabricated pixels.
    # Downscale huge files to cap memory/CPU on the Railway trial.
    h,w=rgb.shape[:2]
    if max(h,w)>3400:
        factor=3400/max(h,w)
        rgb=cv2.resize(rgb,(round(w*factor),round(h*factor)),interpolation=cv2.INTER_AREA)
    p=STYLE_PARAMS[style]
    before=_quality_metrics(rgb)
    noise=_estimate_noise(cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY))
    rgb,_=_denoise_rgb(rgb,noise)
    rgb=_neutral_white_balance(rgb)
    tilt=_detect_tilt(rgb) if auto_level else 0.0
    if tilt: rgb=_level(rgb,tilt)
    rgb=_tone_luma(rgb,p)
    rgb=_saturation(rgb,p['chroma'])
    rgb=_edge_sharpness(rgb,p['sharpen'])
    rgb, superres=_optional_neural_superres(rgb)
    out=Image.fromarray(rgb,'RGB')
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    out.save(destination,format='JPEG',quality=95,subsampling=0,optimize=True)
    return {'file':destination.name,'size':[out.width,out.height],
            'original_size':[original['largura'],original['altura']], 'style':style,
            'method':'Photo Engine V2: redução de ruído, sombras localizadas, balanço neutro e nitidez controlada (sem IA generativa)',
            'source_quality':original,'output_quality':_quality_metrics(rgb),
            'noise_index':round(noise,2),'auto_level_degrees':round(tilt,2),
            'super_resolution':superres,
            'quality_notice':original.get('aviso_resolucao')}
