"""Premium direto V3.3: cliente envia 1..8 fotos; UMA autorização cria TODAS as entregas.

Importação, diagnóstico e armazenamento NÃO consomem API. A produção requer Gemini
+ fal.ai e é executada em worker local (não bloqueia HTTP), sem repetição automática.
O download só aparece após auditoria de TODAS as imagens; resultados são revisão interna.
"""
from __future__ import annotations
import json, secrets, re, threading, hashlib, shutil, statistics
from pathlib import Path
from datetime import datetime,timezone
from PIL import Image

TAG=re.compile(r'^pedido-[0-9a-f]{16}$')
LOCK=threading.Lock()
RUNNING=set()
RUN_LOCK=threading.Lock()
MAX_JSON=75_000_000

def root_store():
    from app import OUT
    p=OUT/'premium_direto_v33';p.mkdir(parents=True,exist_ok=True)
    return p

def _get(job):
    if not TAG.fullmatch(str(job)):raise ValueError('Número de pedido inválido.')
    root=root_store()/job
    if not (root/'estado.json').exists():raise FileNotFoundError('Pedido Premium não encontrado.')
    return root

def _read(root):return json.loads((root/'estado.json').read_text(encoding='utf-8'))

def _save(root,state):
    target=root/'estado.json';tmp=root/'estado.json.tmp'
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(target)

def _now():
    return datetime.now(timezone.utc)

def _clock(iso):
    try:
        dt=datetime.fromisoformat(iso)
        return dt.astimezone(timezone.utc).timestamp()
    except (ValueError,TypeError,AttributeError):
        return None

def _label(role, photos=8):
    """Human-readable progress labels; no estimates are invented from roles."""
    role=str(role or '')
    match=re.fullmatch(r'(highlight|feed|story|extra)_(\d+)', role)
    if role=='edicao_fotografica':return 'Aprimorando as fotos dos produtos'
    if role=='profile_logo':return 'Criando logo e foto de perfil'
    if match:
        kind,idx=match.group(1),int(match.group(2))
        names={'highlight':('Criando capas de destaques',5),'feed':('Criando publicações do feed',6),
               'story':('Criando stories e status',4),'extra':('Criando artes extras Premium',3)}
        text,total=names[kind]
        return f'{text} · {idx}/{total}'
    return 'Gerando arte: '+role.replace('_',' ')[:50]

def _public(state):
    p={k:state.get(k) for k in ('id','brand','activity','photos','expected_attempts','attempts_reserved','status','last_action','errors','diagnoses','created_utc')}
    p['plan']=state.get('plan','premium')
    status=state.get('status','')
    total=max(1,int(state.get('expected_attempts') or 1))
    reserved=min(total,max(0,int(state.get('attempts_reserved') or 0)))
    completed=min(reserved,max(0,int(state.get('attempts_completed') or 0)))
    start=_clock(state.get('started_utc'))
    now=(_clock(state.get('finished_utc')) if status in ('REVISAO_NECESSARIA','INTERROMPIDO_SEM_REPETICAO') else None) or _now().timestamp()
    # Histórico de versões anteriores só conta reservas; NÃO fingir que foram concluidas.
    has_metrics=bool(start is not None)
    p['attempts_completed']=completed if has_metrics else None
    p['phase']=state.get('phase') or ('Preparando briefing e referências' if status=='EM_PRODUCAO' else '')
    p['elapsed_seconds']=max(0,round(now-start)) if has_metrics else None
    p['progress_percent']=100 if status=='REVISAO_NECESSARIA' else (min(96,round(95*completed/total)) if has_metrics else None)
    p['eta_low_seconds']=None
    p['eta_high_seconds']=None
    # ETA com base em durações REALMENTE observadas e salvas no disco. Ajusta a cada peça.
    durations=[float(x) for x in state.get('call_durations_seconds',[]) if isinstance(x,(int,float)) and 1<=x<=3600]
    if status=='EM_PRODUCAO' and has_metrics and len(durations)>=2 and completed<total:
        recent=durations[-8:]
        avg=statistics.median(recent) if len(recent)>=4 else statistics.mean(recent)
        active_since=_clock(state.get('active_attempt_utc'))
        active_for=max(0,now-active_since) if active_since else 0
        left=total-completed
        # Não contar duas vezes o tempo já decorrido na chamada ativa.
        predicted=max(avg*0.35, avg-active_for) + max(0,left-1)*avg + 25
        p['eta_low_seconds']=int(max(60,min(86400,predicted*0.70)))
        p['eta_high_seconds']=int(max(p['eta_low_seconds']+30,min(86400,predicted*1.55)))
    if status=='REVISAO_NECESSARIA':
        p['download']='/download/'+state['id']+'.zip'
        p['review']='/revisar?job='+state['id']
    return p

def _reply(h,obj,code=200):h._send(json.dumps(obj,ensure_ascii=False),code)

def _body(h,limit=MAX_JSON):
    if not h.headers.get('Content-Type','').lower().startswith('application/json'):
        raise ValueError('Envie JSON.')
    origin=h.headers.get('Origin','')
    if origin and origin not in ('http://127.0.0.1:8786','http://localhost:8786'):
        raise ValueError('Origem não autorizada.')
    n=int(h.headers.get('Content-Length','0'))
    if not 2<=n<=limit:raise ValueError('Envio muito grande. Máximo de 75 MB por pedido.')
    return json.loads(h.rfile.read(n))

def prepare_from_data(data):
    """Valida e grava um pedido SEM chamadas de IA ou cobranças.

    Reutilizado tanto pelo Estúdio quanto pelo fluxo comercial de testes.
    """
    root=None
    try:
        from photo_adapt import from_data_url,to_jpeg
        from photo_quality import diagnose
        brand=' '.join(str(data.get('brand') or '').split())[:45]
        activity=' '.join(str(data.get('activity') or '').split())[:100]
        instagram=str(data.get('instagram') or '').strip()[:100]
        contact=str(data.get('contact') or '').strip()[:100]
        photos=data.get('images')
        plan=str(data.get('plan') or 'premium')
        from engine import PLANS,count_visual_calls
        if plan not in PLANS:raise ValueError('Plano desconhecido.')
        if len(brand)<2:raise ValueError('Informe o nome da empresa.')
        if not instagram or not contact:raise ValueError('Informe Instagram e contato real da empresa.')
        if not isinstance(photos,list):raise ValueError('Fotos inválidas.')
        if plan=='fotos' and not 1<=len(photos)<=6:raise ValueError('Fotos Business: envie de 1 a 6 fotografias.')
        if plan=='perfil' and len(photos)>6:raise ValueError('Perfil Express: no máximo 6 fotografias opcionais como referência.')
        if plan=='vitrine' and not 1<=len(photos)<=6:raise ValueError('Vitrine Digital: envie de 1 a 6 fotos de referência.')
        if plan=='premium' and not 1<=len(photos)<=8:raise ValueError('Feed Premium: envie de 1 a 8 fotografias.')
        loaded=[];diagnoses=[];fingerprints=set()
        for i,part in enumerate(photos,1):
            if not isinstance(part,dict):raise ValueError(f'Foto {i} inválida.')
            im=from_data_url(part.get('data'),max_side=2400)
            digest=hashlib.sha256(im.resize((48,48),Image.Resampling.LANCZOS).tobytes()).hexdigest()
            if digest in fingerprints:raise ValueError(f'Foto {i} duplicada: envie fotografias diferentes.')
            fingerprints.add(digest)
            diagnoses.append({'photo_number':i,**diagnose(im)})
            loaded.append(im)
        logo=None
        if data.get('logo_image') is not None:
            item=data['logo_image']
            if not isinstance(item,dict):raise ValueError('Arquivo de logo inválido.')
            logo=from_data_url(item.get('data'),logo=True)
        job='pedido-'+secrets.token_hex(8)
        root=root_store()/job;root.mkdir(parents=True)
        from app import OUT
        in_dir=OUT/job/'input';in_dir.mkdir(parents=True)
        for i,im in enumerate(loaded,1):
            to_jpeg(im,in_dir/f'original_{i:02d}.jpg')
        if logo is not None:to_jpeg(logo,in_dir/'logo_existente.jpg')
        state={'id':job,'plan':plan,'brand':brand,'activity':activity,'instagram':instagram,'contact':contact,
               'photos':len(loaded),'expected_attempts':count_visual_calls(plan,len(loaded)),
               'attempts_reserved':0,'status':'PREPARADO_SEM_CREDITOS',
               'last_action':'Fotos recebidas, diagnóstico realizado; nenhuma API acionada',
               'errors':[],'diagnoses':diagnoses,'has_logo':logo is not None,
               'created_utc':datetime.now(timezone.utc).isoformat(),
               'manual_approval_required':True,'auto_retry':False}
        _save(root,state)
        return state
    except Exception:
        if root and root.exists():
            from app import OUT
            shutil.rmtree(root,ignore_errors=True)
            shutil.rmtree(OUT/root.name,ignore_errors=True)
        raise

def import_handler(h):
    try:
        data=_body(h)
        state=prepare_from_data(data)
        _reply(h,{'ok':True,**_public(state),'message':'Premium preparado sem créditos. Fotos serão editadas automaticamente quando você autorizar o lote inteiro.'})
    except (ValueError,TypeError,KeyError,OverflowError,MemoryError) as ex:
        _reply(h,{'error':str(ex)},400)
    except Exception as ex:
        print('[premium direto] import:',type(ex).__name__,str(ex)[:130])
        _reply(h,{'error':'Falha ao preparar as fotos. Nenhum crédito foi consumido nesta importação.'},500)

def _run(root):
    from app import OUT,audit_artifacts
    from engine import build
    from image_ai import set_attempt_hook
    st=_read(root);job=st['id']
    def reserved(role):
        state=_read(root)
        now=_now()
        # Só é possível iniciar a próxima arte se a chamada anterior retornou
        # e a etapa correspondente do motor terminou sem erro.
        if state.get('active_attempt_utc') and state['attempts_reserved'] > state.get('attempts_completed',0):
            started=_clock(state['active_attempt_utc'])
            duration=max(0.001,now.timestamp()-started) if started else 0
            if duration:
                durations=state.setdefault('call_durations_seconds',[])
                durations.append(round(duration,2))
                state['call_durations_seconds']=durations[-20:]
            state['attempts_completed']=state['attempts_reserved']
        state['attempts_reserved']+=1
        state['active_attempt_utc']=now.isoformat()
        state['phase']=_label(role,state.get('photos',8))
        state['last_action']=f'Tentativa {state["attempts_reserved"]}/{state["expected_attempts"]} iniciada: {role}'
        _save(root,state) # ANTES da chamada fal.ai: auditoria / sem auto-retry
    try:
        set_attempt_hook(reserved)
        inp=OUT/job/'input'
        photos=[inp/f'original_{i:02d}.jpg' for i in range(1,st['photos']+1)]
        logo=inp/'logo_existente.jpg' if st['has_logo'] else None
        # Cada plano gera apenas os entregáveis correspondentes e passa pela auditoria.
        plan=st.get('plan','premium')
        archive=build(OUT/job/'entrega',plan,st['brand'],st['instagram'],st['contact'],photos,
                      sample_only=False,activity=st['activity'],logo_reference_path=logo,
                      preserve_existing_logo=bool(logo))
        # A última chamada terminou e as peças foram salvas pelo motor.
        state=_read(root)
        if state.get('attempts_reserved',0)>state.get('attempts_completed',0):
            began=_clock(state.get('active_attempt_utc'))
            if began:
                durations=state.setdefault('call_durations_seconds',[])
                durations.append(round(max(0.001,_now().timestamp()-began),2))
                state['call_durations_seconds']=durations[-20:]
            state['attempts_completed']=state['attempts_reserved']
        state['active_attempt_utc']=None
        state['phase']='Conferindo os arquivos e montando a entrega'
        _save(root,state)
        info=json.loads((OUT/job/'entrega'/'INFO_PEDIDO.json').read_text(encoding='utf-8'))
        problems=audit_artifacts(OUT/job/'entrega',plan,info)
        if problems:raise RuntimeError('Auditoria incompleta: '+'; '.join(problems[:8]))
        # Relatório complementar: ainda exige verificação visual humana.
        (OUT/job/'entrega'/'LEIA_ENTREGA_STAYVISION.txt').write_text(
            f'Plano: {plan}. Fotos de referência recebidas: {st["photos"]}.\n'
            'Tratamento individual das fotos: somente nos planos Fotos Business e Feed Premium.\n'
            'Identidade, textos e publicações: conforme o plano. Revisão humana antes da entrega.\n'
            'Sem Pix, cobranças ou publicação automáticos.\n',encoding='utf-8')
        # Incorporar relatório adicional antes de liberar download.
        import zipfile
        final=OUT/(job+'.zip');tmp=OUT/(job+'.zip.tmp')
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
            for file in sorted((OUT/job/'entrega').rglob('*')):
                if file.is_file():z.write(file,file.relative_to(OUT/job/'entrega'))
        tmp.replace(final)
        state=_read(root);state.update({'status':'REVISAO_NECESSARIA','phase':'Pronto para revisão humana',
            'finished_utc':_now().isoformat(),
            'last_action':'Pacote final completo, auditoria técnica passou; revisão visual obrigatória'})
        _save(root,state)
        archive.unlink(missing_ok=True)
    except Exception as ex:
        state=_read(root)
        state['status']='INTERROMPIDO_SEM_REPETICAO'
        state['finished_utc']=_now().isoformat()
        state['phase']='Produção interrompida — verificar antes de tentar novamente'
        state['errors'].append(str(ex)[:300])
        state['last_action']='Interrompido. Verificar histórico da fal.ai antes de iniciar novo pedido.'
        _save(root,state)
        print('[premium direto] SEM REPETIÇÃO:',type(ex).__name__,str(ex)[:200])
    finally:
        set_attempt_hook(None)
        with RUN_LOCK:RUNNING.discard(job)
        LOCK.release()

def start_prepared(job):
    """Operator-only entry point. Never call before verified payment in production.

    This local V3.7 has only explicit SIMULATED payment, never real approval.
    """
    taken=False
    try:
        root=_get(str(job))
        st=_read(root)
        if st['status']!='PREPARADO_SEM_CREDITOS':raise ValueError('Pedido já foi iniciado. Não repetir tentativas.')
        from creative_ai import available,mode
        from image_ai import enabled,preflight
        if not available() or mode()=='off':raise ValueError('Gemini não habilitado. Reinicie usando opção 8 com as duas chaves.')
        if not enabled():raise ValueError('fal.ai não habilitada. Reinicie usando opção 8.')
        from path_safety import require_safe_output
        require_safe_output()
        preflight(st['expected_attempts'])
        if not LOCK.acquire(blocking=False):raise ValueError('Outra produção está ativa. Não reenvie.')
        taken=True
        with RUN_LOCK:
            st=_read(root)
            if st['status']!='PREPARADO_SEM_CREDITOS':raise ValueError('Pedido já iniciado.')
            st['status']='EM_PRODUCAO';st['last_action']='Iniciando briefing Gemini e edição automática'
            st['started_utc']=_now().isoformat()
            st['attempts_completed']=0
            st['active_attempt_utc']=None
            st['call_durations_seconds']=[]
            st['phase']='Analisando a marca e preparando o briefing'
            _save(root,st);RUNNING.add(st['id'])
        threading.Thread(target=_run,args=(root,),daemon=True).start()
        taken=False
        return _public(st)
    finally:
        if taken:LOCK.release()

def finish_handler(h):
    try:
        data=_body(h,5000)
        if data.get('confirm')!='AUTORIZO_PREMIUM_COMPLETO':raise ValueError('Falta autorização explícita para o Premium.')
        job=str(data.get('id',''))
        # Do not bypass payment for customer-originated orders.
        from commerce_flow import is_commercial_job, is_paid
        if is_commercial_job(job):
            raise ValueError('Pedido comercial: início permitido somente no painel interno com código do operador.')
        st=start_prepared(job)
        _reply(h,{'ok':True,**st,'message':'Premium iniciado. Acompanhe o mesmo ID; não reenvie arquivos.'},202)
    except FileNotFoundError:_reply(h,{'error':'Pedido não encontrado.'},404)
    except (ValueError,TypeError,RuntimeError) as ex:_reply(h,{'error':str(ex)},400)

def status_handler(h,job):
    try:
        root=_get(job);st=_read(root)
        with RUN_LOCK:active=job in RUNNING
        if st['status']=='EM_PRODUCAO' and not active:
            st['status']='INTERROMPIDO_SEM_REPETICAO'
            st['finished_utc']=_now().isoformat()
            st['phase']='O aplicativo foi reiniciado — confira as chamadas antes de continuar'
            st['errors'].append('O servidor foi interrompido. Não reiniciar chamadas pagas sem conferir o histórico.')
            _save(root,st)
        _reply(h,{'ok':True,**_public(st)})
    except (ValueError,FileNotFoundError):_reply(h,{'error':'Pedido Premium não localizado.'},404)
