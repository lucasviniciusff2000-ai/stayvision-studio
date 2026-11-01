"""Diagnóstico offline sem Mercado Pago, Gemini ou fal.ai."""
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
import os,sys,compileall
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
assert compileall.compile_dir(str(root),quiet=1)
print('1/6 PASSOU: arquivos Python compilam.')
from real_plan_checkout import PRICES
assert PRICES=={'fotos':Decimal('59.90'),'perfil':Decimal('149.90'),'vitrine':Decimal('249.90'),'premium':Decimal('399.90')}
print('2/6 PASSOU: valores reais dos quatro planos.')
from web_public import GET_SIMPLE,POST_SIMPLE
assert '/api/cliente/checkout-real' in POST_SIMPLE and '/api/operacao/simular-pagamento' not in POST_SIMPLE
assert '/api/orders' not in GET_SIMPLE
print('3/6 PASSOU: checkout real no gateway; simulações locais bloqueadas.')
assert (root/'assets'/'cliente_inicio_v310.js').is_file() and (root/'index.html').is_file()
assert 'location.origin' in (root/'assets'/'cliente_inicio_v310.js').read_text(encoding='utf-8')
print('4/6 PASSOU: site e acompanhamento com links do mesmo domínio.')
from auto_delivery import paid_for_delivery
paid={'plan':'fotos','payment':'VERIFICADO_PROVEDOR','payment_source':'MERCADO_PAGO_API_VERIFICADO','paid_amount_brl':'59.90','checkout_real':{'kind':'REAL_PLAN','status':'PREFERENCIA_CRIADA','currency':'BRL','amount_brl':'59.90','seller_id':'123','payment_id':'456','preference_id':'id'}}
with patch.dict(os.environ,{'SV_COMMERCIAL_AUTO_DELIVERY':'1','STAYVISION_FULL_AUTO':'1','SV_AUTO_DELIVERY_EXPLICIT':'1','STAYVISION_SEMI_AUTO':'1','SV_AUTO_AI_EXPLICIT':'1','SV_REAL_PLANS_ENABLED':'1','MP_LIVE_ACCESS_TOKEN':'MOCK_ONLY','SV_AUTO_DELIVERY_MAX_ORDERS':'20','SV_AUTO_AI_BUDGET_MAX_CALLS':'40'}):
 assert paid_for_delivery(paid)
 assert not paid_for_delivery(dict(paid,paid_amount_brl='1.00'))
 assert not paid_for_delivery(dict(paid,payment='PENDENTE'))
print('5/6 PASSOU: não libera sem pagamento real integral.')
assert not any(x.is_file() for x in (root/'pedidos_teste').rglob('*')) and not (root/'admin_login_local.json').exists()
print('6/6 PASSOU: dados pessoais e credenciais não inclusos no pacote.')
print('TESTES OFFLINE APROVADOS. Ainda é necessário validar Railway, Mercado Pago e IA ao vivo.')
