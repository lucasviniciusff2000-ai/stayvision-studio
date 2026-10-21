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
    """Photo Engine V2: architecture-preserving computational photo restoration."""
    from photo_engine_v2 import enhance_photo_v2, PhotoEngineError
    try:
        return enhance_photo_v2(source, destination, style=style,
                                auto_level=os.getenv('STAYVISION_PHOTO_AUTO_LEVEL', '0') == '1')
    except PhotoEngineError as exc:
        raise AIEngineError(str(exc)) from exc


def _scene_frame(source: Path, dest: Path, size: tuple[int,int], spatial: bool) -> None:
    """Fit full room photo on a soft-fill backdrop; no stretched/cropped geometry."""
    with Image.open(source) as im:
        original = ImageOps.exif_transpose(im).convert('RGB')
    w,h = size
    fill = ImageOps.fit(original,(w,h),Image.Resampling.LANCZOS)
    fill = fill.filter(ImageFilter.GaussianBlur(25))
    fill = ImageEnhance.Brightness(fill).enhance(0.45)
    foreground = original.copy()
    foreground.thumbnail((w,h),Image.Resampling.LANCZOS)
    offset = ((w-foreground.width)//2,(h-foreground.height)//2)
    fill.paste(foreground,offset)
    if spatial:
        # Spatial look = simulated framing/parallax on two composited planes.
        # This is deliberately NOT represented as a depth map or a 3D tour.
        fill = ImageEnhance.Contrast(fill).enhance(1.035)
    fill.save(dest, format='JPEG', quality=88, optimize=True)


def _ffmpeg_scene(source: Path, output: Path, i: int, size: tuple[int,int], duration: int, spatial: bool,
                  timeout: int = 150) -> None:
    if not shutil.which('ffmpeg'):
        raise AIEngineError('FFmpeg não instalado. Veja as instruções do Dockerfile.')
    w,h=size; fps=24; frames=fps*duration
    # Small cinematic push/pan, with a separate direction for each room.
    z_inc = 0.00075 if spatial else 0.00052
    start = 1.075 if spatial else 1.045
    if i%2:
        pan_x='(iw-iw/zoom)*(1-on/' + str(frames) + ')'
    else:
        pan_x='(iw-iw/zoom)*on/' + str(frames)
    pan_y='(ih-ih/zoom)*0.48'
    vf=(f'scale={w+120}:{h+68},'
        f'zoompan=z=\'min({start}+on*{z_inc},1.27)\':x=\'{pan_x}\':y=\'{pan_y}\':d={frames}:s={w}x{h}:fps={fps},'
        'format=yuv420p')
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',
         '-i',str(source),'-vf',vf,'-frames:v',str(frames),
         '-c:v','libx264','-threads','2','-preset','veryfast','-crf','25',
         '-pix_fmt','yuv420p','-movflags','+faststart','-an',str(output)]
    try:
        result=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,check=False)
    except subprocess.TimeoutExpired as exc:
        raise AIEngineError('A renderização demorou demais. Tente menos fotos.') from exc
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        msg=result.stderr.decode('utf-8','replace')[-650:]
        raise AIEngineError('Falha ao gerar o vídeo: '+msg)


def render_video(image_files: list[Path], destination: Path, spatial: bool = False, aspect: str='horizontal',
                 on_progress: Callable[[int,str],None] | None = None, progress_start: int=68, progress_end: int=97) -> dict:
    """24 fps MP4 with deterministic motion. No external video/AI API needed."""
    if not image_files:
        raise AIEngineError('Nenhuma foto disponível para criar o vídeo.')
    if not shutil.which('ffmpeg'):
        raise AIEngineError('FFmpeg ausente.')
    # 720p 24fps; Railway CPU-only rendering with two codec threads.
    if aspect not in ASPECTS: raise AIEngineError('Formato de vídeo inválido.')
    size=(1280,720) if aspect=='horizontal' else (720,1280)
    duration=4
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()
    with tempfile.TemporaryDirectory(prefix='stayvision-scenes-') as temp:
        tmp=Path(temp)
        paths=[]
        for ix, path in enumerate(image_files):
            canvas=tmp / f'canvas{ix:02d}.jpg'
            movie=tmp / f'clip{ix:02d}.mp4'
            _scene_frame(path,canvas,size,spatial)
            _ffmpeg_scene(canvas,movie,ix,size,duration,spatial)
            paths.append(movie)
            if on_progress: on_progress(int(progress_start + (ix+1)/len(image_files)*(progress_end-progress_start)),f'Vídeo: cena {ix+1} de {len(image_files)}')
        concat=tmp / 'scenes.txt'
        concat.write_text(''.join("file '"+p.name+"'\n" for p in paths),encoding='utf-8')
        cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',
             '-f','concat','-safe','0','-i',str(concat),'-c','copy','-movflags','+faststart',str(destination)]
        result=subprocess.run(cmd,cwd=tmp,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,check=False)
        if result.returncode or not destination.is_file() or destination.stat().st_size==0:
            raise AIEngineError('Erro na montagem do vídeo: '+result.stderr.decode('utf-8','replace')[-550:])
    return {'file':destination.name,'size_bytes':destination.stat().st_size,'resolution':f'{size[0]}x{size[1]}',
            'duration_seconds':len(image_files)*duration,'frames_per_second':24,
            'mode':'movimento espacial ilustrativo 2.5D' if spatial else 'video cinematografico 2D',
            'warning':'Não é reconstrução 3D real.' if spatial else 'Criado a partir de fotos estáticas.'}


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
    manifest={'engine_version':'stayvision-photo-v2.0-video-v1.0','mode':mode,'style':style,
              'photos':photos,'artifacts':artifacts,'aspect':aspect,
              'integrity':'Processamento fotográfico não generativo. Não inventa paredes, móveis ou detalhes ausentes.',
              'tour_3d':'não disponível; módulo de reconstrução real reservado para futura integração'}
    if mode in ('video','spatial','complete'):
        do_video = mode in ('video','complete')
        do_spatial = mode in ('spatial','complete')
        if on_progress: on_progress(68,'Preparando cenas de vídeo')
        if do_video:
            dest=output_dir/'Video_StayVision.mp4'
            video=render_video(processed,dest,spatial=False,aspect=aspect,on_progress=on_progress,progress_start=68,progress_end=82 if do_spatial else 96)
            artifacts.append({'name':dest.name,'label':'Vídeo cinematográfico MP4','type':'video',**video})
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
