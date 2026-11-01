"""Fase 2: briefing em separado, aprovação explícita e UMA amostra de Perfil Express.
Somente localhost. Não expõe chaves, não usa pix, não faz retry. Gemini e fal.ai
podem cobrar conforme conta; launcher começa com ambos desligados por padrão.
"""
from __future__ import annotations
import base64, io, json, os, re, secrets
from pathlib import Path
from PIL import Image,ImageOps,UnidentifiedImageError

MAX_JSON=39_000_000
DATA_RE=re.compile(r'^data:image/(?:jpeg|jpg|png|webp);base64,',re.I)
ID_RE=re.compile(r'^[a-f0-9]{20}$')


def _payload(handler, max_n=MAX_JSON):
    origin=handler.headers.get('Origin','')
    if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
        raise ValueError('Origem não autorizada.')
    if not handler.headers.get('Content-Type','').lower().startswith('application/json'):
        raise ValueError('Use application/json.')
    n=int(handler.headers.get('Content-Length','0'))
    if not 3<=n<=max_n:raise ValueError('Tamanho do pedido inválido.')
    obj=json.loads(handler.rfile.read(n))
    if not isinstance(obj,dict):raise ValueError('Dados inválidos.')
    return obj


def _store():
    from app import OUT
    d=OUT/'fase2_preflight'; d.mkdir(parents=True,exist_ok=True)
    return d


def _save_image(data, path):
    from photo_adapt import from_data_url, to_jpeg
    to_jpeg(from_data_url(data,max_side=2400,logo=True),path)


def create_brief_handler(h):
    folder=None
    try:
        from engine import create_brief,normalize_contact,normalize_instagram,limit
        from creative_ai import create,available,mode
        o=_payload(h)
        brand=limit(o.get('brand'),45)
        activity=limit(o.get('activity'),100)
        if len(brand)<2:raise ValueError('Informe o nome da marca.')
        if len(activity)<3:raise ValueError('Informe o ramo real da empresa para evitar confundir o negócio.')
        ig=normalize_instagram(o.get('instagram'))
        contact=normalize_contact(o.get('contact'))
        pictures=o.get('images')
        if not isinstance(pictures,list) or len(pictures)>1:raise ValueError('Envie no máximo um logotipo neste teste.')
        name=secrets.token_hex(10)
        folder=_store()/name;folder.mkdir()
        image=folder/'referencia.jpg'
        has_logo=bool(pictures)
        if has_logo:_save_image(pictures[0].get('data'),image)
        references=[image] if has_logo else []
        offline=create_brief(brand,ig,contact,references,activity)
        from image_ai import enabled as fal_enabled
        if mode()=='off' or not available():
            # O usuário sabe claramente que este passo não analisou pixels.
            result={'provider':'local','model':'regras_sem_IA','data':offline,'notes':['Modo gratuito: sem leitura real dos pixels nem geração de imagem.'],'usage':{}}
        else:
            creative=create(brand,ig,contact,references,offline,activity=activity)
            if creative.provider!='gemini':raise RuntimeError('Gemini falhou. Não vamos autorizar geração paga.')
            result={'provider':creative.provider,'model':creative.model,'data':creative.data,'notes':creative.notes,'usage':creative.usage}
        saved={'name':name,'brand':brand,'instagram':ig,'contact':contact,'activity':activity,
               'creative':result,'photo':'referencia.jpg' if has_logo else None,'preserve_existing_logo':has_logo,'sample_generated':False}
        (folder/'brief.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
        data=result['data']; flags=data.get('quality_flags') or []
        reply={'ok':True,'id':name,'provider':result['provider'],'model':result['model'],
            'image_ai_enabled':fal_enabled(),'notes':result['notes'],
            'brief':{'segment':data.get('segment'),'sector':data.get('sector'),
                     'tagline':data.get('tagline'),'visual_style':data.get('visual_style',''),
                     'logo_symbol':data.get('logo_symbol',''),
                     'accent':data.get('accent'), 'highlights':data.get('highlights',[]),
                     'highlight_concepts':data.get('highlight_concepts',[]),
                     'uncertainties':data.get('uncertainties',[]),
                     'flags':flags,'warnings':data.get('quality_warnings',[]),'brand_mismatch_review':data.get('brand_mismatch_review',False)},
             'message':'Briefing Gemini: revisar ANTES de liberar uma imagem paga.' if result['provider']=='gemini' else 'Conferência local, sem IA. Não habilita geração.'}
        h._send(json.dumps(reply,ensure_ascii=False))
    except (ValueError,TypeError,KeyError,OverflowError) as e:
        if folder and folder.exists():__import__('shutil').rmtree(folder,ignore_errors=True)
        h._send(json.dumps({'error':str(e)},ensure_ascii=False),400)
    except RuntimeError as e:
        if folder and folder.exists():__import__('shutil').rmtree(folder,ignore_errors=True)
        h._send(json.dumps({'error':str(e)},ensure_ascii=False),503)
    except Exception as ex:
        if folder and folder.exists():__import__('shutil').rmtree(folder,ignore_errors=True)
        print('FASE2 BRIEF ERROR:',type(ex).__name__)
        h._send('{"error":"Falha interna no briefing."}',500)



def last_brief_handler(h):
    """Recupera briefing local existente para a mesma marca, sem chamar API.

    Somente a sessão local. Não consome cota nem gera imagem.
    """
    try:
        from urllib.parse import parse_qs, urlparse
        brand=parse_qs(urlparse(h.path).query).get('brand',[''])[0].strip().casefold()
        if len(brand)<2 or len(brand)>45:
            raise ValueError('Informe o nome da empresa para recuperar o briefing.')
        root=_store()
        for folder in sorted(root.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True):
            if not folder.is_dir() or not ID_RE.fullmatch(folder.name):continue
            f=folder/'brief.json'
            if not f.is_file():continue
            try:doc=json.loads(f.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            if doc.get('brand','').strip().casefold()!=brand:continue
            if doc.get('sample_generated'):continue
            creative=doc.get('creative') or {}
            if creative.get('provider')!='gemini':continue
            direction=creative.get('data') or {}
            flags=direction.get('quality_flags') or []
            from image_ai import enabled as fal_enabled, remaining
            h._send(json.dumps({
                'ok':True,'id':folder.name,'provider':'gemini','model':creative.get('model'),
                'image_ai_enabled':fal_enabled(),'images_remaining':remaining(),
                'recovered':True,'brand':doc['brand'],'activity':doc.get('activity',''),
                'instagram':doc.get('instagram',''),'contact':doc.get('contact',''),
                'has_logo':bool(doc.get('photo')),
                'brief':{'segment':direction.get('segment'),'sector':direction.get('sector'),
                         'tagline':direction.get('tagline'),'visual_style':direction.get('visual_style',''),
                         'logo_symbol':direction.get('logo_symbol',''),'accent':direction.get('accent'),
                         'highlights':direction.get('highlights',[]),'highlight_concepts':direction.get('highlight_concepts',[]),
                         'uncertainties':direction.get('uncertainties',[]),
                         'flags':flags,'warnings':direction.get('quality_warnings',[]),'brand_mismatch_review':direction.get('brand_mismatch_review',False)}
            },ensure_ascii=False))
            return
        h._send(json.dumps({'error':'Nenhum briefing Gemini pendente encontrado para esta marca. Use Conferir proposta.'},ensure_ascii=False),404)
    except ValueError as ex:
        h._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
    except Exception as ex:
        print('FASE2 RECOVER ERROR:',type(ex).__name__)
        h._send('{"error":"Falha ao recuperar briefing local."}',500)



def recheck_brief_handler(h):
    """Deterministic local quality recheck; no Gemini/fal.ai calls, no credit use.
    A saved Gemini brief is required; this cannot upgrade a local preview into Gemini.
    """
    try:
        o=_payload(h,max_n=8000)
        name=str(o.get('id',''))
        if not ID_RE.fullmatch(name): raise ValueError('Identificador do briefing inválido.')
        folder=(_store()/name).resolve()
        if not folder.is_relative_to(_store().resolve()) or not (folder/'brief.json').is_file():
            raise ValueError('Briefing salvo não encontrado. Recupere o último briefing.')
        saved=folder/'brief.json'
        doc=json.loads(saved.read_text(encoding='utf-8'))
        if doc.get('sample_generated'):
            raise ValueError('Este briefing já iniciou uma amostra; não repetir a chamada paga.')
        if (doc.get('creative') or {}).get('provider')!='gemini':
            raise ValueError('Apenas um briefing já concluído pelo Gemini pode ser revalidado.')
        from quality_gate import repair
        from image_ai import enabled as fal_enabled,remaining
        direction=doc['creative']['data']
        # Correct only contradictions in creative copy; never edit photographic observations.
        direction, warnings=repair(doc['brand'],direction)
        dropped=False
        if o.get('remove_reference') is True:
            if not doc.get('photo'):
                raise ValueError('Não há logotipo anexado para descartar.')
            if o.get('confirm')!='DESCARTAR_REFERENCIA_INCORRETA':
                raise ValueError('Confirme que a imagem NÃO é da empresa antes de descartá-la.')
            doc['photo']=None
            doc['preserve_existing_logo']=False
            dropped=True
        # If the unrelated source is explicitly removed, the brand direction can be used
        # without presenting the original unrelated photo as an authentic logo.
        if not doc.get('photo'):
            direction['brand_mismatch_review']=False
            direction['quality_flags']=[x for x in (direction.get('quality_flags') or [])
                if not str(x).startswith('A imagem anexada pode pertencer')]
            if dropped: direction.setdefault('quality_warnings',[]).append('Referência incompatível descartada pelo operador; a nova arte será original.')
        doc['creative']['data']=direction
        existing=doc['creative'].get('notes') or []
        doc['creative']['notes']=list(dict.fromkeys(existing + (direction.get('quality_warnings') or [])))[:50]
        saved.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
        h._send(json.dumps({'ok':True,'id':name,'provider':'gemini', 'model':doc['creative']['model'],
            'brand':doc['brand'],'activity':doc.get('activity',''),
            'has_logo':bool(doc.get('photo')),'image_ai_enabled':fal_enabled(),
            'images_remaining':remaining(),
            'rechecked':True,'dropped_reference':dropped,
            'brief':{'segment':direction.get('segment'),'sector':direction.get('sector'),
                     'tagline':direction.get('tagline'), 'visual_style':direction.get('visual_style',''),
                     'logo_symbol':direction.get('logo_symbol',''), 'accent':direction.get('accent'),
                     'highlights':direction.get('highlights',[]),
                     'highlight_concepts':direction.get('highlight_concepts',[]),
                     'uncertainties':direction.get('uncertainties',[]),
                     'flags':direction.get('quality_flags',[]),
                     'warnings':direction.get('quality_warnings',[]),
                     'brand_mismatch_review':direction.get('brand_mismatch_review',False)}
        },ensure_ascii=False))
    except (ValueError,KeyError,TypeError) as ex:
        h._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
    except Exception as ex:
        print('FASE2 RECHECK ERROR:',type(ex).__name__)
        h._send(json.dumps({'error':'Erro interno ao revalidar o briefing salvo.'},ensure_ascii=False),500)


def sample_handler(h):
    try:
        o=_payload(h,max_n=8000)
        name=str(o.get('id',''))
        if not ID_RE.fullmatch(name):raise ValueError('Identificador inválido.')
        if o.get('confirm')!='GERAR_UMA_IMAGEM':raise ValueError('Confirmação explícita ausente.')
        folder=(_store()/name).resolve()
        if not folder.is_relative_to(_store().resolve()) or not (folder/'brief.json').exists():raise ValueError('Briefing inexistente.')
        doc=json.loads((folder/'brief.json').read_text(encoding='utf-8'))
        if doc.get('sample_generated'):raise ValueError('Amostra já utilizada. Não repetiremos a chamada.')
        creative=doc['creative']
        if creative['provider']!='gemini':raise ValueError('Reprovado: primeiro faça o briefing real com Gemini.')
        direction=creative['data']
        if direction.get('brand_mismatch_review') or direction.get('quality_flags'):
            raise ValueError('Briefing com alertas de coerência: corrija antes de consumir créditos.')
        from image_ai import enabled,preflight
        if not enabled():raise RuntimeError('Fal.ai desligada: nenhuma geração foi realizada.')
        preflight(1)
        # Reserva o pedido ANTES de chamar terceiros. Se houver timeout, não retry automático.
        doc['sample_generated']=True
        (folder/'brief.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
        from creative_ai import CreativeResult
        from engine import build
        from app import OUT
        job='pedido-'+secrets.token_hex(8)
        target=OUT/job/'entrega';target.mkdir(parents=True,exist_ok=True)
        saved_creative=CreativeResult(direction,'gemini',creative['model'],creative['notes'],creative.get('usage',{}))
        arch=build(target,'perfil',doc['brand'],doc['instagram'],doc['contact'],[folder/doc['photo']] if doc.get('photo') else [],
                   sample_only=True,activity=doc['activity'],preapproved_creative=saved_creative,preserve_existing_logo=doc.get('preserve_existing_logo',False))
        (OUT/(job+'.zip')).write_bytes(arch.read_bytes())
        h._send(json.dumps({'ok':True,'job':job,'download':'/download/'+job+'.zip',
                            'review':'/revisar?job='+job,
                            'message':'Amostra produzida: 1 arte. Não é um pacote Perfil Express completo.'},ensure_ascii=False))
    except (ValueError,KeyError,TypeError) as ex:
        h._send(json.dumps({'error':str(ex)},ensure_ascii=False),400)
    except RuntimeError as ex:
        h._send(json.dumps({'error':str(ex)},ensure_ascii=False),503)
    except Exception as ex:
        print('FASE2 SAMPLE ERROR:',type(ex).__name__)
        h._send('{"error":"Falha interna. Uma chamada pode ter sido cobrada. Confira painel fal.ai antes de tentar novamente."}',500)
