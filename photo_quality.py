"""StayVision V3.2 — diagnóstico e pré-tratamento fotográfico 100% local.

Não usa IA generativa, redes ou créditos. Métricas heurísticas NÃO certificam
nitidez nem fidelidade; qualquer foto transformada requer aprovação humana.
"""
from __future__ import annotations
import json
from pathlib import Path
from PIL import Image, ImageOps, ImageStat, ImageEnhance, ImageFilter

VERSION='SV_PHOTO_QUALITY_3_2'


def _small(im):
    sample=ImageOps.exif_transpose(im).convert('RGB')
    sample.thumbnail((512,512),Image.Resampling.LANCZOS)
    return sample


def diagnose(im):
    """Sinais aproximados de risco, sem adivinhar conteúdo ou inventar detalhes."""
    im=ImageOps.exif_transpose(im)
    if im.width<1 or im.height<1:raise ValueError('Imagem vazia.')
    sm=_small(im)
    gray=sm.convert('L'); st=ImageStat.Stat(gray)
    brightness=round(st.mean[0],1); contrast=round(st.stddev[0],1)
    hist=gray.histogram();total=max(1,sum(hist))
    shadows=round(100*sum(hist[:26])/total,1)
    whites=round(100*sum(hist[245:])/total,1)
    # Uma medida de textura, não um detector infalível de desfoque.
    edges=gray.filter(ImageFilter.FIND_EDGES)
    if min(edges.size)>20: edges=edges.crop((8,8,edges.width-8,edges.height-8))
    sharpness=round(ImageStat.Stat(edges).stddev[0],1)
    flags=[];risk='baixo'
    if min(im.size)<450:
        flags.append('Resolução muito baixa: detalhes reais podem estar irrecuperáveis.');risk='alto'
    elif min(im.size)<800:
        flags.append('Resolução limitada: ampliar não cria detalhes reais.');risk='moderado'
    if brightness<52 or shadows>48:
        flags.append('Foto muito escura ou com sombras extensas; iluminação precisará de correção.')
        risk='moderado' if risk=='baixo' else risk
    if brightness>224 or whites>48:
        flags.append('Foto muito clara ou com altas luzes estouradas; parte dos detalhes pode estar perdida.')
        risk='moderado' if risk=='baixo' else risk
    if contrast<24:
        flags.append('Baixo contraste: avaliar se a cena tem poucos detalhes ou falta de nitidez.')
    if sharpness<15:
        flags.append('Pouca textura detectada: possível desfoque ou área uniforme; conferir visualmente.')
        risk='moderado' if risk=='baixo' else risk
    # Texto de avaliação precisa limitar a interpretação de falsos positivos.
    return {'version':VERSION,'width':im.width,'height':im.height,
            'brightness_0_255':brightness,'contrast_std':contrast,
            'shadow_pixels_percent':shadows,'highlight_pixels_percent':whites,
            'edge_texture_heuristic':sharpness,'risk':risk,'warnings':flags,
            'measurement_note':'Métricas heurísticas: fundos lisos podem parecer borrados; nitidez real exige inspeção visual.'}


def prepare_reference(im,diagnosis=None):
    """Prepara referência fiel; não simula detalhes nem altera a identidade do objeto."""
    base=ImageOps.exif_transpose(im).convert('RGB')
    report=diagnosis or diagnose(base)
    out=base.copy();actions=[]
    light=report['brightness_0_255']
    if light<98:
        factor=min(1.20,max(1.06,1.11+(90-light)/800))
        out=ImageEnhance.Brightness(out).enhance(factor)
        actions.append('Correção moderada de exposição (não recupera pixels sem informação)')
    elif light>195:
        factor=max(.90,1.0-(light-195)/850)
        out=ImageEnhance.Brightness(out).enhance(factor)
        actions.append('Redução moderada da exposição')
    if report['contrast_std']<45 and 50<light<215:
        out=ImageEnhance.Contrast(out).enhance(1.08)
        actions.append('Ajuste moderado de contraste')
    # Evitar suavização automática que destrua rótulos/texturas.
    # Nunca intensificar artefatos em fotos extremamente pequenas.
    if min(out.size)>=700 and report['edge_texture_heuristic']>=15:
        out=out.filter(ImageFilter.UnsharpMask(radius=1.15,percent=55,threshold=4))
        actions.append('Nitidez suave de bordas existentes, sem reconstrução')
    if not actions:actions=['Referência mantida sem correções automáticas arriscadas']
    return out,{'processor':VERSION,'operations':actions,'quality_before':report,
                'faithfulness_note':'Pré-processamento tonal e nitidez leve; não restaura detalhes ausentes.'}


def _white_border_fraction(im):
    """Heuristic: white neutral pixels in the outer 14% border of the picture.

    Not a product mask; do not use it to assert product accuracy or reject catalog style
    in all industries. It is specific to explicit studio-backdrop fashion requests.
    """
    sm=ImageOps.exif_transpose(im).convert('RGB').resize((128,128),Image.Resampling.BILINEAR)
    px=sm.load();white=0;total=0
    for y in range(128):
        for x in range(128):
            if x<18 or x>=110 or y<18 or y>=110:
                r,g,b=px[x,y];total+=1
                if min(r,g,b)>=237 and max(r,g,b)-min(r,g,b)<18:white+=1
    return white/max(1,total)


def inspect_result(original,processed,sector='generico'):

    """Validação mecânica da imagem final. Não é autorização de publicação."""
    output=diagnose(processed)
    flags=[]
    if min(processed.size)<700:flags.append('Saída pequena: risco ao exportar para redes sociais.')
    if output['brightness_0_255']<35:flags.append('Saída excessivamente escura: revisar.')
    if output['brightness_0_255']>236:flags.append('Saída excessivamente clara: revisar.')
    if output['contrast_std']<13:flags.append('Saída com contraste muito baixo: revisar.')
    original_d=diagnose(original)
    if original_d['risk']=='alto':flags.append('Original de alto risco; detalhes aparentes da IA podem ter sido inventados.')
    # A V3.30 aprovou fotografias de calçados cujo branco genérico foi mantido.
    # Na direção STUDIO para moda isso exige revisão e NUNCA entrega automática.
    if sector=='moda' and _white_border_fraction(original)>0.68 and _white_border_fraction(processed)>0.38:
        flags.append('Fundo branco de catálogo permaneceu; cenário publicitário da StayVision não foi demonstrado. Reter para revisão.')
    return {'version':VERSION,'source':original_d,'result':output,
            'review_flags':flags,
            'status':'REVISAO_PRIORITARIA' if flags else 'REVISAO_HUMANA_OBRIGATORIA',
            'approval':'NAO_APROVADO_AUTOMATICAMENTE',
            'checklist':['Produto/rosto, contagem, tamanho e formato idênticos aos reais',
                         'Rótulos, textos, cores e marcas corretos',
                         'Sem partes artificiais ou objetos inventados',
                         'Detalhes e nitidez aceitáveis em 100% de zoom']}


def save_report(path,report):
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
