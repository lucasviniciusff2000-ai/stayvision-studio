"""Galeria de entrega PRIVADA em servidor local, sem publicacao online.

Acesso a arquivos exige token aleatorio criptograficamente forte, pedido aprovado
pela revisao interna e caminho de midia explicitamente permitido. Nao inclui dados
de clientes externos ao pedido. Este modulo NAO torna o aplicativo apto a producao web.
"""
from __future__ import annotations
import datetime as dt
import json
import mimetypes
import re
import secrets
from pathlib import Path
from urllib.parse import quote

TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{40,80}$')
FILE_TYPES = {
 'preview_perfil': ('06_previas_instagram/perfil_completo_1080x1920.png','Perfil completo — simulação'),
 'preview_feed': ('06_previas_instagram/grade_publicacoes_1080x1350.png','Grade de publicações — simulação'),
 'preview_banner': ('06_previas_instagram/apresentacao_premium_2000x1250.png','Apresentação premium — simulação'),
 'foto': ('01_fotos_tratadas/foto_profissional_{:02d}.jpg','Fotos profissionais'),
 'post': ('03_vitrine_digital/feed_{:02d}_1080x1350.jpg','Publicações'),
 'story': ('03_vitrine_digital/story_{:02d}_1080x1920.jpg','Stories / status'),
 'extra': ('04_feed_premium/arte_extra_{:02d}_1080x1350.png','Extras Premium'),
 'destaque': ('02_perfil_express/capa_destaque_{:02d}.png','Capas de destaque'),
 'avatar': ('02_perfil_express/foto_de_perfil_1080.png','Foto de perfil'),
 'logo_escuro': ('02_perfil_express/logo_horizontal_escuro_1600x600.png','Logo horizontal escuro'),
 'logo_claro': ('02_perfil_express/logo_horizontal_claro_1600x600.png','Logo horizontal claro'),
}


def _reviewed(job):
    from app import order_dir, read_review
    folder=order_dir(job)
    from commerce_flow import is_commercial_job, is_paid
    if is_commercial_job(job) and not is_paid(job):
        raise PermissionError('Pagamento não confirmado.')
    if read_review(job).get('status')!='APROVADO':
        raise PermissionError('A entrega ainda não foi aprovada para o cliente.')
    return folder


def _secret_file(job):
    from app import OUT, JOB_RE
    if not JOB_RE.fullmatch(job):raise ValueError('Pedido inválido')
    return OUT/job/'.delivery_access.json'


def create(job):
    _reviewed(job)
    path=_secret_file(job)
    # Regenera o token na revisao. Todo link anterior e revogado.
    token=secrets.token_urlsafe(36)
    record={'token':token,'job':job,'created_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(record),encoding='utf-8')
    try:path.chmod(0o600)
    except OSError:pass
    return '/entrega/'+token


def revoke(job):
    _secret_file(job).unlink(missing_ok=True)


def link_for_operator(job):
    try:
        _reviewed(job)
        d=json.loads(_secret_file(job).read_text(encoding='utf-8'))
        return '/entrega/'+d['token'] if TOKEN_RE.fullmatch(d['token']) else None
    except (PermissionError,FileNotFoundError,ValueError,TypeError,KeyError):return None


def folder_for_token(token):
    from app import OUT, JOB_RE
    if not TOKEN_RE.fullmatch(token):raise FileNotFoundError('Link inválido.')
    # Tokens nunca controlam diretamente caminhos. Busca apenas em diretórios de pedido válidos.
    for root in OUT.iterdir():
        if not root.is_dir() or not JOB_RE.fullmatch(root.name):continue
        path=root/'.delivery_access.json'
        if not path.is_file():continue
        try: record=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if secrets.compare_digest(str(record.get('token','')),token):
            return _reviewed(root.name)
    raise FileNotFoundError('Entrega indisponível, expirada ou não aprovada.')


def _file(folder,kind,n):
    if kind not in FILE_TYPES:raise FileNotFoundError('Arquivo não permitido.')
    if not re.fullmatch(r'[1-9]\d?',str(n)):raise FileNotFoundError('Arquivo não permitido.')
    n=int(n)
    if n>20 or (kind in ('avatar','logo_escuro','logo_claro','preview_perfil','preview_feed','preview_banner') and n!=1):
        raise FileNotFoundError('Arquivo não permitido.')
    rel=FILE_TYPES[kind][0].format(n) if '{' in FILE_TYPES[kind][0] else FILE_TYPES[kind][0]
    f=(folder/rel).resolve()
    if not f.is_relative_to(folder.resolve()) or not f.is_file():raise FileNotFoundError('Arquivo indisponível.')
    return f


def _read_text(folder,relative,cap=25000):
    f=folder/relative
    if not f.is_file() or f.stat().st_size>cap:return ''
    return f.read_text(encoding='utf-8-sig',errors='replace').strip()


def _bios(folder):
    text=_read_text(folder,'02_perfil_express/bios_3_opcoes.txt',5000)
    result=[]
    if text:
        chunks=re.split(r'\n\s*\n',text)
        for chunk in chunks:
            lines=chunk.strip().splitlines()
            if len(lines)>=2 and any(s in lines[0].upper() for s in ('COMERCIAL','CRIATIVA','INSTITUCIONAL')):
                result.append({'name':lines[0].split('(')[0].strip(),'text':'\n'.join(lines[1:]).strip()})
    if not result:
        default=_read_text(folder,'02_perfil_express/bio_sugerida.txt',2000)
        if default:result=[{'name':'Bio recomendada','text':default}]
    return result


def _captions(folder):
    text=_read_text(folder,'03_vitrine_digital/legendas_prontas_para_revisao.txt')
    if not text:return []
    out=[]
    for chunk in re.split(r'(?=^POST\s+\d{2}\s*:)',text,flags=re.M):
        m=re.match(r'^POST\s+(\d{2})\s*:\s*([^\n]+)\n?(.*)',chunk,re.S)
        if m:out.append({'number':int(m.group(1)),'name':m.group(2).strip(),'text':m.group(3).strip()})
    return out


def _story_copy(folder):
    text=_read_text(folder,'03_vitrine_digital/textos_stories.txt')
    out=[]
    for chunk in re.split(r'(?=^STORY\s+\d{2}\b)',text,flags=re.M):
        m=re.match(r'^STORY\s+(\d{2})\b([^\n]*)\n?(.*)',chunk,re.S)
        if m:out.append({'number':int(m.group(1)),'name':m.group(2).strip(' ·'), 'text':m.group(3).strip()})
    return out


def manifest(token):
    folder=folder_for_token(token)
    info=json.loads((folder/'INFO_PEDIDO.json').read_text(encoding='utf-8'))
    result={'ok':True,'brand':str(info.get('brand','Sua marca'))[:100],
            'plan':str(info.get('plan_name','Seu pacote'))[:70],
            'instagram':str(info.get('instagram',''))[:100],
            'bios':_bios(folder),'captions':_captions(folder), 'stories_text':_story_copy(folder),
            'groups':[],'notice':'Prévias ilustrativas criadas a partir do material entregue; não representam uma conta real publicada. Confira antes de publicar.'}
    for kind,(_,label) in FILE_TYPES.items():
        files=[]
        for i in range(1,21):
            try:f=_file(folder,kind,i)
            except FileNotFoundError:continue
            q=f'/midia/{token}/{kind}/{i}'
            files.append({'label':(label if kind in ('avatar','logo_escuro','logo_claro','preview_perfil','preview_feed','preview_banner') else f'{label} {i:02d}'),
                          'view':q,'save':f'/salvar/{token}/{kind}/{i}',
                          'mime':mimetypes.guess_type(f.name)[0] or 'application/octet-stream'})
        if files:result['groups'].append({'kind':kind,'label':label,'files':files})
    # ZIP opcional; nao usar como forma principal de acesso.
    from app import OUT
    approved=OUT/('aprovado-'+folder.parent.name+'.zip')
    if approved.is_file(): result['zip_optional']=f'/salvar/{token}/pacote-completo'
    return result


def handle_get(h,p):
    try:
        if (m:=re.fullmatch(r'/entrega/([A-Za-z0-9_-]{40,80})',p)):
            folder_for_token(m.group(1))
            from app import ROOT
            return h._send((ROOT/'galeria_celular.html').read_bytes(),mime='text/html; charset=utf-8',extra={'Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex,nofollow','Content-Security-Policy':"default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"})
        if (m:=re.fullmatch(r'/api/entrega/([A-Za-z0-9_-]{40,80})',p)):
            return h._send(json.dumps(manifest(m.group(1)),ensure_ascii=False),extra={'X-Robots-Tag':'noindex,nofollow'})
        if (m:=re.fullmatch(r'/(midia|salvar)/([A-Za-z0-9_-]{40,80})/([a-z_]+)/([1-9]\d?)',p)):
            download,token,kind,n=m.groups()
            f=_file(folder_for_token(token),kind,n)
            mime=mimetypes.guess_type(f.name)[0] or 'application/octet-stream'
            extra={'X-Robots-Tag':'noindex,nofollow','Content-Security-Policy':"default-src 'none'; sandbox"}
            if download=='salvar':extra['Content-Disposition']=f'attachment; filename="{f.name}"'
            return h._send(f.read_bytes(),mime=mime,extra=extra)
        if (m:=re.fullmatch(r'/salvar/([A-Za-z0-9_-]{40,80})/pacote-completo',p)):
            folder=folder_for_token(m.group(1))
            from app import OUT
            f=OUT/('aprovado-'+folder.parent.name+'.zip')
            if not f.is_file():raise FileNotFoundError('ZIP não encontrado.')
            return h._send(f.read_bytes(),mime='application/zip',extra={'Content-Disposition':'attachment; filename="pacote-completo.zip"'})
        raise FileNotFoundError('Rota não encontrada')
    except (PermissionError,FileNotFoundError,ValueError,KeyError):
        return h._send('{"error":"Entrega não disponível. Verifique o link recebido."}',404)
