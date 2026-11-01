"""Credenciais locais com derivação PBKDF2; não publicar este servidor na internet."""
import hashlib,hmac,json,secrets,os
from pathlib import Path

CONFIG=Path(os.environ.get('STAYVISION_DATA_DIR',str(Path(__file__).resolve().parent))) / 'admin_login_local.json'

def configured():
    return CONFIG.is_file()

def setup(username,password):
    if not 3<=len(username)<=60 or not username.replace('_','').replace('-','').isalnum():raise ValueError('Usuário deve ter 3–60 caracteres alfanuméricos.')
    if len(password)<12:raise ValueError('A senha precisa ter pelo menos 12 caracteres.')
    if CONFIG.exists():raise ValueError('Credenciais existentes; arquivo não será sobrescrito.')
    salt=secrets.token_bytes(24); rounds=480000
    record={'username':username,'salt':salt.hex(),'iterations':rounds,'password_hash':hashlib.pbkdf2_hmac('sha256',password.encode(),salt,rounds).hex()}
    CONFIG.write_text(json.dumps(record),encoding='utf-8')
    try:CONFIG.chmod(0o600)
    except OSError:pass

def verify(username,password):
    try:
        record=json.loads(CONFIG.read_text(encoding='utf-8'))
        digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(record['salt']),int(record['iterations']))
        return hmac.compare_digest(record['username'],username) and hmac.compare_digest(bytes.fromhex(record['password_hash']),digest)
    except (OSError,ValueError,KeyError,TypeError):return False
