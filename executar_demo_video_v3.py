"""Optional: render a private video on Windows without starting web server.

Usage: python executar_demo_video_v3.py "C:\\Fotos" --aspect vertical
No photos are sent anywhere; uses OpenCV and local FFmpeg only.
"""
import argparse
import json
import os
from pathlib import Path
from video_engine_v3 import render_steady_video, SteadyVideoError


def main():
    parser=argparse.ArgumentParser(description='StayVision: criar vídeo estável V3 de fotos locais')
    parser.add_argument('photos',help='Pasta com fotos .jpg/.png/.webp')
    parser.add_argument('--aspect',choices=('horizontal','vertical'),default='horizontal')
    parser.add_argument('--quality',choices=('auto','balanced','hd'),default='auto')
    parser.add_argument('--motion',choices=('gentle','minimal','static'),default='gentle')
    args=parser.parse_args()
    source=Path(args.photos).expanduser().resolve()
    if not source.is_dir():parser.error('Informe uma pasta existente com fotos.')
    images=sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() in ('.jpg','.jpeg','.png','.webp'))
    if not 1<=len(images)<=12:parser.error('Use de 1 a 12 fotos por vídeo.')
    dest=source.parent/(source.name+'_StayVision_V3')
    dest.mkdir(exist_ok=True)
    video=dest/f'Video_StayVision_{args.aspect}_V3.mp4'
    try:
        report=render_steady_video(images,video,aspect=args.aspect,quality=args.quality,motion=args.motion,
                    on_progress=lambda p,m: print(f'{p}% — {m}',flush=True))
    except SteadyVideoError as exc:
        parser.error(str(exc))
    print('Vídeo:',video)
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
