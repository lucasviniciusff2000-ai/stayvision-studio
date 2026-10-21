"""StayVision Photo Engine V3 — fidelity-first property photography.

Deterministic, offline computational imaging. Deliberately does NOT erase objects,
rebuild scenery, invent architectural detail or pretend interpolated pixels are neural AI.
User originals are never modified. Optional genuine neural x2 FSRCNN support is opt-in.
"""
from __future__ import annotations
from pathlib import Path
import math
import numpy as np
import cv2
from PIL import Image
from photo_engine_v2 import (
    PhotoEngineError, _read_rgb, _quality_metrics, _estimate_noise,
    _neutral_white_balance, _denoise_rgb, _detect_tilt, _level,
    _optional_neural_superres,
)

STYLES = {
    'natural': dict(lift=.29,local=.11,sharp=.35,saturation=1.00),
    'claro': dict(lift=.39,local=.13,sharp=.37,saturation=1.00),
    'premium': dict(lift=.32,local=.14,sharp=.39,saturation=1.018),
}


def _scene_metrics(rgb: np.ndarray) -> dict:
    """Quality reports must not be marketed as a learned/semantic scene classifier."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h,w=gray.shape
    top=hsv[:max(1,int(h*.55))]
    sky = (top[:,:,0]>=88)&(top[:,:,0]<=133)&(top[:,:,1]>=40)&(top[:,:,2]>=110)
    bottom=hsv[int(h*.43):]
    water = (bottom[:,:,0]>=84)&(bottom[:,:,0]<=110)&(bottom[:,:,1]>=65)
    green = (hsv[:,:,0]>=34)&(hsv[:,:,0]<=90)&(hsv[:,:,1]>30)
    dark = float(np.mean(gray<80))
    bright = float(np.mean(gray>235))
    return {'frac_sombras':round(dark,3), 'frac_luzes_fortes':round(bright,3),
            'indicador_azul_ceus':round(float(np.mean(sky)),3),
            'indicador_azul_agua':round(float(np.mean(water)),3),
            'indicador_vegetacao':round(float(np.mean(green)),3),
            'luminosidade_p50':int(np.median(gray))}


def _adaptive_luminance(rgb: np.ndarray, params: dict) -> np.ndarray:
    """Recover VISIBILITY in shadow regions while shielding bright sky/windows.

    Works only on LAB L; does not synthesize texture hidden in clipped shadows.
    Spatial illumination base is calculated at reduced resolution to bound memory.
    """
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    L=lab[:,:,0].astype(np.float32)/255.0
    height,width=L.shape
    base_width=min(512,width)
    base_height=max(1,round(height*base_width/width))
    thumbnail=cv2.resize(L,(base_width,base_height),interpolation=cv2.INTER_AREA)
    smooth=cv2.GaussianBlur(thumbnail,(0,0),sigmaX=21,sigmaY=21)
    illumination=cv2.resize(smooth,(width,height),interpolation=cv2.INTER_LINEAR)
    # Local weight preferentially lifts dark STRUCTURES and does not brighten the sky.
    local_mask=np.clip((.57-illumination)/.43,0,1)
    local_mask=cv2.GaussianBlur(local_mask,(0,0),sigmaX=2.0)
    shadow=np.clip((.73-L)/.73,0,1)
    local_gain = params['lift']*(.50 + .50*local_mask)
    # At low L, avoid driving black/noisy pixels into flat gray.
    lift=local_gain*shadow**1.18*np.sqrt(np.maximum(L,.03))
    L2=np.clip(L+lift,0,1)
    # Gentle brightness-dependent local contrast without double halos.
    clahe=cv2.createCLAHE(clipLimit=1.32,tileGridSize=(9,9)).apply((L2*255).astype(np.uint8))
    clahe=clahe.astype(np.float32)/255.0
    darks=np.clip((.70-L2)*2.0,0,1)
    L2=np.clip(L2+params['local']*darks*(clahe-L2),0,1)
    # Protect already-bright highlights instead of pretending clipped skies can recover.
    L2=np.where(L>.90,np.minimum(L2,L+.012),L2)
    lab[:,:,0]=np.clip(L2*255,0,255).astype(np.uint8)
    return cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)


def _tame_oversaturation(rgb: np.ndarray, original_rgb: np.ndarray, params:dict) -> np.ndarray:
    """Softly reduce oversaturated cyan/blue; avoid aggressive HDR-looking pools/sky."""
    hsv = cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    h,s,v=cv2.split(hsv)
    sat=s.astype(np.float32)
    hue=h.astype(np.int16)
    original_hsv=cv2.cvtColor(original_rgb,cv2.COLOR_RGB2HSV)
    # Saturated blue & cyan are commonly overdriven by camera HDR processing.
    blue = ((hue>=83)&(hue<=133)).astype(np.float32)
    oversat=np.clip((sat-135.0)/110.0,0,1)
    reduction=1.0-.16*blue*oversat
    # Neutral colors remain neutral; green grass is not repainted or synthesized.
    corrected=np.clip(sat*reduction*params['saturation'],0,255)
    # Dynamic clamp on changes to color saturation, particularly on already vibrant pools.
    origin_sat=original_hsv[:,:,1].astype(np.float32)
    corrected=np.minimum(corrected,np.maximum(origin_sat*1.08,origin_sat+10))
    hsv[:,:,1]=corrected.astype(np.uint8)
    return cv2.cvtColor(hsv,cv2.COLOR_HSV2RGB)


def _edge_preserving_sharp(rgb: np.ndarray, strength:float,noise_index:float) -> np.ndarray:
    ycc=cv2.cvtColor(rgb,cv2.COLOR_RGB2YCrCb)
    L=ycc[:,:,0].astype(np.float32)
    blurred=cv2.GaussianBlur(L,(0,0),sigmaX=.86)
    residual=L-blurred
    floor=1.8+float(np.clip(noise_index*.32,0,2.8))
    mask=np.clip((np.abs(residual)-floor)/7,0,1)
    # Avoid shiny white outlines around high-contrast tiles/tree branches.
    edge=np.clip(residual,-15,15)
    ycc[:,:,0]=np.clip(L+strength*mask*edge,0,255).astype(np.uint8)
    return cv2.cvtColor(ycc,cv2.COLOR_YCrCb2RGB)


def _guarded_result(original:np.ndarray, edited:np.ndarray) -> tuple[np.ndarray,dict]:
    """Conservative color deviation guard; outputs diagnostic rather than invented quality score."""
    inp=cv2.cvtColor(original,cv2.COLOR_RGB2LAB).astype(np.float32)
    out=cv2.cvtColor(edited,cv2.COLOR_RGB2LAB).astype(np.float32)
    chroma_shift=float(np.mean(np.sqrt(np.sum((out[:,:,1:]-inp[:,:,1:])**2,axis=2))))
    brightness_shift=float(np.mean(out[:,:,0]-inp[:,:,0]))
    # Large cast changes are not trustworthy without an actual neutral target.
    mixed=False
    if chroma_shift>12:
        blend=.60
        edited=cv2.addWeighted(edited,blend,original,1-blend,0)
        mixed=True
    quality={'desvio_medio_cor_lab':round(chroma_shift,2),
             'alteracao_media_luminosidade_lab':round(brightness_shift,2),
             'protecao_cores_acionada':mixed}
    return edited,quality


def _quality_notice(image:np.ndarray,noise:float)->str|None:
    h,w=image.shape[:2]
    gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY)
    issues=[]
    if min(h,w)<900:
        issues.append('Resolução pequena: detalhes ausentes não podem ser recuperados com garantia.')
    if float(np.mean(gray<45))>.28:
        issues.append('Sombras muito escuras; recuperar luz pode revelar ruído, não detalhes.')
    if float(np.mean(gray>247))>.12:
        issues.append('Áreas brancas sem informação não podem ter textura reconstruída fielmente.')
    if noise>5.5:
        issues.append('Ruído/artefatos detectados; conferir texturas antes de entregar.')
    return ' '.join(issues) if issues else None


def enhance_photo_v3(source:Path,destination:Path,style:str='natural',auto_level:bool=False)->dict:
    if style not in STYLES:
        raise PhotoEngineError('Estilo inválido.')
    original = _read_rgb(Path(source))
    original_metrics=_quality_metrics(original)
    scene_before=_scene_metrics(original)
    initial_h,initial_w=original.shape[:2]
    # 14 MP upper bound, preserving original files untouched and preventing OOM on small hosts.
    if max(initial_w,initial_h)>3400:
        factor=3400/max(initial_w,initial_h)
        rgb=cv2.resize(original,(round(initial_w*factor),round(initial_h*factor)),interpolation=cv2.INTER_AREA)
    else:
        rgb=original.copy()
    metrics_before=_scene_metrics(rgb)
    noise=_estimate_noise(cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY))
    params=STYLES[style]
    # Denoise must be restrained: water, tiles, roofs and trees carry fine detail.
    if noise>2.15:
        rgb,denoised=_denoise_rgb(rgb,min(noise,5.8))
    else:denoised=False
    whitebalanced=_neutral_white_balance(rgb)
    # Suppress white-balance changes on wildly blue scenes when no neutral gray is reliable.
    rgb=cv2.addWeighted(whitebalanced,.86,rgb,.14,0)
    tilt=_detect_tilt(rgb) if auto_level else 0.0
    if tilt:rgb=_level(rgb,tilt)
    base_for_color=rgb.copy()
    rgb=_adaptive_luminance(rgb,params)
    rgb=_tame_oversaturation(rgb,base_for_color,params)
    rgb=_edge_preserving_sharp(rgb,params['sharp'],noise)
    rgb,quality_guard=_guarded_result(base_for_color,rgb)
    rgb,superres=_optional_neural_superres(rgb)
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    Image.fromarray(rgb).save(destination,format='JPEG',quality=94,subsampling=0,optimize=True)
    notice=_quality_notice(original,noise)
    result={
        'file':destination.name,'size':[rgb.shape[1],rgb.shape[0]],
        'original_size':[initial_w,initial_h], 'style':style,
        'method':'StayVision Photo V3: equilíbrio de luz por regiões, cor contida, ruído e detalhes; preserva a arquitetura (não generativo)',
        'source_quality':original_metrics,'output_quality':_quality_metrics(rgb),
        'scene_indicators_before':scene_before,'scene_indicators_processed':metrics_before,
        'quality_guard':quality_guard,'noise_index':round(noise,2),
        'auto_level_degrees':round(tilt,2),'super_resolution':superres,
        'denoise_applied':denoised,'quality_notice':notice,
    }
    return result
