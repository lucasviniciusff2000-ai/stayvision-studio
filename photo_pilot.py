"""V3.2: teste pago de UMA foto, com importação gratuita e autorizações auditadas.

Servidor local. Nunca retoma/repete uma chamada fal.ai após falha ou reinício.
"""
from __future__ import annotations
import json, io, re, secrets, threading, zipfile, hashlib
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image,ImageOps

JOB=re.compile(r'^piloto-[a-f0-9]{16}$')
LOCK=threading.Lock()
ACTIVE=set()
ACTIVE_LOCK=threading.Lock()


def store():
    from app import OUT
    p=OUT/'pilotos_fotograficos';p.mkdir(parents=True,exist_ok=True)
    return p


def path(job):
    if not JOB.fullmatch(str(job)):raise ValueError('Código de piloto inválido.')
    root=store()/job
    if not (root/'estado.json').is_file():raise FileNotFoundError('Piloto não encontrado.')
    return root


def read(root):return json.loads((root/'estado.json').read_text(encoding='utf8'))


def write(root,st):
    file=root/'estado.json';tmp=file.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(st,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(file)


def public(st):
    keep=('id','brand','activity','status','attempts','errors','diagnosis','created_utc')
    r={key:st.get(key) for key in keep}
    if st['status']=='REVISAO_NECESSARIA':r['download']='/download/'+st['id']+'.zip'
    return r


def request_body(server):
    if not server.headers.get('Content-Type','').lower().startswith('application/json'):
        raise ValueError('Envie JSON.')
    origin=server.headers.get('Origin','')
    if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
        raise ValueError('Origem inválida.')
    n=int(server.headers.get('Content-Length','0'))
    if not 2<=n<=40_000_000:raise ValueError('Requisição excede 40 MB.')
    return json.loads(server.rfile.read(n))


def reply(server,body,code=200):server._send(json.dumps(body,ensure_ascii=False),code)


def import_handler(server):
    try:
        data=request_body(server)
        brand=' '.join(str(data.get('brand') or '').split())[:75]
        activity=' '.join(str(data.get('activity') or '').split())[:100]
        if len(brand)<2:raise ValueError('Informe a marca.')
        photo=data.get('image')
        if not isinstance(photo,dict):raise ValueError('Selecione uma fotografia.')
        from photo_adapt import from_data_url
        from photo_quality import diagnose
        image=from_data_url(photo.get('data'))
        diag=diagnose(image)
        root=store()/('piloto-'+secrets.token_hex(8))
        root.mkdir(parents=True)
        image.save(root/'original.jpg',quality=94,subsampling=0,optimize=True)
        st={'id':root.name,'brand':brand,'activity':activity,'status':'PREPARADO',
            'attempts':0,'errors':[],'diagnosis':diag,
            'created_utc':datetime.now(timezone.utc).isoformat(),
            'original_sha256':hashlib.sha256((root/'original.jpg').read_bytes()).hexdigest(),
            'approval_required':True,'expected_paid_attempts':1}
        write(root,st)
        reply(server,{'ok':True,**public(st),'notice':'Análise concluída sem créditos. Chamada paga ainda NÃO iniciada.'})
    except (ValueError,TypeError,OverflowError,KeyError) as ex:reply(server,{'error':str(ex)},400)
    except Exception as ex:
        print('[piloto] Importação:',repr(ex));reply(server,{'error':'Falha ao importar a fotografia.'},500)


def _sector(activity):
    from fotos_complete import _sector
    return _sector(activity)


def _process(root):
    from engine import load_photo,save_jpg,photo_comparison
    from image_ai import edit_photo,model
    from photo_quality import prepare_reference,inspect_result,save_report
    st=read(root)
    from app import OUT
    try:
        original=load_photo(root/'original.jpg')
        prepared,prep=prepare_reference(original,st['diagnosis'])
        delivery=root/'entrega';qa=delivery/'05_controle_de_qualidade';qa.mkdir(parents=True,exist_ok=True)
        (delivery/'00_originais').mkdir(exist_ok=True)
        (delivery/'01_fotos_tratadas').mkdir(exist_ok=True)
        save_jpg(original,delivery/'00_originais/original_01.jpg')
        save_jpg(prepared,qa/'referencia_preparada.jpg')
        note='Fotografia de cliente, preservar identidade e conteúdo. '+' '.join(st['diagnosis']['warnings'])
        # A única chamada autorizada. Tentativa já reservada no estado.
        image,meta=edit_photo(prepared,st['brand'],note,_sector(st['activity']))
        save_jpg(image,delivery/'01_fotos_tratadas/foto_profissional_01.jpg')
        photo_comparison(original,image,qa/'antes_depois_01.jpg')
        quality=inspect_result(original,image)
        save_report(qa/'qualidade_foto_01.json',{'preparation':prep,'final_check':quality,'model':model(),
                    'model_metadata':meta,'charged_attempts_reserved':1})
        (qa/'LEIA.txt').write_text('PILOTO DE UMA FOTO: revisão humana obrigatória.\n'
            'Pré-tratamento sem IA; retoque final com uma tentativa fal.ai.\n'
            'Compare produto, rótulos, rostos, texturas e quantidade.\n'
            'NÃO é aprovação de plano Premium ou prova de recuperação irreversível.\n',encoding='utf8')
        (delivery/'INFO_PILOTO.json').write_text(json.dumps({'plan':'PILOTO_INTERNO_UMA_FOTO','brand':st['brand'],
           'attempts_reserved':1,'image_provider':model(),'quality_status':quality['status'],
           'not_full_paid_plan':True,'human_approval_required':True},ensure_ascii=False,indent=2),encoding='utf8')
        archive=OUT/(st['id']+'.zip');tmp=archive.with_suffix('.zip.tmp')
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as zipped:
            for file in sorted(delivery.rglob('*')):
                if file.is_file():zipped.write(file,file.relative_to(delivery))
        tmp.replace(archive)
        st=read(root);st['status']='REVISAO_NECESSARIA';st['quality_status']=quality['status'];write(root,st)
    except Exception as ex:
        st=read(root);st['status']='INTERROMPIDO_SEM_REPETICAO';st['errors'].append(str(ex)[:240]);write(root,st)
        print('[piloto] Falha, sem repetir tentativa:',type(ex).__name__)
    finally:
        with ACTIVE_LOCK:ACTIVE.discard(root.name)
        LOCK.release()


def finish_handler(server):
    locked=False
    try:
        data=request_body(server)
        if data.get('confirm')!='AUTORIZO_UMA_FOTO':raise ValueError('Autorização explícita ausente.')
        root=path(data.get('id'))
        st=read(root)
        if st['status']!='PREPARADO':raise ValueError('Piloto já iniciado ou concluído. Não repetir.')
        from image_ai import enabled,preflight
        if not enabled():raise ValueError('Ligue o modo fal.ai com uma tentativa autorizada.')
        from path_safety import require_safe_output
        require_safe_output()
        preflight(1)
        if not LOCK.acquire(blocking=False):raise ValueError('Outro teste está sendo processado.')
        locked=True
        st=read(root)
        if st['status']!='PREPARADO':raise ValueError('Este piloto já foi iniciado.')
        st['status']='EM_PRODUCAO';st['attempts']=1
        write(root,st)
        with ACTIVE_LOCK:ACTIVE.add(root.name)
        threading.Thread(target=_process,args=(root,),daemon=True).start()
        locked=False
        reply(server,{'ok':True,**public(st),'message':'Uma tentativa reservada, sem retentativas.'},202)
    except (FileNotFoundError,ValueError,TypeError,RuntimeError,OverflowError) as ex:
        reply(server,{'error':str(ex)},400)
    except Exception as ex:
        print('[piloto] Início:',type(ex).__name__)
        reply(server,{'error':'Falha ao iniciar teste; confira o histórico antes de repetir.'},500)
    finally:
        if locked:LOCK.release()


def status_handler(server,job):
    try:
        root=path(job);st=read(root)
        with ACTIVE_LOCK:active=job in ACTIVE
        if st['status']=='EM_PRODUCAO' and not active:
            st['status']='INTERROMPIDO_SEM_REPETICAO'
            st['errors'].append('Processo encerrado; confira faturamento da fal.ai antes de novo pedido.')
            write(root,st)
        reply(server,{'ok':True,**public(st)})
    except (ValueError,FileNotFoundError):reply(server,{'error':'Piloto não encontrado.'},404)
