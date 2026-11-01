"""Bio profissional Instagram: zero chamadas de API, 150 caracteres, sem promessas inventadas.
Opcionalmente aceita sugestão validada do Gemini, na MESMA chamada de briefing existente.
O nome e o @ pertencem ao campo Nome/usuário do Instagram, não são repetidos na bio.
"""
from __future__ import annotations
import hashlib
import re
import unicodedata

MAX_BIO = 150


def _clean(s, limit=100):
    return re.sub(r'\s+', ' ', str(s or '')).strip()[:limit]


def _choice(name, options):
    n = int(hashlib.sha256(name.casefold().encode('utf-8')).hexdigest()[:8], 16)
    return options[n % len(options)]


def _safe_suggestion(text, activity):
    if not isinstance(text, str):
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 4:
        return None
    bio = '\n'.join(lines)
    if len(bio) > MAX_BIO or len(bio) < 55 or not any(ord(ch) > 0x2300 for ch in bio):
        return None
    banned = (r'\b24\s*h\b', r'\bgr[aá]tis\b', r'\bgarantid[ao]s?\b',
              r'\b(?:o|a) melhor\b', r'\br\$\s*\d+', r'\b\d+\s*%\b',
              r'\b(?:promo[cç][aã]o|desconto|frete)\b', r'\b(?:desde)\s*\d{4}\b')
    if any(re.search(exp, bio, re.I) for exp in banned):
        return None
    if re.search(r'@\S+|\(\d{2}\)\s*\d{4,5}', bio):
        return None
    if ('delivery' in bio.lower() or 'entrega' in bio.lower()) and not re.search(r'delivery|entreg', activity, re.I):
        return None
    return bio


def generate_bio(info, brief):
    brand = _clean(info.get('brand'), 75)
    activity = _clean(info.get('activity'), 90)
    sector = _clean(brief.get('sector'), 30).lower()
    # Evite repetir dados já presentes em Nome, @ e botão de contato do Instagram.
    suggestion = _safe_suggestion(brief.get('bio_suggestion'), activity)
    if suggestion:
        return suggestion

    delivery = bool(re.search(r'delivery|entreg', activity, re.I))
    if 'copão' in brand.casefold() and 'flash' in brand.casefold() and sector == 'bebidas':
        parts = [
            '⚡ Seu rolê pede um FLASH!',
            '🥃 Copões e bebidas do seu jeito',
            '🧊 Sabor e atitude para curtir',
            '🛵 Peça pelo contato do perfil 👇' if delivery else '👇 Fale com a gente e saiba mais'
        ]
    elif sector == 'bebidas':
        parts = [
            _choice(brand, ['🍹 Seu momento merece outro sabor', '🥤 Seu próximo brinde começa aqui', '✨ Um brinde ao seu momento']),
            '🧊 Bebidas e opções para escolher',
            '🛵 Peça por delivery' if delivery else '🥃 Conheça nosso cardápio',
            '👇 Confira o contato e peça o seu!'
        ]
    elif sector == 'hamburgueria':
        parts = [
            _choice(brand, ['🍔 Bateu aquela vontade de burger?', '🔥 O próximo desejo tem sabor de burger', '🍔 Seu próximo lanche começa aqui']),
            '🤤 Conheça nossos hambúrgueres',
            '🛵 Peça pelo delivery' if delivery else '📋 Confira nossas opções',
            '👇 Veja o cardápio e fale com a gente'
        ]
    elif sector == 'pizzaria':
        parts = ['🍕 Deu vontade de pizza?', '🤤 Descubra seus próximos sabores',
                 '🛵 Peça pelo delivery' if delivery else '📋 Confira nossas opções',
                 '👇 Veja o cardápio e fale com a gente']
    elif sector == 'gastronomia':
        parts = ['🍽️ Seu próximo sabor começa aqui', '✨ Descubra as opções da casa',
                 '🛵 Peça pelo delivery' if delivery else '📋 Conheça nosso cardápio',
                 '👇 Fale com a gente e saiba mais']
    elif sector == 'moda':
        parts = ['✨ Seu estilo fala por você', '👗 Peças para criar novas combinações',
                 '🛍️ Explore nosso catálogo', '👇 Fale com a loja e saiba mais']
    elif sector == 'beleza':
        parts = ['✨ Seu momento de se cuidar', '💖 Beleza com a sua personalidade',
                 '💄 Conheça nossos serviços e opções', '👇 Fale com a gente e saiba mais']
    elif sector in ('pets','tecnologia','fitness','imoveis','automotivo','saude','educacao'):
        from marketing_upgrade import topic
        subject=topic(info,brief)
        hooks={'pets':'🐾 Um universo pensado para pets', 'tecnologia':'💻 Tecnologia em foco',
               'fitness':'💪 Movimento com propósito','imoveis':'🏠 Espaços para conhecer',
               'automotivo':'🚗 O universo automotivo','saude':'💙 Conheça nosso espaço',
               'educacao':'📚 Ideias para aprender'}
        parts=[hooks[sector], '🎯 '+subject[:48],
               '📸 Confira referências e detalhes', '👇 Fale com a equipe']
    elif sector == 'servicos':
        parts = ['✨ Ideias que fazem diferença', '🛠️ Conheça o nosso trabalho',
                 '📍 Veja nossos serviços', '👇 Entre em contato e saiba mais']
    else:
        descr = activity.rstrip('.!') if activity else 'Conheça nossa marca'
        parts = ['✨ O que fazemos, com identidade',
                 '🎯 ' + descr[:52], '📸 Explore nossos trabalhos e detalhes',
                 '👇 Entre em contato e saiba mais']
    bio = '\n'.join(parts)
    if len(bio) > MAX_BIO:
        # Preserve CTA and meaning without truncating mid-emoji or mid-word.
        shorten = {'👇 Veja o cardápio e fale com a gente': '👇 Confira o cardápio',
                   '👇 Fale com a gente e saiba mais': '👇 Fale com a gente',
                   '👇 Entre em contato e saiba mais': '👇 Saiba mais no contato',
                   '👇 Confira o contato e peça o seu!': '👇 Faça seu pedido!'}
        parts[-1] = shorten.get(parts[-1], parts[-1])
        bio = '\n'.join(parts)
        if len(bio) > MAX_BIO:
            parts[1] = parts[1][:max(20, len(parts[1])-(len(bio)-MAX_BIO)-3)].rstrip(' ,')
            bio = '\n'.join(parts)
    if len(bio) > MAX_BIO:
        raise ValueError('Bio excedeu 150 caracteres e precisa de revisão.')
    return bio


def suggested_name(info, brief):
    brand = _clean(info.get('brand'), 50)
    sector = str(brief.get('sector', '')).lower()
    label = {
        'bebidas':'Bebidas & Copões', 'hamburgueria':'Hambúrgueres',
        'pizzaria':'Pizzaria', 'gastronomia':'Gastronomia',
        'moda':'Moda', 'beleza':'Beleza', 'servicos':'Serviços', 'pets':'Pet', 'tecnologia':'Tecnologia', 'fitness':'Fitness', 'imoveis':'Imóveis', 'automotivo':'Automotivo', 'saude':'Saúde', 'educacao':'Educação'
    }.get(sector, '')
    if not label:
        return brand[:64]
    suffix = ' | ' + label
    return brand[:max(1, 64-len(suffix))] + suffix


def preview_plain(text):
    """Pillow pode não ter fonte emoji; PNG usa texto limpo. TXT/HTML mantêm emojis."""
    value = ''.join(ch for ch in str(text) if unicodedata.category(ch) not in ('So','Sk','Cf') and not (0x1F000 <= ord(ch) <= 0x1FAFF))
    return _clean(value, 150).lstrip('•·- ')


def write_html_preview(root, info, brief):
    """Prévia no navegador com os emojis REAIS e as cinco capas existentes."""
    from pathlib import Path
    import html
    base = Path(root) / '02_perfil_express'
    name = suggested_name(info, brief)
    handle = _clean(info.get('instagram'), 60).lstrip('@')
    bio = generate_bio(info, brief)
    safe_lines = ''.join(f'<div class="line">{html.escape(line)}</div>' for line in bio.splitlines())
    labels = (list(brief.get('highlights') or [])[:5] + ['Produtos', 'Novidades', 'Pedidos', 'Sobre', 'Contato'])[:5]
    circles = '\n'.join(
        f'<div class="highlight"><img src="capa_destaque_{i:02d}.png" alt="Capa {html.escape(label)}"><span>{html.escape(label)}</span></div>'
        for i, label in enumerate(labels, 1)
    )
    page = '''<!DOCTYPE html><html lang="pt-br"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Prévia editorial da bio</title><style>
    *{box-sizing:border-box}body{margin:0;background:#101116;color:#f8f8fa;font-family:system-ui,-apple-system,"Segoe UI",Arial,sans-serif}
    .outer{max-width:670px;margin:25px auto;padding:24px}.top{display:flex;justify-content:space-between;align-items:center;padding:0 0 16px;border-bottom:1px solid #292933}
    .studio{font-weight:800;letter-spacing:2px;color:#ff8740;font-size:12px}.flag{font-size:11px;color:#b0aab1}
    .phone{margin-top:22px;border:1px solid #35333d;border-radius:30px;background:#171820;padding:27px 24px 42px;box-shadow:0 12px 55px #0007}
    .user{font-size:20px;font-weight:750;display:flex;gap:10px;align-items:center}.verified{background:#ff8740;color:#24120b;border-radius:999px;padding:4px 8px;font-size:11px}
    .hero{display:flex;gap:24px;align-items:center;margin:28px 0}.avatar{width:114px;height:114px;border-radius:100%;object-fit:cover;border:3px solid #ff8740;padding:2px}.name{font-weight:770;font-size:19px;line-height:1.3}
    .small{margin-top:7px;font-size:13px;color:#b4acb5}.line{font-size:16px;line-height:1.58;white-space:pre-wrap}
    .contact{display:block;text-decoration:none;border:1px solid #514035;color:#ffd4ae;background:#292020;padding:12px;margin:23px 0 25px;text-align:center;border-radius:12px;font-weight:700}
    .hl{display:flex;gap:8px;justify-content:space-between}.highlight{display:flex;flex-direction:column;align-items:center;max-width:19%;gap:9px;font-size:12px;text-align:center;color:#e0dce0;overflow-wrap:anywhere}
    .highlight img{width:min(15vw,86px);height:min(15vw,86px);border-radius:50%;object-fit:cover;border:2px solid #40343d;padding:2px}
    .foot{color:#a39ca5;font-size:12px;text-align:center;margin-top:28px}
    @media(max-width:480px){.outer{padding:10px}.phone{padding:18px 15px}.avatar{width:88px;height:88px}.hero{gap:15px}.user{font-size:17px}.line{font-size:14px}}
    </style></head><body><div class="outer"><div class="top"><div class="studio">STAYVISION BUSINESS • BIO PROFISSIONAL</div><div class="flag">PRÉVIA, NÃO PUBLICADO</div></div>
    <div class="phone"><div class="user">@__HANDLE__ <span class="verified">Prévia</span></div><div class="hero"><img class="avatar" src="foto_de_perfil_1080.png" alt="Logo atual"><div><div class="name">__NAME__</div><div class="small">Perfil comercial • revisão de texto</div></div></div>
    <section>__LINES__</section><span class="contact">📲 Canal de contato cadastrado</span><div class="hl">__CIRCLES__</div></div>
    <p class="foot">Layout ilustrativo para revisão. Não representa métricas, seguidores, link ativo ou perfil publicado.</p></div></body></html>'''
    page = page.replace('__HANDLE__',html.escape(handle)).replace('__NAME__',html.escape(name)).replace('__LINES__',safe_lines).replace('__CIRCLES__',circles)
    (base/'previa_bio_no_navegador.html').write_text(page, encoding='utf-8')


def generate_bio_options(info, brief):
    """Três abordagens editoriais independentes; limite 150 caracteres por versão."""
    from marketing_upgrade import topic, trim
    brand=trim(info.get('brand'),45)
    sector=trim(brief.get('sector'),30)
    activity=trim(info.get('activity') or brief.get('activity'),64)
    subject=topic(info,brief)
    primary=generate_bio(info,brief)
    if sector=='bebidas':
        lines2=['🍹 Um brinde ao seu momento!', '🥤 '+('Copões e bebidas' if 'cop' in activity.casefold() else 'Bebidas para conhecer'),
                '⚡ Descubra mais pelo nosso perfil', '👇 Fale com a gente']
    elif sector=='moda':
        lines2=['✨ Seu estilo começa nos detalhes', '👗 '+subject[:46],
                '🛍️ Explore nossas inspirações', '👇 Fale com a loja']
    elif sector=='beleza':
        lines2=['✨ Beleza com personalidade', '💖 '+subject[:48],
                '📸 Confira nosso trabalho', '👇 Fale com a equipe']
    elif sector in ('hamburgueria','pizzaria','gastronomia'):
        lines2=['🍽️ Que tal descobrir algo novo?', '🍴 '+subject[:48],
                '📸 Explore nosso perfil', '👇 Pergunte pelas opções']
    else:
        lines2=['✨ Uma identidade que tem propósito', '🎯 '+subject[:48],
                '📸 Conheça o que fazemos', '👇 Fale com a equipe']
    lines3=['✦ Conheça a '+brand[:32], '◈ '+subject[:57],
            '✧ Explore ideias e referências', '↓ Informações no contato do perfil']
    def compact(lines):
        x='\n'.join(lines)
        if len(x)<=150:return x
        lines[1]=lines[1][:max(18, len(lines[1])-(len(x)-150)-1)].rstrip(' ,.;')
        x='\n'.join(lines)
        if len(x)>150:lines[2]='✧ Conheça mais por aqui';x='\n'.join(lines)
        if len(x)>150:lines[0]='✨ Conheça nossa marca';x='\n'.join(lines)
        if len(x)>150:raise ValueError('Bio alternativa acima do limite Instagram')
        return x
    options=[('COMERCIAL — RECOMENDADA',primary),('CRIATIVA',compact(lines2)),('INSTITUCIONAL',compact(lines3))]
    if len(set(t for _,t in options))<3:raise ValueError('Bios muito semelhantes, revisar opções.')
    return '\n\n'.join(f'{label} ({len(value)}/150 caracteres)\n{value}' for label,value in options)+'\n'
