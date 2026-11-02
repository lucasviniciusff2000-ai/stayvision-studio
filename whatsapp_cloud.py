"""Envio individual de template aprovado pela WhatsApp Business Cloud API.

- Só funciona após opt-in registrado e autorização explícita do operador.
- Não importa dados do Google Maps, não dispara em massa e não faz envios em background.
- As credenciais são mantidas exclusivamente em variáveis do servidor Railway.
"""
import contextlib
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request


def _config():
    token = os.getenv("SV_WA_CLOUD_TOKEN", "").strip()
    sender = os.getenv("SV_WA_PHONE_NUMBER_ID", "").strip()
    template = os.getenv("SV_WA_TEMPLATE_NAME", "").strip()
    lang = os.getenv("SV_WA_TEMPLATE_LANG", "pt_BR").strip()
    ver = os.getenv("SV_WA_GRAPH_VERSION", "v26.0").strip()
    if not token or not sender or not template:
        raise ValueError("Configure SV_WA_CLOUD_TOKEN, SV_WA_PHONE_NUMBER_ID e SV_WA_TEMPLATE_NAME na Railway.")
    if not re.fullmatch(r"[0-9]{6,30}", sender):
        raise ValueError("ID de telefone Meta inválido.")
    if not re.fullmatch(r"[a-z0-9_]{2,120}", template):
        raise ValueError("Nome do modelo aprovado inválido.")
    if not re.fullmatch(r"[a-z]{2}_[A-Z]{2}", lang):
        raise ValueError("Idioma do modelo inválido.")
    if not re.fullmatch(r"v[0-9]{1,2}\.[0-9]{1,2}", ver):
        raise ValueError("Versão da API Meta inválida.")
    return token, sender, template, lang, ver


def send_opted_in_template(h):
    from prospection import _auth, _body, _db, _LOCK, _lead, _event, _reply, _now
    try:
        _auth(h, True)
        data = _body(h)
        if data.get("confirmar_envio") is not True:
            raise ValueError("Confirme o envio individual.")
        ident = data.get("id")
        if os.getenv("SV_WA_SEND_ENABLED", "") != "1":
            raise ValueError("Envio pela API desativado. Configure SV_WA_SEND_ENABLED=1 somente após validar a integração e o consentimento.")
        token, sender, template, lang, ver = _config()
        now = dt.datetime.now(dt.timezone.utc)
        day = now.date().isoformat()
        with _LOCK, contextlib.closing(_db()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS wa_envios(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id TEXT NOT NULL,
                modelo TEXT NOT NULL,
                destinatario TEXT NOT NULL,
                estado TEXT NOT NULL,
                meta_id TEXT NOT NULL DEFAULT '',
                criado TEXT NOT NULL,
                atualizado TEXT NOT NULL,
                UNIQUE(lead_id, modelo))""")
            lead = _lead(db, ident)
            if lead["bloqueado"] or not lead["whatsapp_ok"] or len((lead["fonte_consentimento"] or "").strip()) < 12:
                raise ValueError("Contato sem autorização registrada para WhatsApp ou bloqueado. Nenhuma mensagem foi enviada.")
            if not lead["telefone"] or not re.fullmatch(r"55[0-9]{10,11}", lead["telefone"]):
                raise ValueError("Contato sem número brasileiro válido.")
            if re.search(r"google\s*maps|maps\.google", lead["origem"], re.I):
                raise ValueError("Importação do Google Maps não pode ser usada como lista de prospecção.")
            if data.get("telefone_confirmado") != lead["telefone"]:
                raise ValueError("O telefone foi alterado. Confira o destinatário novamente.")
            already = db.execute("SELECT estado FROM wa_envios WHERE lead_id=? AND modelo=?",
                                 (ident,template)).fetchone()
            if already:
                raise ValueError("Este modelo já foi solicitado para o contato. Não repetimos envios automaticamente.")
            count = db.execute("""SELECT COUNT(*) FROM wa_envios
                 WHERE substr(criado,1,10)=?""", (day,)).fetchone()[0]
            if count >= 5:
                raise ValueError("Limite interno de segurança: 5 tentativas pela API por dia.")
            db.execute("""INSERT INTO wa_envios(lead_id,modelo,destinatario,estado,criado,atualizado)
                VALUES(?,?,?,'SOLICITADO',?,?)""",
                (ident,template,lead["telefone"],_now(),_now()))
            _event(db,ident,"WHATSAPP","Envio individual solicitado pelo operador; opt-in registrado")
        # Apenas o modelo previamente aprovado pela Meta é enviado.
        # O modelo deve ter UM parâmetro textual {{1}} no corpo, nome do estabelecimento.
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": lead["telefone"],
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": lang},
                "components": [{
                    "type": "body",
                    "parameters": [{"type":"text","text":lead["nome"][:120]}]
                }]
            }
        }
        url = f"https://graph.facebook.com/{ver}/{sender}/messages"
        req = urllib.request.Request(
            url, data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json"
            })
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                body = json.loads(response.read(30000))
            mid = str((body.get("messages") or [{}])[0].get("id",""))[:250]
            if not mid:
                raise RuntimeError("A Meta não retornou identificador. Verifique o painel oficial antes de tentar novamente.")
            state = "ACEITO_META"
        except urllib.error.HTTPError as exc:
            # Resposta de erro pode conter metadados; não expor corpo/token ao painel.
            state = "REJEITADO_META"
            raise RuntimeError("Meta rejeitou a mensagem (HTTP "+str(exc.code)+"). Confira o modelo aprovado e a configuração da API.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            state = "INDETERMINADO"
            raise RuntimeError("A conexão falhou. O resultado do envio é incerto; confirme na Meta antes de repetir.") from None
        finally:
            with _LOCK, contextlib.closing(_db()) as db, db:
                db.execute("""UPDATE wa_envios SET estado=?,meta_id=?,atualizado=?
                    WHERE lead_id=? AND modelo=?""",
                    (locals().get("state","INDETERMINADO"),locals().get("mid",""),_now(),ident,template))
        return _reply(h,{"ok":True,"status":"ACEITO_PELA_META_NAO_ENTREGUE_CONFIRMADO",
                          "lead_id":ident,"mensagens_solicitadas":1})
    except PermissionError:
        return _reply(h,{"error":"Sessão administrativa inválida."},401)
    except (ValueError,TypeError) as exc:
        return _reply(h,{"error":str(exc)},400)
    except RuntimeError as exc:
        return _reply(h,{"error":str(exc)},502)
    except Exception:
        return _reply(h,{"error":"Envio não confirmado. Confira os registros antes de repetir."},500)
