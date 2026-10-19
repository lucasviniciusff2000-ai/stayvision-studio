const $ = id => document.getElementById(id);
const escapeHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stateNames={aguardando_integracao:'Aguardando integração IA',processando:'Processando',revisao:'Revisão de qualidade',falhou:'Falha',entregue:'Entregue'};
const paymentNames={nao_iniciado:'Não iniciado',pendente:'Pendente',pago:'Pago*',recusado:'Recusado',estornado:'Estornado'};
async function refreshOps(){
 $('ops-status').textContent='Atualizando...';
 try{
  const r=await fetch('/api/admin/operations',{credentials:'same-origin',cache:'no-store'});
  if(r.status===401){$('ops-status').innerHTML='Acesso restrito. <a href="/painel">Faça login no painel administrativo</a> e volte aqui.'; $('ops-content').hidden=true;return;}
  if(!r.ok)throw Error('Não foi possível consultar a operação.');
  const d=await r.json(), c=d.counts;
  $('ops-content').hidden=false;
  $('count-pay').textContent=c.aguardando_pagamento;
  $('count-pending').textContent=c.aguardando_integracao;
  $('count-running').textContent=c.processando;
  $('count-failed').textContent=c.falhou;
  $('count-delivered').textContent=c.entregue;
  const checks=[['Motor de IA',d.engine_connected?'Conectado':'Não integrado'],['Mercado Pago',d.payment_gateway_configured?'Credenciais presentes (testes necessários)':'Sem credenciais completas'],['Cobrança',d.payments_enabled?'Habilitada':'Desabilitada'],['Vendas públicas',d.sales_enabled?'Habilitadas':'Desabilitadas']];
  $('health').textContent=checks.map(([name,value])=>name+': '+value).join('  •  ');
  $('ops-rows').innerHTML=d.jobs.length?d.jobs.map(o=>{
    const paid=o.payment_status==='pago';
    const ai=!paid?'Aguardando pagamento':(o.delivery_filename&&o.status==='concluido'?'Entregue':(stateNames[o.ai_state]||'Aguardando integração IA'));
    return `<tr><td><b>${escapeHtml(o.id)}</b><br><small>${escapeHtml(new Date(o.created_at).toLocaleDateString('pt-BR'))}</small></td><td>${escapeHtml(o.name)}</td><td>${escapeHtml(o.plan_name)}</td><td><span class="ops-tag">${escapeHtml(paymentNames[o.payment_status]||o.payment_status)}</span></td><td><span class="ops-tag">${escapeHtml(ai)}</span></td><td>${o.delivery_filename?'Arquivo anexado':'Pendente'}</td><td><a href="/painel" class="ops-action">Abrir painel ↗</a></td></tr>`;
  }).join(''):'<tr><td colspan="7">Nenhum pedido recebido ainda.</td></tr>';
  $('ops-status').textContent='Dados atualizados. '+d.jobs.length+' pedido(s) no histórico.';
 }catch(e){$('ops-status').textContent=e.message;}
}
$('refresh').addEventListener('click',refreshOps);refreshOps();
