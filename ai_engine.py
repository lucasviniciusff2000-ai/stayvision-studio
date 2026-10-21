"""StayVision Studio rendering engine.

Runs completely offline: photography-aware, deterministic image enhancement and
cinematic real-estate video creation. Spatial mode is intentionally labelled a
2.5D visual approximation, not a genuine room reconstruction.

No payments, customer delivery or network APIs are invoked here.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 55_000_000
MAX_IMAGES = 12
STYLES = ('natural', 'claro', 'premium')
MODES = ('photo', 'video', 'spatial', 'complete')
ASPECTS = ('horizontal', 'vertical')

class AIEngineError(Exception):
    pass


def _mean_luma(image: Image.Image) -> float:
    return ImageStat.Stat(image.convert('L').resize((128, 128))).mean[0]


def enhance_image(source: Path, destination: Path, style: str = 'natural') -> dict:
    """Photo Engine V3: architecture-preserving adaptive computational restoration."""
    from photo_engine_v3 import enhance_photo_v3, PhotoEngineError
    try:
        return enhance_photo_v3(source, destination, style=style,
                                auto_level=os.getenv('STAYVISION_PHOTO_AUTO_LEVEL', '0') == '1')
    except PhotoEngineError as exc:
        raise AIEngineError(str(exc)) from exc


def render_video(image_files: list[Path], destination: Path, spatial: bool = False, aspect: str = 'horizontal',
                 on_progress: Callable[[int, str], None] | None = None,
                 progress_start: int = 68, progress_end: int = 97) -> dict:
    """Video Engine V3: stable subpixel affine, easing and smooth crossfades.

    Uses OpenCV + FFmpeg; does NOT fabricate new 3D views of the property.
    """
    from video_engine_v3 import render_steady_video, SteadyVideoError
    try:
        return render_steady_video(
            image_files, destination, spatial=spatial, aspect=aspect,
            motion=os.getenv('STAYVISION_VIDEO_MOTION', 'gentle').strip().lower(),
            quality=os.getenv('STAYVISION_VIDEO_QUALITY', 'auto').strip().lower(),
            on_progress=on_progress, progress_start=progress_start, progress_end=progress_end)
    except SteadyVideoError as exc:
        raise AIEngineError(str(exc)) from exc


def _make_contact_sheet(inputs: list[Path], processed: list[Path], output: Path) -> None:
    """Review-friendly side-by-side contact sheet. Input files remain unchanged."""
    from PIL import ImageDraw, ImageFont
    cards=[]
    max_pairs=min(6,len(inputs))
    for original,enhanced in zip(inputs[:max_pairs],processed[:max_pairs]):
        with Image.open(original) as left, Image.open(enhanced) as right:
            a=ImageOps.exif_transpose(left).convert('RGB')
            b=ImageOps.exif_transpose(right).convert('RGB')
            size=(640,400)
            def fit(photo):
                canvas=Image.new('RGB',size,(247,248,245))
                photo.thumbnail(size,Image.Resampling.LANCZOS)
                canvas.paste(photo,((size[0]-photo.width)//2,(size[1]-photo.height)//2))
                return canvas
            card=Image.new('RGB',(1280,432),'white')
            card.paste(fit(a),(0,32));card.paste(fit(b),(640,32))
            draw=ImageDraw.Draw(card)
            draw.text((14,10),'ORIGINAL  •  antes',fill=(35,50,39))
            draw.text((654,10),'STAYVISION V3  •  depois',fill=(35,50,39))
            cards.append(card)
    if not cards:return
    sheet=Image.new('RGB',(1280,432*len(cards)),(255,255,255))
    for i,card in enumerate(cards):sheet.paste(card,(0,432*i))
    output.parent.mkdir(parents=True,exist_ok=True)
    sheet.save(output,format='JPEG',quality=91,subsampling=0,optimize=True)


def run_pipeline(image_paths: list[Path], output_dir: Path, mode: str='photo', style: str='natural', aspect: str='horizontal',
                 on_progress: Callable[[int,str],None]|None=None) -> dict:
    if mode not in MODES: raise AIEngineError('Modo inválido.')
    if style not in STYLES: raise AIEngineError('Estilo inválido.')
    if aspect not in ASPECTS: raise AIEngineError('Formato de vídeo inválido.')
    if not image_paths or len(image_paths)>MAX_IMAGES:
        raise AIEngineError('Envie entre 1 e 12 fotografias para o pedido.')
    if any(not p.is_file() or p.suffix.lower() not in ('.jpg','.jpeg','.png','.webp') for p in image_paths):
        raise AIEngineError('Há fotos ausentes ou em formato incompatível.')
    output_dir.mkdir(parents=True,exist_ok=True)
    photos_dir=output_dir/'photos'
    photos_dir.mkdir(exist_ok=True)
    processed=[]; photos=[]
    for ix,source in enumerate(image_paths):
        dest=photos_dir/f'{ix+1:02d}_stayvision.jpg'
        photos.append(enhance_image(source,dest,style))
        processed.append(dest)
        if on_progress: on_progress(int(5 + (ix+1)/len(image_paths)*60),f'Foto {ix+1} de {len(image_paths)} tratada')
    bundle=output_dir/'Fotos_StayVision.zip'
    with zipfile.ZipFile(bundle,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        for image in processed: z.write(image,arcname='fotos/'+image.name)
    artifacts=[{'name':bundle.name,'label':'Fotos tratadas (ZIP)','type':'photos','size_bytes':bundle.stat().st_size}]
    contact=output_dir/'Comparativo_StayVision_V3.jpg'
    _make_contact_sheet(image_paths,processed,contact)
    artifacts.append({'name':contact.name,'label':'Comparação original × tratada (até 6 fotos)','type':'review','size_bytes':contact.stat().st_size})
    report=output_dir/'Relatorio_Qualidade_V3.json'
    report.write_text(json.dumps({'engine':'V3','photos':photos,'notice':'Indicadores automatizados não comprovam qualidade comercial; revise visualmente.'},ensure_ascii=False,indent=2),encoding='utf-8')
    artifacts.append({'name':report.name,'label':'Relatório de qualidade e limitações (JSON)','type':'qa','size_bytes':report.stat().st_size})
    manifest={'engine_version':'stayvision-photo-v3.0-video-v3.0','mode':mode,'style':style,
              'photos':photos,'artifacts':artifacts,'aspect':aspect,
              'integrity':'Edição computacional preservadora da realidade; não inventa paredes, móveis, água, vegetação ou detalhes ausentes.',
              'tour_3d':'não disponível; módulo de reconstrução real reservado para futura integração'}
    if mode in ('video','spatial','complete'):
        do_video = mode in ('video','complete')
        do_spatial = mode in ('spatial','complete')
        if on_progress: on_progress(68,'Preparando cenas de vídeo')
        if do_video:
            dest=output_dir/'Video_StayVision.mp4'
            video=render_video(processed,dest,spatial=False,aspect=aspect,on_progress=on_progress,progress_start=68,progress_end=82 if do_spatial else 96)
            artifacts.append({'name':dest.name,'label':'Vídeo estável V3 · MP4','type':'video',**video})
        if do_spatial:
            dest=output_dir/'Visual_Espacial_Experimental.mp4'
            video=render_video(processed,dest,spatial=True,aspect=aspect,on_progress=on_progress,progress_start=82 if do_video else 68,progress_end=97)
            artifacts.append({'name':dest.name,'label':'Visual espacial ilustrativo (não é tour 3D)','type':'spatial',**video})
    manifest_file=output_dir/'projeto_3d_futuro.json'
    manifest_file.write_text(json.dumps({
      'status':'future_true_3d', 'scene_count':len(photos),'source_images':[p['file'] for p in photos],
      'requirements':['fotografias sobrepostas/visões de vários ângulos','calibração de câmera e escala',
                      'estimativa de profundidade testada','geometria 3D coerente','revisão visual humana'],
      'disclaimer':'Não existe tour 3D real neste pacote; não representar como navegação por ambientes.'
    },ensure_ascii=False,indent=2),encoding='utf-8')
    artifacts.append({'name':manifest_file.name,'label':'Preparação técnica do futuro 3D (JSON)','type':'manifest','size_bytes':manifest_file.stat().st_size})
    # One delivery file suitable for the existing order's 'Entregar arquivo final' form.
    if mode != 'photo':
        full=output_dir/'Pacote_StayVision_Final.zip'
        with zipfile.ZipFile(full,'w',compression=zipfile.ZIP_STORED) as archive:
            for image in processed:
                archive.write(image,arcname='fotos/'+image.name)
            for entry in artifacts:
                if entry['type'] in ('video','spatial'):
                    archive.write(output_dir/entry['name'],arcname='videos/'+entry['name'])
            archive.write(manifest_file,arcname=manifest_file.name)
        artifacts.insert(0,{'name':full.name,'label':'Pacote final: fotos + vídeos (ZIP)',
                            'type':'complete','size_bytes':full.stat().st_size})
    manifest['artifacts']=artifacts
    (output_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    if on_progress: on_progress(100,'Arquivos produzidos. Revise antes de entregar.')
    return manifest
