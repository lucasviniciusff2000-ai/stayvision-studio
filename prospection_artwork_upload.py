"""Upload privado de arte para prévia de prospecção; sem qualquer envio de mensagens."""
import base64
import binascii
import io
import json
import os
import secrets
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

def artwork_path():
    root=Path(os.getenv("STAYVISION_DATA_DIR") or "dados")
    return root/"marketing_stayvision_antes_depois.jpg"

def upload_artwork(h):
    try:
        from prospection import _auth
        from commerce_flow import _body
        _auth(h,True)
        payload=_body(h,limit=4_000_000)
        raw=payload.get("image_base64","")
        if not isinstance(raw,str) or not 50<len(raw)<=3_500_000:
            raise ValueError("Envie uma imagem JPG, PNG ou WEBP de até 2,5 MB.")
        try: decoded=base64.b64decode(raw,validate=True)
        except (binascii.Error,ValueError):raise ValueError("Arquivo de imagem inválido.")
        if len(decoded)>2_500_000:raise ValueError("Imagem maior que o limite de 2,5 MB.")
        try:
            with Image.open(io.BytesIO(decoded)) as im:
                if im.format not in ("JPEG","PNG","WEBP"):raise ValueError("Formato não permitido.")
                if im.width*im.height>18_000_000:raise ValueError("Dimensões excessivas.")
                im=ImageOps.exif_transpose(im)
                im.thumbnail((1800,1800),Image.Resampling.LANCZOS)
                if im.mode!="RGB":im=im.convert("RGB")
                out=io.BytesIO()
                im.save(out,format="JPEG",quality=88,optimize=True)
        except (OSError,UnidentifiedImageError,Image.DecompressionBombError):
            raise ValueError("Arquivo de imagem corrompido ou incompatível.")
        target=artwork_path()
        target.parent.mkdir(parents=True,exist_ok=True)
        tmp=target.with_name(target.name+"."+secrets.token_hex(6)+".tmp")
        try:
            tmp.write_bytes(out.getvalue())
            os.replace(tmp,target)
        finally:
            if tmp.exists():tmp.unlink()
        h._send(json.dumps({"ok":True,"art":"/assets/stayvision_antes_depois.jpg","mensagens_enviadas":0},ensure_ascii=False))
    except PermissionError:
        h._send(json.dumps({"error":"Faça login no painel."}),401)
    except (ValueError,TypeError) as e:
        h._send(json.dumps({"error":str(e)},ensure_ascii=False),400)
    except Exception:
        h._send(json.dumps({"error":"Falha ao salvar a arte. Confira o armazenamento persistente."},ensure_ascii=False),500)
