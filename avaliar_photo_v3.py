#!/usr/bin/env python3
"""Photo V3 offline QA: validate property photographs without uploading them.

Usage: python avaliar_photo_v3.py "C:\Fotos-Imovel" --estilo claro
Creates output outside the originals folder. Never overwrites originals.
"""
import argparse
import json
import sys
from pathlib import Path
from ai_engine import run_pipeline, AIEngineError

def main():
    parser=argparse.ArgumentParser(description='StayVision Photo Engine V3 — avaliação local')
    parser.add_argument('entrada',help='Pasta contendo imagens JPG, JPEG, PNG, WEBP, ou caminho para uma foto')
    parser.add_argument('--estilo',choices=['natural','claro','premium'],default='claro')
    parser.add_argument('--saida',default=None)
    args=parser.parse_args()
    source=Path(args.entrada).expanduser().resolve()
    if source.is_file():files=[source]
    elif source.is_dir(): files=sorted(f for f in source.iterdir() if f.is_file() and f.suffix.lower() in ('.jpg','.jpeg','.png','.webp'))
    else:parser.error('Pasta/arquivo não encontrado')
    if not 1<=len(files)<=12:
        parser.error('Escolha entre 1 e 12 fotos por vez')
    out=Path(args.saida).expanduser().resolve() if args.saida else source.parent/(source.stem+'_StayVision_V3' if source.is_file() else source.name+'_StayVision_V3')
    if source.is_dir() and out==source:parser.error('A pasta de saída não pode ser a pasta de originais')
    try:
        result=run_pipeline(files,out,'photo',args.estilo)
    except (AIEngineError,ValueError,OSError) as e:
        print('Erro:',e,file=sys.stderr)
        return 1
    print('Pronto:',out)
    print('Compare original x tratada no arquivo:',out/'Comparativo_StayVision_V3.jpg')
    print('Relatório:',out/'Relatorio_Qualidade_V3.json')
    for i,photo in enumerate(result['photos'],1):
        if photo.get('quality_notice'):print(f'Aviso foto {i}:',photo['quality_notice'])
    return 0

if __name__=='__main__':raise SystemExit(main())
