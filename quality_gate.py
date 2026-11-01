"""Auditoria deterministica dos textos do Gemini ANTES de gastar fal.ai.
Nao substitui confirmacao de fatos da empresa por responsavel humano.
"""
from __future__ import annotations
import re, unicodedata

def plain(s):
    x=unicodedata.normalize('NFKD', str(s or '').lower())
    return ''.join(c for c in x if not unicodedata.combining(c))

# Mencionar esses alimentos nas OBSERVACOES das fotos e permitido; em
# texto ou identidade de marca de bebidas, requer contexto verificado.
WRONG={'bebidas': r'\b(?:hamburguer(?:es)?|burger|lanches?|sanduiches?|pizzas?|refeic(?:ao|oes)|batatas? fritas?|queijos?|ingredientes? selecionados|comidas?|alimentos?|restaurantes?)\b',
       'pizzaria': r'\b(?:hamburguer(?:es)?|burger|sanduiches?|coqueteis?|drinks?)\b',
       'hamburgueria':r'\b(?:pizzas?|coqueteis?|drinks?)\b',
       'pets':r'\b(?:copoes?|whisky|burgers?|pizzas?|coqueteis?)\b',
       'tecnologia':r'\b(?:copoes?|whisky|pizzas?|hamburgueres?|coqueteis?)\b',
       'moda':r'\b(?:copoes?|whisky|pizzas?|hamburgueres?|coqueteis?)\b',
       'beleza':r'\b(?:copoes?|whisky|pizzas?|hamburgueres?|coqueteis?)\b',
       'fitness':r'\b(?:copoes?|whisky|pizzas?|hamburgueres?|coqueteis?)\b',
       'imoveis':r'\b(?:copoes?|whisky|pizzas?|hamburgueres?|coqueteis?)\b',
       'saude':r'\b(?:copoes?|whisky|pizzas?|hamburgueres?|coqueteis?)\b',
       'educacao':r'\b(?:copoes?|whisky|pizzas?|hamburgueres?|coqueteis?)\b',
       'automotivo':r'\b(?:copoes?|whisky|pizzas?|hamburgueres?|coqueteis?)\b'}

# Textos seguros especificos para a DIRECAO DE MARCA, nao afirmacoes sobre o catalogo.
SAFE_DRINKS={
 'tagline': 'Um flash de personalidade para seu momento.',
 'visual_style': ('Identidade autoral para marca de bebidas: preto profundo, laranja luminoso, '
                  'composicao de estúdio premium, brilho pontual controlado, ritmo de raio e silhueta de copo.'),
 'logo_symbol': 'Silhueta estilizada de copo atravesada por um raio autoral, linhas fortes, leitura clara em avatar.',
 'headlines': ['Seu momento em destaque', 'Personalidade em cada escolha',
               'Um visual que marca', 'Seu ritmo, sua escolha',
               'O universo da marca', 'Uma identidade com energia'],
 'details': ['Conheça o universo da marca e suas opções.', 'Descubra a proposta e o estilo da marca.',
             'Saiba mais sobre a Copão Flash.', 'Veja novidades e informações no perfil.',
             'Encontre informações e entre em contato.', 'Acompanhe a identidade e as novidades.'],
 'captions': ['Conheça a marca e descubra o que combina com seu momento. Fale com a equipe para informações.',
              'Uma identidade marcante para momentos que merecem destaque. Confira mais no perfil.',
              'Cada escolha tem seu estilo. Acompanhe a marca e descubra suas opções.',
              'Quer saber mais sobre a proposta da marca? Entre em contato.',
              'Cores e atitude em uma identidade feita para chamar atenção. Conheça o perfil.',
              'Acompanhe nossas novidades e converse com a equipe para tirar suas dúvidas.'],
 'visual_motifs': ['Silhueta de copo autoral', 'Raio em movimento', 'Reflexos em âmbar e laranja',
                   'Padrões de faíscas controladas', 'Linhas dinâmicas sobre preto profundo'],
 'highlight_concepts': ['Um copo estilizado em destaque', 'Um ícone de opções com estética energética',
                        'Balão de conversa geométrico', 'Raio como emblema institucional',
                        'Estrela/faísca representando novidades'],
}

def _brand_specific(text, brand):
    # Evita codificar um cliente de teste como texto de todas as empresas.
    return text.replace('Copão Flash',brand)

def repair(brand, brief):
    """Repara copy e direcao que contradizem o ramo sem alterar evidencias das fotos."""
    out=dict(brief)
    sector=plain(out.get('sector'))
    regex=WRONG.get(sector)
    report=[]
    blocking=[]
    if not regex:
        out['quality_flags']=[]
        out['quality_warnings']=[]
        return out, report
    pattern=re.compile(regex,re.I)
    # Somente ramal bebidas tem dicionario especializado; outros devem exigir revisao.
    for key in ('tagline','visual_style','logo_symbol','bio_suggestion'):
        val=str(out.get(key,'') or '')
        if pattern.search(plain(val)):
            if sector=='bebidas':
                out[key]=_brand_specific(SAFE_DRINKS.get(key,''),brand)
                report.append(f'Referência a outro ramo corrigida em {key}.')
            else:
                blocking.append(f'Texto incompatível com o ramo em {key}: exige revisão.')
    for key in ('headlines','details','captions','visual_motifs','highlight_concepts'):
        items=list(out.get(key) or [])
        for i,val in enumerate(items):
            if pattern.search(plain(val)):
                if sector=='bebidas':
                    source=SAFE_DRINKS[key]
                    items[i]=_brand_specific(source[i%len(source)],brand)
                    report.append(f'Referência fora do ramo corrigida em {key}[{i+1}].')
                else:
                    blocking.append(f'Peça {key}[{i+1}] incompatível com a atividade declarada.')
        out[key]=items
    # Higienizacao do foco: nunca prometer que fotos de outro ramo sao o catalogo da empresa.
    uncertainty=' '.join(out.get('uncertainties') or [])
    mismatch=bool(re.search(r'contrast|contrasta|diverg|nao ha confirm|outro negocio|diferent',plain(uncertainty)))
    if mismatch:
        blocking.append('A imagem anexada pode pertencer a outro negócio. Remova a referência incorreta antes de produzir.')
    # Problemas corrigidos ficam no histórico de avisos, não impedem a geração.
    # Só inconsistências AINDA presentes bloqueiam uma chamada paga.
    out['quality_warnings']=list(dict.fromkeys(report))
    out['quality_flags']=list(dict.fromkeys(blocking))
    out['brand_mismatch_review']=mismatch
    return out, out['quality_warnings'] + out['quality_flags']
