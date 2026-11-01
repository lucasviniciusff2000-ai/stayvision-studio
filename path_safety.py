"""Fail early before paid-image reservations if Windows paths may exceed MAX_PATH."""
import os
from pathlib import Path

def require_safe_output():
    from app import OUT
    # Deepest pilot test output and commercial production paths.
    checks=[
        OUT/'pilotos_fotograficos'/('piloto-'+'a'*16)/'entrega'/'05_controle_de_qualidade'/'referencia_preparada.jpg',
        OUT/'premium_direto_v33'/('pedido-'+'a'*16)/'estado.json.tmp',
        OUT/('pedido-'+'a'*16)/'entrega'/'05_controle_de_qualidade'/'referencias_preparadas'/'referencia_01.jpg',
    ]
    if os.name=='nt' and any(len(str(f))>=246 for f in checks):
        raise RuntimeError('PASTA MUITO LONGA para Windows. ANTES de gerar IA, mova a pasta inteira da StayVision para C:\\SV\\SV_V327, reinicie o sistema e importe seus pedidos anteriores. Nao repita tentativa reservada antes de conferir a fal.ai.')
    return True
