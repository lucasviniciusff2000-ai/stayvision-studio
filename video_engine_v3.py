"""StayVision Video Engine V3: steady, faithful photo animation.

No generative AI. OpenCV's fractional-pixel affine interpolation avoids the
integer-rounded zoompan motion that caused micro-jumps on straight edges.
Frames are piped to FFmpeg, never stored as thousands of temporary JPEGs.
The original room geometry is not regenerated or distorted.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

FPS = 30
SCENE_SECONDS = 4
CROSSFADE_FRAMES = 15  # 0.5 seconds
MOTIONS = ("gentle", "minimal", "static")


class SteadyVideoError(Exception):
    pass


def ease(t: float) -> float:
    """Smootherstep: zero speed and acceleration at both ends."""
    x = min(1.0, max(0.0, float(t)))
    return x * x * x * (x * (x * 6 - 15) + 10)


def crossfade_weight(frame_idx: int, total: int) -> float:
    """Cosine transition weight, 0→1 without an abrupt start/end."""
    if total < 1: return 1.0
    t = (frame_idx + 1) / (total + 1)
    return 0.5 - 0.5 * math.cos(math.pi * t)


def scene_canvas(source: Path, size: tuple[int, int]) -> np.ndarray:
    """Preserve entire source image and set unobtrusive background for mismatch.

    Avoid stretching or changing geometry of property. A blurred copy fills
    letterbox/pillarbox spaces; original pixels are kept in the foreground.
    """
    w, h = size
    with Image.open(source) as opened:
        orig = ImageOps.exif_transpose(opened).convert("RGB")
    if orig.width <= 0 or orig.height <= 0:
        raise SteadyVideoError("Fotografia inválida para vídeo.")
    target_ratio = w / h
    src_ratio = orig.width / orig.height
    if abs(src_ratio - target_ratio) < 0.018:
        return cv2.cvtColor(np.asarray(orig.resize(size, Image.Resampling.LANCZOS)), cv2.COLOR_RGB2BGR)
    # Soft, dark background is deliberately subdued, so original is dominant.
    bg = ImageOps.fit(orig, size, Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=max(12, min(w, h) // 36)))
    bg = ImageEnhance.Brightness(bg).enhance(0.34)
    fg = orig.copy()
    fg.thumbnail(size, Image.Resampling.LANCZOS)
    x = (w - fg.width) // 2
    y = (h - fg.height) // 2
    bg.paste(fg, (x, y))
    return cv2.cvtColor(np.asarray(bg), cv2.COLOR_RGB2BGR)


def frame_transform(size: tuple[int, int], scene_index: int, t: float,
                    motion: str = "gentle", spatial: bool = False) -> np.ndarray:
    """2x3 source→target transform; translation and zoom stay fractional.

    Zoom is restrained to 1–3% (spatial illustration up to 4%); motion is
    deterministic and both start/end have zero velocity and acceleration.
    """
    if motion not in MOTIONS:
        raise SteadyVideoError("Movimento inválido; use gentle, minimal ou static.")
    w, h = size
    p = ease(t)
    if motion == "static":
        z, dx, dy = 1.0, 0.0, 0.0
    else:
        strength = 0.38 if motion == "minimal" else 1.0
        amp = (0.035 if spatial else 0.024) * strength
        # One intent per scene: either calm push/pull or a short drifting path.
        mode = scene_index % 4
        if mode == 0:   # gentle approach; no pan
            z = 1.012 + amp * p
            dx, dy = 0., 0.
        elif mode == 1: # slow reveal left→right, almost constant zoom
            z = 1.022 + 0.007 * strength * p
            dx = (p - 0.5) * w * 0.010 * strength
            dy = 0.
        elif mode == 2: # slow retreat
            z = 1.012 + amp * (1-p)
            dx, dy = 0., 0.
        else:           # very mild vertical drift
            z = 1.023 + 0.004 * strength * p
            dx = 0.
            dy = (p - 0.5) * h * 0.009 * strength
    # Continuous subpixel affine transform centered on the composition.
    return np.asarray([[z, 0., (1-z)*w/2+dx],
                       [0., z, (1-z)*h/2+dy]], dtype=np.float64)


def steady_frame(canvas: np.ndarray, scene_index: int, frame_index: int,
                 frames_per_scene: int, motion: str="gentle", spatial: bool=False) -> np.ndarray:
    h,w = canvas.shape[:2]
    t = frame_index/max(1, frames_per_scene-1)
    affine = frame_transform((w,h), scene_index, t, motion=motion, spatial=spatial)
    if np.array_equal(affine, np.asarray([[1,0,0],[0,1,0]])):
        return canvas
    return cv2.warpAffine(canvas, affine, (w,h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT_101)


def _quality_size(paths: list[Path], aspect: str, profile: str) -> tuple[int,int]:
    if aspect not in ("horizontal", "vertical"):
        raise SteadyVideoError("Formato de vídeo inválido.")
    if profile not in ("auto", "balanced", "hd"):
        raise SteadyVideoError("STAYVISION_VIDEO_QUALITY precisa ser auto, balanced ou hd.")
    native=[]
    for path in paths:
        with Image.open(path) as im:
            native.append(min(im.size))
    fullhd = profile == "hd" or (profile == "auto" and min(native)>=950 and len(paths)<=8)
    return ((1920,1080) if aspect=="horizontal" else (1080,1920)) if fullhd else \
           ((1280,720) if aspect=="horizontal" else (720,1280))


def render_steady_video(image_files: list[Path], destination: Path, *,
                        aspect: str="horizontal", spatial: bool=False,
                        motion: str="gentle", quality: str="auto",
                        on_progress: Callable[[int,str],None] | None=None,
                        progress_start: int=68, progress_end: int=97) -> dict:
    if not image_files:
        raise SteadyVideoError("Nenhuma foto disponível para criar o vídeo.")
    if len(image_files)>12:
        raise SteadyVideoError("No máximo 12 imagens por vídeo.")
    if motion not in MOTIONS:
        raise SteadyVideoError("Movimento inválido.")
    if not shutil.which("ffmpeg"):
        raise SteadyVideoError("FFmpeg não instalado.")
    size = _quality_size(image_files,aspect,quality)
    w,h=size
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination=destination.resolve()
    frames = FPS*SCENE_SECONDS
    overlap = CROSSFADE_FRAMES if len(image_files)>1 else 0
    total_frames = len(image_files)*frames-(len(image_files)-1)*overlap
    # Two x264 threads to avoid monopolizing a small Railway instance.
    cmd=["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s:v", f"{w}x{h}",
         "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "19", "-threads", "2",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart",
         str(destination)]
    written=0
    with tempfile.TemporaryFile() as errors:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=errors)
        try:
            assert proc.stdin is not None
            # Avoid keeping every image/video frame in memory. Only two canvases.
            current = scene_canvas(image_files[0],size)
            for idx in range(len(image_files)):
                nxt=scene_canvas(image_files[idx+1],size) if idx+1<len(image_files) else None
                start=0 if idx==0 else overlap
                for fi in range(start,frames):
                    frame=steady_frame(current,idx,fi,frames,motion=motion,spatial=spatial)
                    if nxt is not None and fi >= frames-overlap:
                        k=fi-(frames-overlap)
                        next_frame=steady_frame(nxt,idx+1,k,frames,motion=motion,spatial=spatial)
                        weight=crossfade_weight(k,overlap)
                        frame=cv2.addWeighted(frame,1-weight,next_frame,weight,0)
                    proc.stdin.write(frame.tobytes())
                    written+=1
                current=nxt
                if on_progress:
                    on_progress(int(progress_start+(idx+1)/len(image_files)*(progress_end-progress_start)),
                                f"Vídeo estável: cena {idx+1} de {len(image_files)}")
            proc.stdin.close()
            code=proc.wait(timeout=180)
            if code != 0:
                errors.seek(0)
                raise SteadyVideoError("FFmpeg falhou: "+errors.read().decode("utf-8","replace")[-600:])
        except (OSError, BrokenPipeError, subprocess.TimeoutExpired) as exc:
            proc.kill();proc.wait()
            errors.seek(0)
            detail=errors.read().decode("utf-8","replace")[-350:]
            if destination.exists(): destination.unlink()
            raise SteadyVideoError("Falha ao renderizar o vídeo. "+detail) from exc
        except BaseException:
            proc.kill();proc.wait()
            if destination.exists(): destination.unlink()
            raise
    if written != total_frames or not destination.is_file() or destination.stat().st_size == 0:
        raise SteadyVideoError("O vídeo gerado ficou incompleto.")
    return {
        "file":destination.name,
        "size_bytes":destination.stat().st_size,
        "resolution": f"{w}x{h}",
        "frames_per_second":FPS,
        "frame_count":written,
        "duration_seconds":round(written/FPS,2),
        "transition_seconds": overlap/FPS,
        "motion_profile":motion,
        "quality_profile":"1080p Full HD (fonte adequada ou forçado)" if w in (1920,1080) and max(w,h)==1920 else "720p eficiente",
        "mode":"movimento espacial ilustrativo 2.5D" if spatial else "vídeo estável de fotos 2D",
        "engine":"video-v3-subpixel-easing-crossfade",
        "warning":"Não é reconstrução 3D real." if spatial else "Animação estável de fotos, não vídeo generativo por IA.",
    }
