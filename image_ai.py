"""StayVision Business - GPT Image 2.5 Sunburst Edit via fal.ai.
ONLY server-side (local on Windows). Explicit paid opt-in. NO automatic retries.
"""
from __future__ import annotations
import base64, io, os, re, json
from urllib.parse import urlparse
from urllib.request import Request,urlopen
from threading import Lock, local
from PIL import Image, ImageOps, ImageDraw

ENDPOINT = 'openai/gpt-image-2.5/sunburst/edit'
PROMPT_VERSION = 'SV_331_PREMIUM_STUDIO_SCENE_V1'
REF_IMAGE_USD = 0.0412  # Apenas estimativa; cobrança efetiva no painel da fal.ai.
SESSION_CALLS = 0
_LOCK = Lock()
_THREAD_PROGRESS=local()

def set_attempt_hook(callback):
    """Somente no worker local; invocado APÓS reservar e ANTES do envio externo."""
    _THREAD_PROGRESS.callback=callback

def _notify_attempt(role):
    fn=getattr(_THREAD_PROGRESS,'callback',None)
    if fn is not None:fn(role)  # falha aqui bloqueia o envio, sem repetir reserva


def enabled():
    return os.getenv('STAYVISION_IMAGE_MODE','off').strip().lower() == 'required'

def provider(): return 'fal_gpt_image'
def model(): return ENDPOINT

def limit():
    try:return max(0,min(40,int(os.getenv('STAYVISION_IMAGE_SESSION_LIMIT','0'))))
    except (ValueError,TypeError):return 0

def remaining():return max(0,limit()-SESSION_CALLS)

def preflight(num_images):
    if not enabled(): return
    if not os.getenv('FAL_KEY','').strip():
        raise RuntimeError('FAL_KEY ausente. Use o inicializador Etapa 26; não envie sua chave pelo chat.')
    if num_images < 1 or num_images > 40:
        raise RuntimeError('Número de chamadas inválido (1 a 40).')
    if remaining() < num_images:
        raise RuntimeError('Restam %d chamadas autorizadas nesta sessão; pedido exige %d. Nenhuma nova edição foi iniciada.' % (remaining(),num_images))

def edit_goal():
    return 'refine' if os.getenv('STAYVISION_EDIT_GOAL','new').strip().lower() == 'refine' else 'new'

def make_prompt(brand, observation='', sector='generico'):
    """Strong direction, distinguish refinement from brand-new commercial edit.

    Refine: supplied photo is the *prior professional result*. Change only deficient
    parts without modifying product. New: source is a raw smartphone photograph.
    """
    if edit_goal() == 'refine':
        return (
            "PRECISION RETOUCH of the already professionally edited CUSTOMER PHOTO. "
            "Preserve its EXACT subject, visible people, objects, location, geometry, count, "
            "materials, colors, labels, writing and composition. Correct ONLY lighting, "
            "harsh artifacts, distracting dust and minor tonal issues. "
            "Do NOT redesign anything, replace the product, invent ingredients, services, "
            "architecture, faces, clothing, brands or accessories. No text or watermark. "
        )

    base = (
        "Transform this REAL customer-supplied photograph into a refined, believable "
        "professional commercial photograph. First identify what is ACTUALLY in the "
        "reference. Keep its real subject, category, silhouette, exact product count, "
        "visible branding, surface textures, geometry and factual details. Improve "
        "lighting, color balance, sharpness, depth and distracting background elements "
        "without altering the business facts. Choose an environment suitable for "
        "the detected SUBJECT AND declared BUSINESS SECTOR, not a restaurant by default. "
        "Do not invent products, food ingredients, testimonials, storefronts, people, "
        "prices, logos or claims. No text or watermarks. "
    )
    by_sector = {
        'bebidas': (
            "Faithful premium commercial BEVERAGE photography. Preserve the exact number "
            "and shape of the existing transparent cups, original liquid hue and fill level, "
            "ice size and count where visible, condensation, straw, garnish, and all visible "
            "branding without modifying logos or inventing legible labels. "
            "No added bottles, whisky labels, alcohol brands, fruit, ingredients, pricing, "
            "promises or decorations not present in the photograph. Do not turn the drink "
            "into a slushie or change a clear drink into a bright colored cocktail. "
            "Remove distracting backgrounds and replace with a premium dark bar/studio "
            "setting while maintaining authentic cup proportions and natural contact shadows. "
        ),
        'pizzaria': (
            "The SAME pizza remains the hero. Keep the real ingredient types and "
            "count of visible olives, real homemade crust and natural outline. "
            "If the photograph contains distracting packaging, improve its presentation "
            "without deleting any meaningful authentic brand information. Keep the entire visible "
            "portion and natural aspect ratio; don't invent an artificial geometric "
            "outline or create sharp corners or tips. Professional warm restaurant "
            "light and appetite-inducing but credible colors. "
        ),
        'hamburgueria': (
            "Retain the exact number of burgers and major visible ingredients, bun "
            "shapes, realistic patty thickness and lettuce/cheese proportions. "
            "Remove clutter; stage with sophisticated food photography lighting "
            "and appropriate restaurant background without adding food. "
        ),
        'gastronomia': (
            "Keep the same real dish, food category, portions and identifiable "
            "ingredients. Use premium restaurant lighting and a clean scene. "
        ),
        'beleza': (
            "Keep the exact container, product count, visible label and brand "
            "faithful, with elegant studio lighting and clean commercial background. "
        ),
        'moda': (
            "HIGH-END FASHION / FOOTWEAR / JEWELRY PRODUCT PHOTOGRAPHY. "
            "Keep the EXACT physical product(s): same number of items, silhouette, "
            "shoe last, heel shape and height, toe, ankle opening, eyelets, laces, "
            "buckles, ornaments, visible text, materials and actual colors. "
            "Do not redesign the product, alter its proportions, invent hardware, "
            "add a second shoe when only one is shown, or change the camera angle dramatically. "
            "Improve the ENVIRONMENT to look like a genuine, premium studio campaign: "
            "replace a blank, flat pure-white cutout background with subtle warm ivory "
            "plaster or beige limestone architecture, a tasteful travertine display surface "
            "and physically convincing contact shadows. Soft directional daylight, "
            "refined commercial highlights, realistic fine-grain texture and depth; "
            "natural editorial product photography, not an illustration. "
            "If the source already has a credible composed environment, improve it "
            "without replacing it unnecessarily. If the product is jewelry, use "
            "scaled jewelry display blocks rather than an oversized shoe podium. "
            "Keep the entire product comfortably within the frame and visually dominant. "
            "Avoid white seamless catalog cutout as the final scene when the source is "
            "already on a plain white background. Do not invent logos or captions. "
        ),
        'servicos': (
            "Improve the real place faithfully; do not fabricate architecture, "
            "equipment, people, signs or features. "
        ),
        'pets': ("Preserve animal identity, coat, pose, surroundings and any visible products. No fake pets, breed claims or equipment."),
        'tecnologia': ("Keep exact device model, design, visible ports, screen and labels. No invented specifications or brand changes."),
        'fitness': ("Keep real gym space, equipment, poses, people and brand identity. No manipulated body results or fake achievements."),
        'imoveis': ("Keep the exact layout, architecture, room size, walls, windows, floors and fixed features. No fake rooms or renovations."),
        'automotivo': ("Preserve real vehicle model, color, proportions, badges and real workshop features. No invented upgrades."),
        'saude': ("Preserve real environment and objects faithfully. No before-after medical claims, false results, procedures or patients."),
        'educacao': ("Keep the actual location, study materials and visible people unchanged. No fictional certificates or guarantees."),
        'generico': (
            "Preserve the real object's identity, color, relative proportions, "
            "brand details and number of visible items. "
        ),
    }
    fidelity = (
        ' The input may be a small, compressed or poorly lit phone photograph. '
        'Do not hallucinate missing product details or create false labels or features. '
        'If authentic detail cannot be recovered, prefer modest faithful improvement '
        'rather than invented sharpness. Keep the subject recognizable. '
    )
    note = ' Photographer observation: '+str(observation)[:450]+'. ' if observation else ''
    return base + by_sector.get(sector,by_sector['generico']) + fidelity + note + ' One single finished photograph.'

def _error(ex):
    status=getattr(ex,'status_code',None) or getattr(ex,'status',None)
    detail=str(getattr(ex,'message',None) or getattr(ex,'detail',None) or ex)
    key=os.getenv('FAL_KEY','').strip()
    if key: detail=detail.replace(key,'[CHAVE OCULTA]')
    detail=re.sub(r'https?://\S+','[URL OCULTA]',detail)
    detail=re.sub(r'data:image/[^\s]+','[IMAGEM OCULTA]',detail,flags=re.I)
    detail=re.sub(r'(?i)(bearer\s+|key\s*[:=]\s*)[A-Za-z0-9_:\-.]{10,}','[AUTENTICAÇÃO OCULTA]',detail)
    detail=re.sub(r'[A-Za-z0-9+/]{100,}={0,2}','[DADOS OCULTOS]',detail)
    detail=re.sub(r'\s+',' ',detail).strip()[:220]
    return 'Falha no GPT Image/fal.ai (%s): %s. Não repita antes de conferir o histórico de solicitações e seu saldo; uma tentativa pode ter sido cobrada.' % (f'HTTP {status}' if status else type(ex).__name__,detail)

def edit_photo(im,brand,observation='',sector='generico'):
    global SESSION_CALLS
    if not enabled(): raise RuntimeError('Edição com API desligada. Use o inicializador com consentimento.')
    preflight(1)
    with _LOCK:
        if SESSION_CALLS >= limit():raise RuntimeError('Limite de chamadas pagas alcançado.')
        SESSION_CALLS+=1  # Contar tentativa ANTES do envio; sem retry, até se houver timeout.
    _notify_attempt('edicao_fotografica')
    try:import fal_client
    except ImportError as e:raise RuntimeError('Biblioteca fal-client ausente. Execute novamente INICIAR_GPT_IMAGE_WINDOWS.bat.') from e

    src=ImageOps.exif_transpose(im).convert('RGB')
    src.thumbnail((1536,1536),Image.Resampling.LANCZOS)
    buffer=io.BytesIO();src.save(buffer,format='JPEG',quality=92)
    uri='data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii')
    prompt=make_prompt(brand,observation,sector)
    refs=[uri]  # Uma referencia: foto real; nenhum guia geometrico.
    # Official fal docs: openai/gpt-image-2.5/sunburst/edit accepts image_urls and quality, image_size, num_images.
    # 'auto' maintains source orientation; do NOT force square_hd.
    arguments={'prompt':prompt,'image_urls':refs, 'image_size':'auto', 'quality':'high',
               'num_images':1,'output_format':'png','enable_safety_checker':True}
    try:
        result=fal_client.subscribe(ENDPOINT,arguments=arguments)
    except Exception as ex:
        raise RuntimeError(_error(ex)) from None
    try:
        if not isinstance(result,dict):raise ValueError('Resposta sem JSON.')
        arr=result.get('images') or []
        if not isinstance(arr,list) or not arr:raise ValueError('Resposta não retornou images[].')
        url=str(arr[0].get('url',''))
        parsed=urlparse(url);host=(parsed.hostname or '').lower()
        # Deny arbitrary redirect, internal addresses, and untrusted hosts.
        if parsed.scheme!='https' or not (host=='fal.media' or host.endswith('.fal.media')):
            raise ValueError('URL de saída fora do armazenamento esperado da fal.ai.')
        with urlopen(Request(url,headers={'User-Agent':'StayVisionBusiness/26.0'}),timeout=55) as r:
            if r.geturl() != url:
                raise ValueError('Redirecionamento do arquivo bloqueado. Confira request no painel.')
            data=r.read(24_000_001)
        if len(data)>24_000_000:raise ValueError('Arquivo maior que 24 MB.')
        with Image.open(io.BytesIO(data)) as loaded:
            loaded.verify()
        with Image.open(io.BytesIO(data)) as loaded:
            output=ImageOps.exif_transpose(loaded).convert('RGB')
        if min(output.size)<384:raise ValueError('Saída muito pequena.')
    except Exception as ex:
        raise RuntimeError('Modelo respondeu, mas não foi possível validar/baixar a imagem (%s). Confira o histórico antes de gerar outra: a chamada pode ter sido cobrada.'%type(ex).__name__) from None
    return output, {'provider':'fal','model':ENDPOINT,'visual_style':'publicitario_premium',
                    'quality':'high','image_size':'auto','prompt_version':PROMPT_VERSION,'edit_goal':edit_goal(),
                    'prompt_sent':prompt, 'visual_category':sector,'references_used':len(refs), 'geometry_guide_used':False, 'geometry_review':'Verificar forma NATURAL, ausência de pontas artificiais, alongamento ou deformação; aprovação humana necessária',
                    'estimated_output_usd_reference':REF_IMAGE_USD,
                    'pricing_note':'Referência ilustrativa high portrait 1024x1536. Custo real varia com tamanho e tokens; ver painel fal.ai.',
                    'human_approval_required':True,'usage':{}}

# ETAPA 28: imagem publicitária original a partir de texto, ou edição com referências.
# Reutiliza exclusivamente FAL_KEY. NÃO chama outra conta OpenAI, nem GPT de texto.
TEXT_ENDPOINT = 'openai/gpt-image-2.5/sunburst/text-to-image'

def generate_visual(prompt, *, references=(), size=(1024,1024), quality='high', role='design'):
    """Uma imagem GPT Image real; nunca cair silenciosamente em mock/filtro."""
    global SESSION_CALLS
    if not enabled():raise RuntimeError('GPT Image desligado: não serão geradas artes genéricas.')
    preflight(1)
    if quality not in ('medium','high'):raise ValueError('Qualidade inválida.')
    if len(prompt)>14000 or not prompt.strip():raise ValueError('Briefing de imagem inválido.')
    if len(references)>3:raise ValueError('Muitas referências.')
    # Tomar posse de uma tentativa antes da chamada externa, sem retry.
    with _LOCK:
        if SESSION_CALLS>=limit():raise RuntimeError('Limite de tentativas autorizado esgotado.')
        SESSION_CALLS+=1
    _notify_attempt(role)
    try:import fal_client
    except ImportError as ex:raise RuntimeError('Instale fal-client pela inicialização Windows.') from ex
    image_urls=[]
    for ref in references:
        if isinstance(ref,Image.Image): im=ImageOps.exif_transpose(ref).convert('RGB')
        else:
            with Image.open(ref) as loaded: im=ImageOps.exif_transpose(loaded).convert('RGB')
        im.thumbnail((1250,1250),Image.Resampling.LANCZOS)
        b=io.BytesIO();im.save(b,format='JPEG',quality=88)
        image_urls.append('data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode('ascii'))
    endpoint=ENDPOINT if image_urls else TEXT_ENDPOINT
    args={'prompt':prompt,'image_size':{'width':size[0],'height':size[1]},
          'quality':quality,'num_images':1,'output_format':'png','enable_safety_checker':True}
    if image_urls:args['image_urls']=image_urls
    try:res=fal_client.subscribe(endpoint,arguments=args)
    except Exception as ex:raise RuntimeError(_error(ex)) from None
    try:
        images=res.get('images') if isinstance(res,dict) else None
        if not isinstance(images,list) or not images:raise ValueError('Sem imagens de saída')
        uri=str(images[0]['url']); parsed=urlparse(uri);host=(parsed.hostname or '').lower()
        if parsed.scheme!='https' or not (host=='fal.media' or host.endswith('.fal.media')):
            raise ValueError('Host não permitido')
        with urlopen(Request(uri,headers={'User-Agent':'StayVisionBusiness/28'}),timeout=65) as r:
            if r.geturl()!=uri:raise ValueError('Redirecionamento inesperado')
            data=r.read(24_000_001)
        if len(data)>24_000_000:raise ValueError('Arquivo acima de 24MB')
        with Image.open(io.BytesIO(data)) as check:check.verify()
        with Image.open(io.BytesIO(data)) as src:img=ImageOps.exif_transpose(src).convert('RGB')
        if min(img.size)<384:raise ValueError('Resolução insuficiente')
        return img,{'model':endpoint,'role':role,'quality':quality,'reference_count':len(image_urls),
                    'requested_size':list(size),'status':'completed','billing':'verificar painel fal.ai'}
    except Exception:
        raise RuntimeError('IA retornou, mas a imagem não pôde ser baixada ou validada. Verifique no painel fal.ai ANTES de repetir: pode haver cobrança.') from None
