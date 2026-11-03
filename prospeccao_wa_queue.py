"""Fila persistente de prospecção WhatsApp StayVision.

Módulo de preparação. Não envia mensagens, não agenda tarefas por si só
e não é iniciado automaticamente pela aplicação. O adaptador Gupshup e
a autorização explícita de ativação deverão ser conectados separadamente.
"""
import contextlib
import datetime as dt
import os
import sqlite3
import threading

BATCH_SIZE = 5
BATCH_INTERVAL_SECONDS = 300
TEMPLATE_NAME = "stayvision_apresentacao"
_LOCK = threading.RLock()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def initialize(db_path):
    """Cria tabela separada sem alterar os 50 leads existentes."""
    with _LOCK, contextlib.closing(sqlite3.connect(db_path)) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS fila_prospeccao_wa (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          lead_id TEXT NOT NULL UNIQUE,
          telefone TEXT NOT NULL,
          nome TEXT NOT NULL,
          template TEXT NOT NULL,
          estado TEXT NOT NULL DEFAULT 'AGUARDANDO',
          lote INTEGER NOT NULL,
          autorizado INTEGER NOT NULL DEFAULT 0,
          criado TEXT NOT NULL,
          atualizado TEXT NOT NULL,
          erro TEXT DEFAULT '',
          provider_message_id TEXT DEFAULT ''
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_fila_wa_estado_lote ON fila_prospeccao_wa(estado,lote)")
        db.commit()


def prepare(db_path, contacts):
    """Prepara apenas contatos com opt-in individual confirmado.

    contacts: iterable de dicts com lead_id, telefone, nome e opt_in=True.
    Sem opt-in confirmado, o contato é ignorado. Idempotente por lead_id.
    """
    initialize(db_path)
    inserted = 0
    ignored = 0
    with _LOCK, contextlib.closing(sqlite3.connect(db_path)) as db:
        for item in contacts:
            if item.get("opt_in") is not True:
                ignored += 1
                continue
            lead_id = str(item.get("lead_id", "")).strip()
            phone = "".join(c for c in str(item.get("telefone", "")) if c.isdigit())
            name = str(item.get("nome", "")).strip()
            if not lead_id or not name or not (12 <= len(phone) <= 13):
                ignored += 1
                continue
            count = db.execute("SELECT COUNT(*) FROM fila_prospeccao_wa").fetchone()[0]
            lote = count // BATCH_SIZE
            now = _now()
            cur = db.execute("""INSERT OR IGNORE INTO fila_prospeccao_wa
                (lead_id,telefone,nome,template,estado,lote,autorizado,criado,atualizado)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (lead_id,phone,name,TEMPLATE_NAME,"AGUARDANDO",lote,1,now,now))
            inserted += cur.rowcount
        db.commit()
    return {"preparados": inserted, "ignorados": ignored, "envios": 0}


def preview(db_path):
    """Somente leitura; nenhuma chamada de rede."""
    initialize(db_path)
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        rows = db.execute("""SELECT estado,COUNT(*) FROM fila_prospeccao_wa
                             GROUP BY estado""").fetchall()
        total = db.execute("SELECT COUNT(*) FROM fila_prospeccao_wa").fetchone()[0]
    return {"total": total, "estados": dict(rows),
            "tamanho_lote": BATCH_SIZE,
            "intervalo_segundos": BATCH_INTERVAL_SECONDS,
            "template": TEMPLATE_NAME, "envio_ativo": False}


def cancel(db_path, lead_id):
    """Cancela um contato antes do envio, por exemplo após pedido SAIR."""
    initialize(db_path)
    with _LOCK, contextlib.closing(sqlite3.connect(db_path)) as db:
        cur = db.execute("""UPDATE fila_prospeccao_wa
            SET estado='CANCELADO',atualizado=?
            WHERE lead_id=? AND estado='AGUARDANDO'""", (_now(),lead_id))
        db.commit()
        return cur.rowcount


def sending_prerequisites():
    """Relata os bloqueios, sem ativar ou enviar nada."""
    missing = []
    if os.getenv("SV_WA_PROVIDER", "").strip().lower() != "gupshup":
        missing.append("SV_WA_PROVIDER=gupshup")
    if os.getenv("SV_WA_TEMPLATE_APPROVED") != "1":
        missing.append("aprovação verificada do template")
    if os.getenv("SV_WA_CAMPAIGN_ENABLED") != "1":
        missing.append("ativação explícita da campanha")
    return {"ready": not missing, "missing": missing,
            "warning": "A prontidão não confirma opt-in nem entrega; requer integração e testes."}
