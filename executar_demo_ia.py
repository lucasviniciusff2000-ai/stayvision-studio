"""Demo from StayVision's public reference imagery; no real customer data needed."""
import argparse
from pathlib import Path
from ai_engine import run_pipeline

if __name__=='__main__':
    cli=argparse.ArgumentParser(description='Demonstração local StayVision')
    cli.add_argument('--modo',choices=('photo','video','spatial','complete'),default='photo')
    cli.add_argument('--estilo',choices=('natural','claro','premium'),default='premium')
    cli.add_argument('--formato',choices=('horizontal','vertical'),default='horizontal')
    args=cli.parse_args()
    root=Path(__file__).resolve().parent
    images=[root/'static/assets/01_Piscina.jpg',root/'static/assets/02_Quarto.jpg']
    result=run_pipeline(images,root/'demo_ia_saida',args.modo,args.estilo,args.formato,lambda x,y:print(f'{x}% - {y}',flush=True))
    print('\nRESULTADOS:', (root/'demo_ia_saida').resolve())
    for item in result['artifacts']:print(' •',item['label'],item['name'])
