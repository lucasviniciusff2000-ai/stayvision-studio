const $=q=>document.querySelector(q),$$=q=>[...document.querySelectorAll(q)];
const h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL',maximumFractionDigits:0}).format(v);
const labels={recebido:'Recebido',aguardando_pagamento:'Pagamento pendente',em_producao:'Em produção',em_revisao:'Em revisão',concluido:'Concluído',cancelado:'Cancelado'};
async function api(path,options={}){let r=await fetch(path,{credentials:'same-origin',...options});let data=await r.json().catch(()=>({error:'Resposta inválida'}));if(!r.ok)throw Error(data.error||'Requisição falhou');return data;}
let currentOrder=null,orders=[],settings=null,initialized=false,aiPolling=null;
async function start(){const auth=await api('/api/admin/me');initialized=auth.initialized;if(!auth.authenticated){showLogin();return;}showPanel();await Promise.all([refresh(),loadSettings(),loadLeads()]);}
function showLogin(){ $('#login-layout').classList.remove('hidden');$('#admin-layout').classList.add('hidden');if(!initialized){$('#auth-desc').textContent='Admin ainda não configurado. Defina STAYVISION_ADMIN_USER e STAYVISION_ADMIN_PASSWORD nas variáveis privadas da Railway.';$('#auth-submit').disabled=true;}}
function showPanel(){$('#login-layout').classList.add('hidden');$('#admin-layout').classList.remove('hidden');}
$('#auth-form').addEventListener('submit',async e=>{e.preventDefault();$('#auth-feedback').textContent='';try{await api(initialized?'/api/admin/login':'/api/admin/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('#username').value,password:$('#password').value})});initialized=true;showPanel();await Promise.all([refresh(),loadSettings(),loadLeads()]);}catch(err){$('#auth-feedback').textContent=err.message;}});
$('#logout').addEventListener('click',async()=>{await api('/api/admin/logout',{method:'POST'});location.reload();});
$$('[data-tab]').forEach(b=>b.addEventListener('click',()=>{$$('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));$('#tab-overview').classList.toggle('hidden',b.dataset.tab!=='overview');$('#tab-settings').classList.toggle('hidden',b.dataset.tab!=='settings');$('#tab-leads').classList.toggle('hidden',b.dataset.tab!=='leads');}));
$('#refresh').addEventListener('click',refresh);
$('#filter-search').addEventListener('input',renderOrders);$('#filter-status').addEventListener('change',renderOrders);
async function refresh(){let d=await api('/api/admin/overview');orders=d.orders;$('#metric-total').textContent=d.total;$('#metric-new').textContent=d.received;$('#metric-progress').textContent=d.in_progress;$('#metric-sales').textContent=money(d.paid_total);renderOrders();}
function renderOrders(){let q=$('#filter-search').value.toLowerCase().trim(),status=$('#filter-status').value;let list=orders.filter(o=>(!q||[o.name,o.email,o.phone,o.id,o.city,o.property_type,o.plan_name].join(' ').toLowerCase().includes(q))&&(!status||o.status===status));$('#orders-count').textContent=list.length+' pedido(s)';$('#orders-table').innerHTML=list.length?list.map(o=>`<tr><td><b>${h(o.id)}</b><br><small>${h(new Date(o.created_at).toLocaleDateString('pt-BR'))}</small></td><td>${h(o.name)}<br><small>${h(o.city)}</small></td><td>${h(o.plan_name)}</td><td>${money(o.price)}</td><td><span class="status-tag ${o.payment_status==='pago'?'paid':''}">${h(labels[o.status]||o.status)}</span></td><td><button type="button" data-order="${h(o.id)}">Abrir ↗</button></td></tr>`).join(''):'<tr><td colspan="6" style="text-align:center;padding:30px">Nenhum pedido encontrado.</td></tr>';$$('[data-order]').forEach(btn=>btn.addEventListener('click',()=>openOrder(btn.dataset.order)));}
const detail=(name,v)=>`<div><div class="detail-label">${name}</div><div class="detail-value">${h(v)}</div></div>`;
async function openOrder(id){try{let d=await api('/api/admin/orders/'+encodeURIComponent(id)),o=d.order;if(!o)throw Error('Pedido não localizado.');currentOrder=o;$('#order-editor').classList.remove('hidden');$('#order-heading').textContent='Pedido '+o.id;$('#order-meta').innerHTML=detail('Nome',o.name)+detail('E-mail',o.email)+detail('Telefone',o.phone)+detail('Local',o.city)+detail('Imóvel',o.property_type)+detail('Serviço',o.plan_name)+detail('Preço',money(o.price))+detail('Criado',new Date(o.created_at).toLocaleString('pt-BR'))+`<div style="grid-column:1/-1">${detail('Briefing',o.notes||'Sem observações')}</div>`;
$('#order-files').innerHTML=d.files.map(f=>`<div><a href="/api/admin/files/${f.id}" target="_blank" rel="noopener">↗ ${h(f.name)}</a><small style="color:#859286"> · ${(f.size/1048576).toFixed(2)} MB</small></div>`).join('')||'<p>Sem arquivos.</p>';
$('#tracking-link').href='/acompanhar?token='+encodeURIComponent(o.customer_token);
$('#edit-status').value=o.status;$('#edit-payment').value=o.payment_status;$('#edit-note').value=o.admin_note;$('#update-feedback').textContent='';$('#delivery-feedback').textContent='';$('#verify-feedback').textContent='';$('#mp-payment-id').value='';refreshAi(o.id);$('#order-editor').scrollIntoView({behavior:'smooth'});
}catch(err){alert(err.message);}}
$('#close-order').addEventListener('click',()=>{$('#order-editor').classList.add('hidden');currentOrder=null;if(aiPolling){clearTimeout(aiPolling);aiPolling=null;}});
async function refreshAi(oid){
 if(aiPolling){clearTimeout(aiPolling);aiPolling=null;}
 if(!oid||!currentOrder||currentOrder.id!==oid)return;
 const feedback=$('#ai-feedback'),results=$('#ai-results'),wrap=$('#ai-progress-wrap'),fill=$('#ai-progress-fill');
 try{
  const response=await api('/api/admin/ai/status?id='+encodeURIComponent(oid));
  if(!currentOrder||currentOrder.id!==oid)return;
  const runs=response.runs||[],run=runs[0];
  if(!run){feedback.textContent='Pronto para tratar as fotos deste pedido.';results.innerHTML='';wrap.hidden=true;$('#ai-generate').disabled=false;return;}
  feedback.textContent=(run.state==='pronto'?'✓ ':run.state==='falhou'?'Erro: ':run.state==='interrompido'?'Interrompido: ':'Processando: ')+(run.message||run.state);
  wrap.hidden=!['processando','na_fila'].includes(run.state);
  fill.style.width=(run.progress||0)+'%';
  $('#ai-generate').disabled=wrap.hidden===false;
  if(run.state==='pronto'){
   let artifacts=(run.artifacts||[]).filter(a=>a.name);
   results.innerHTML='<b style="font-size:12px;color:#446c46">Arquivos para revisão — nenhum é enviado automaticamente ao cliente:</b>'+artifacts.map(a=>{
     const url='/api/admin/ai/file?run='+encodeURIComponent(run.id)+'&name='+encodeURIComponent(a.name);
     return '<div class="ai-file"><div><b>'+h(a.label||a.name)+'</b><br><small>'+h(a.name)+'</small></div><a href="'+url+'">Baixar ↧</a></div>';
   }).join('')+((run.previews||[]).length?'<div class="ai-preview">'+run.previews.map(name=>'<img loading="lazy" alt="Prévia tratada" src="/api/admin/ai/file?run='+encodeURIComponent(run.id)+'&name='+encodeURIComponent('photos/'+name)+'">').join('')+'</div>':'')+((run.quality_warnings||[]).length?'<div class="notice" style="margin:12px 0;color:#6b4c20;background:#fff8e7"><b>Atenção à resolução original</b><p>'+run.quality_warnings.map(h).join('<br>')+'</p><small>Para qualidade de anúncio, solicite fotos originais em alta resolução, não imagens comprimidas por mensageiros. Nenhum filtro recupera os detalhes ausentes.</small></div>':'')+((artifacts.length)?'<p style="font-size:11px;color:#697967">Revise o resultado e utilize “Entregar arquivo final” somente após conferir o pagamento.</p>':'');
  } else {results.innerHTML='';}
  if(!wrap.hidden)aiPolling=setTimeout(()=>refreshAi(oid),2300);
 }catch(err){feedback.textContent='Erro ao consultar produção: '+err.message;wrap.hidden=true;}
}
$('#ai-generate').addEventListener('click',async()=>{
 if(!currentOrder)return;
 const oid=currentOrder.id,mode=$('#ai-mode').value,style=$('#ai-style').value,aspect=$('#ai-aspect').value;
 const btn=$('#ai-generate');btn.disabled=true;
 $('#ai-feedback').textContent='Iniciando processamento. Aguarde...';
 try{
  await api('/api/admin/ai/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:oid,mode,style,aspect})});
  await refreshAi(oid);
 }catch(err){$('#ai-feedback').textContent='Não foi possível iniciar: '+err.message;btn.disabled=false;}
});
$('#update-form').addEventListener('submit',async e=>{e.preventDefault();if(!currentOrder)return;try{await api('/api/admin/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:currentOrder.id,status:$('#edit-status').value,payment_status:$('#edit-payment').value,admin_note:$('#edit-note').value})});$('#update-feedback').textContent='Alterações salvas com sucesso.';await refresh();}catch(err){$('#update-feedback').textContent=err.message;}});
$('#verify-payment-form').addEventListener('submit',async e=>{
 e.preventDefault();if(!currentOrder)return;
 const feed=$('#verify-feedback'),btn=$('#verify-payment-form button[type="submit"]');
 const id=currentOrder.id,paymentId=$('#mp-payment-id').value.trim();
 if(!/^[0-9]{1,30}$/.test(paymentId)){feed.textContent='Informe o ID numérico do pagamento.';return;}
 if(!window.confirm('Consultar este pagamento REAL na API do Mercado Pago e marcar o pedido '+id+' como Pago SOMENTE se todos os dados conferirem? Não será criada cobrança nova.'))return;
 btn.disabled=true;feed.textContent='Conferindo pagamento com o Mercado Pago, sem gerar cobrança...';
 try{
  const response=await api('/api/admin/verify-payment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,payment_id:paymentId})});
  await refresh();await openOrder(id);
  $('#verify-feedback').textContent=response.message+' Pedido: '+id+'. Status: Pago.';
 }catch(err){feed.textContent=err.message;}
 finally{btn.disabled=false;}
});
$('#delivery-form').addEventListener('submit',async e=>{e.preventDefault();if(!currentOrder)return;const f=$('#delivery-file').files[0];if(!f)return;if(f.size>94371840){$('#delivery-feedback').textContent='Arquivo maior que 90 MB.';return;}let form=new FormData();form.append('id',currentOrder.id);form.append('delivery',f);$('#delivery-feedback').textContent='Enviando arquivo, aguarde...';try{await api('/api/admin/deliver',{method:'POST',body:form});$('#delivery-feedback').textContent='Arquivo salvo! A entrega é liberada quando o pagamento estiver confirmado.';$('#edit-status').value='concluido';$('#delivery-file').value='';await refresh();}catch(err){$('#delivery-feedback').textContent=err.message;}});
async function loadSettings(){settings=await api('/api/admin/settings');$('#brand-setting').value=settings.brand_name;$('#whatsapp-setting').value=settings.contact_whatsapp;$('#settings-prices').innerHTML=settings.plans.map(p=>`<div><label for="price-${p.code}">${h(p.name)}</label><input class="input" type="number" min="1" max="100000" step="1" id="price-${p.code}" value="${p.price}"><p style="font-size:11px;color:#7b8978">${h(p.description)}</p></div>`).join('');$('#payment-toggles').classList.add('hidden');$('#pix-production-credential-status').textContent=settings.pix_production_diagnostic_ready?'Token de produção cadastrado no servidor (valor oculto).':'Token de produção ainda não cadastrado na Railway.';$('#payment-toggle').checked=!!settings.payment_enabled;$('#sales-toggle').checked=!!settings.sales_enabled;$('#payment-diagnostics').textContent=settings.sales_enabled?'Checkout de produção ATIVO. A confirmação dos pagamentos depende dos webhooks autenticados.':'Checkout público BLOQUEADO. Integração de produção preparada para lançamento quando autorizada na Railway.';}
$('#pix-diagnostic-btn').addEventListener('click', async () => {
 const button=$('#pix-diagnostic-btn'), out=$('#pix-diagnostic-result');
 button.disabled=true;out.textContent='Consultando os meios de pagamento com a credencial de TESTE...';
 try {
   const x=await api('/api/admin/pix-diagnostic');
   out.textContent=(x.pix_listed?'Pix consta na lista da API. ':'Pix NÃO consta na lista da API. ')+x.message+
    ' Não há bloqueio do Pix na preferência de pagamento da StayVision.';
 } catch(err) {out.textContent='Não foi possível consultar a API: '+err.message;}
 finally {button.disabled=false;}
});
$('#pix-production-btn').addEventListener('click', async()=>{
 const button=$('#pix-production-btn'), out=$('#pix-production-result');
 button.disabled=true; out.textContent='Consultando somente os meios de pagamento disponiveis no Mercado Pago...';
 try {
   const x=await api('/api/admin/pix-production-diagnostic');
   out.textContent=(x.pix_listed?'Pix LISTADO na API de producao. ':'Pix NAO LISTADO na API de producao. ')+x.message+
     ' Nenhuma cobranca foi criada e o checkout real segue desativado.';
 } catch(err) {out.textContent='Consulta nao realizada: '+err.message;}
 finally {button.disabled=false;}
});
$('#webhook-diagnostic-btn').addEventListener('click', async()=>{
 const output=$('#webhook-diagnostic-output');
 output.textContent='Consultando notificações recebidas...';
 try {
   const x=await api('/api/admin/webhook-status');
   const latest=x.recent_events?.[0];
   output.textContent=(x.webhook_secret_configured?'Chave de webhook configurada. ':'Chave de webhook ainda NÃO configurada. ')+
    'Notificações autenticadas recebidas: '+x.events_received+'. '+
    (latest?'Última: '+latest.received_at+' — '+latest.event_type+' ('+latest.result+'). ':'')+
    'Consultas com validação completa (somente observação): '+(x.reconciliation?.verified_readonly??0)+'. '+
    'O checkout segue desativado. Nenhuma alteração de pagamento foi realizada.';
 }catch(e){output.textContent='Falha na consulta: '+e.message;}
});
$('#settings-form').addEventListener('submit',async e=>{e.preventDefault();if(!settings)return;try{let plans=settings.plans.map(p=>({...p,price:Number($('#price-'+p.code).value)}));await api('/api/admin/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plans,brand_name:$('#brand-setting').value,contact_whatsapp:$('#whatsapp-setting').value})});$('#settings-feedback').textContent='Configurações salvas. Atualize o site para ver os valores.';await loadSettings();}catch(err){$('#settings-feedback').textContent=err.message;}});
async function checkCheckoutReadiness(){
 const el=$('#checkout-readiness-status');
 try{
  const x=await api('/api/admin/checkout-readiness');
  el.textContent=(x.orders_publicly_open?'Checkout público ATIVO. ':(x.mode==='locked'?'Checkout real BLOQUEADO. ':'Modo restrito configurado; verifique as autorizações. '))+
   (x.production_token_present?'Token de produção cadastrado. ':'Token de produção ausente. ')+
   (x.collector_id_configured?'ID do vendedor configurado. ':'ID do vendedor ainda não configurado. ')+
   (x.orders_publicly_open?'Venda pública: SIM (somente se autorizada nas variáveis).':'Venda pública: NÃO.');
 }catch(e){el.textContent='Diagnóstico indisponível: '+e.message;}
}
$('#checkout-dryrun-btn').addEventListener('click',async()=>{
 const el=$('#checkout-dryrun-result'),id=$('#checkout-dryrun-id').value.trim().toUpperCase();
 if(!/^SV-[A-Z0-9-]{5,40}$/.test(id)){el.textContent='Informe um código válido de pedido Photo.';return;}
 el.textContent='Validando em modo de simulação...';
 try{
  const x=await api('/api/admin/checkout-preview?id='+encodeURIComponent(id));
  el.textContent='Prévia sem cobrança: '+x.order_id+' · Plano Photo · R$ '+x.amount_brl+
   ' · Preferência existente: '+(x.preference_linked?'sim':'não')+
   ' · Checkout restrito: '+(x.checkout_locked?'BLOQUEADO':'aguardando autorização')+
   '. Nenhuma cobrança foi criada.';
 }catch(e){el.textContent='Prévia não realizada: '+e.message;}
});
async function stage7Readiness(){
 const status=$('#stage7-status'),btn=$('#stage7-create');
 try{
  const x=await api('/api/admin/checkout-readiness');
  const ready=!!x.single_order_gate_ready;
  status.textContent=ready?'Autorização de pedido único detectada. Confirme antes de criar link real.':(x.orders_publicly_open?'Vendas públicas ativas: seção de teste restrito desnecessária.':'BLOQUEADO: modo restrito e autorização por pedido ainda não foram habilitados nas variáveis privadas.');
  btn.disabled=!ready;
 }catch(e){status.textContent='Diagnóstico indisponível: '+e.message;btn.disabled=true;}
}
$('#stage7-order-id').addEventListener('input',()=>{
 const id=$('#stage7-order-id').value.trim().toUpperCase();
 $('#stage7-confirm').placeholder=/^SV-[A-Z0-9-]{5,40}$/.test(id)?'AUTORIZO PIX REAL '+id+' R$49':'AUTORIZO PIX REAL SV-... R$49';
 $('#stage7-link-area').hidden=true;
});
$('#stage7-create').addEventListener('click',async()=>{
 const id=$('#stage7-order-id').value.trim().toUpperCase(),out=$('#stage7-result');
 $('#stage7-link-area').hidden=true;
 if(!/^SV-[A-Z0-9-]{5,40}$/.test(id)){out.textContent='Informe o pedido Photo autorizado.';return;}
 if(!$('#stage7-understand').checked){out.textContent='Confirme que compreende que será gerado um link de pagamento real.';return;}
 if($('#stage7-confirm').value.trim()!=='AUTORIZO PIX REAL '+id+' R$49'){
  out.textContent='Digite a autorização exata para este pedido. Isso não habilita cobranças sozinho.';return;
 }
 const go=window.confirm('Criar uma preferência REAL de R$ 49 para '+id+'? Apenas um pedido autorizado. Ainda NÃO paga automaticamente.');
 if(!go){out.textContent='Operação cancelada. Nenhuma solicitação de cobrança enviada.';return;}
 const btn=$('#stage7-create');btn.disabled=true;out.textContent='Solicitando preferência restrita ao Mercado Pago...';
 try{
  const x=await api('/api/admin/checkout-create',{method:'POST',headers:{'Content-Type':'application/json','X-StayVision-Checkout-Intent':'single-real-test'},
   body:JSON.stringify({id,confirmation:$('#stage7-confirm').value.trim()})});
  out.textContent=(x.created?'Preferência criada. ':'Preferência já existente, reutilizada. ')+
   'Atenção: R$ 49, dinheiro REAL se o link for pago. Código de preferência: '+x.preference_id+'.';
  const a=$('#stage7-link');a.href=x.url;$('#stage7-link-area').hidden=false;
 }catch(e){out.textContent='Link NÃO disponibilizado: '+e.message;}finally{await stage7Readiness();}
});
$('#stage7-check-payment').addEventListener('click',async()=>{
 const out=$('#stage7-payment-result'),oid=$('#stage7-order-id').value.trim().toUpperCase(),pid=$('#stage7-payment-id').value.trim();
 if(!/^SV-[A-Z0-9-]{5,40}$/.test(oid)|| !/^[0-9]{1,30}$/.test(pid)){
  out.textContent='Informe um código de pedido válido e o ID numérico de um pagamento.';return;
 }
 out.textContent='Consultando status oficial do Mercado Pago...';
 try{
  const x=await api('/api/admin/checkout-observe?id='+encodeURIComponent(oid)+'&payment_id='+encodeURIComponent(pid));
  out.textContent='Pedido '+x.order_id+' | Pagamento '+x.payment_id+' | API: '+x.payment_status+
   ' | Conferência: '+x.result+' | Status StayVision: '+x.order_payment_status+'. Nenhuma alteração automática por esta consulta.';
 }catch(e){out.textContent='Não foi possível conferir: '+e.message;}
});
$('#seller-verify-btn').addEventListener('click',async()=>{
 const btn=$('#seller-verify-btn'),out=$('#seller-verify-result');
 btn.disabled=true;out.textContent='Verificando o ID da conta com o Mercado Pago, sem criar preferência...';
 try{
  const x=await api('/api/admin/seller-identity');
  const configured=String(x.configured_id_suffix||'').replace(/[^0-9]/g,'').slice(-4);
  const owner=String(x.token_owner_id_suffix||'').replace(/[^0-9]/g,'').slice(-4);
  out.textContent=(x.verified?'IDENTIDADE CONFIRMADA. ':'ATENÇÃO: IDENTIDADE DIVERGENTE. ')+x.message+
   (configured&&owner?' ID configurado termina em: '+configured+'. ID reconhecido pelo token termina em: '+owner+'.':'')+
   ' Checkout real continua bloqueado; nenhuma cobrança criada.';
 }catch(e){out.textContent='Identidade NÃO confirmada: '+e.message+' Não desbloqueie o checkout.';}
 finally{btn.disabled=false;}
});
// Consulta explícita e autenticada do ID da conta, sem token e sem criar cobranças.
$('#seller-reveal-id-btn').addEventListener('click',async()=>{
 const btn=$('#seller-reveal-id-btn'),out=$('#seller-full-id-feedback'),area=$('#seller-full-id-area'),field=$('#seller-full-id');
 area.hidden=true;field.value='';btn.disabled=true;out.textContent='Consultando identidade diretamente no Mercado Pago...';
 try{
  const x=await api('/api/admin/seller-identity-full');
  const id=String(x.token_owner_id_full||'');
  if(!/^[0-9]{1,30}$/.test(id))throw Error('A API não retornou um identificador numérico válido.');
  field.value=id;area.hidden=false;
  out.textContent=(x.verified?'O ID já coincide com o cadastro. ':'O ID é diferente do cadastro atual. ')+
    'Confira que a conta de produção é sua antes de substituir o valor de MP_PRODUCTION_COLLECTOR_ID. Nenhuma cobrança foi criada.';
 }catch(e){out.textContent='Não foi possível obter o ID: '+e.message+' Checkout permanece bloqueado.';}
 finally{btn.disabled=false;}
});
$('#seller-copy-id-btn').addEventListener('click',async()=>{
 const field=$('#seller-full-id'),feedback=$('#seller-full-id-feedback');
 if(!/^[0-9]{1,30}$/.test(field.value))return;
 try{await navigator.clipboard.writeText(field.value);feedback.textContent='ID copiado. Cole SOMENTE no valor de MP_PRODUCTION_COLLECTOR_ID na Railway.';}
 catch(e){field.focus();field.select();feedback.textContent='Selecione e copie o número do campo manualmente (Ctrl+C).';}
});
$('#seller-hide-id-btn').addEventListener('click',()=>{
 $('#seller-full-id').value='';$('#seller-full-id-area').hidden=true;
 $('#seller-full-id-feedback').textContent='ID ocultado. Checkout continua bloqueado.';
});
$('#save-payment-toggle').addEventListener('click',async()=>{
 if(!settings?.mercadopago_ready)return;
 let payment=$('#payment-toggle').checked,sales=$('#sales-toggle').checked;
 if(sales&&!payment){$('#payment-toggle-feedback').textContent='Ative pagamentos antes de abrir vendas.';return;}
 if(sales&&!confirm('Habilitar SOMENTE o Checkout Pro de TESTE? Nenhum cliente real deve receber este link.'))return;
 try {await api('/api/admin/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payment_enabled:payment,sales_enabled:sales})});$('#payment-toggle-feedback').textContent='Configuração atualizada. Atualize o site para refletir as mudanças.';await loadSettings();}catch(e){$('#payment-toggle-feedback').textContent=e.message;}
});
let leads=[],currentLeadId='';
async function loadLeads(){let d=await api('/api/admin/leads');leads=d.leads;renderLeads();}
function renderLeads(){let q=$('#lead-search').value.trim().toLowerCase(),filtered=leads.filter(l=>!q||[l.name,l.city,l.segment,l.phone,l.stage].join(' ').toLowerCase().includes(q));$('#lead-list').innerHTML=filtered.length?filtered.map(l=>{
let phone=l.phone.replace(/\D/g,'');let canMessage=/^\d{10,15}$/.test(phone)&&l.stage!=='sem_interesse';
let msg=encodeURIComponent(`Olá, ${l.name.split(' ')[0]}! Trabalho com o StayVision, um estúdio de conteúdo visual para imóveis e hospedagens. Gostaria de apresentar uma demonstração do nosso trabalho?`);
return `<div style="border:1px solid #dce9d8;border-radius:7px;padding:15px"><b style="font-size:14px">${h(l.name)}</b><span class="status-tag" style="float:right">${h(l.stage.replaceAll('_',' '))}</span><p style="margin:11px 0 6px;font-size:12px">${h(l.segment)} · ${h(l.city||'Sem cidade')}</p><p style="font-size:11px;color:#7b8878">${h(l.phone)}</p><div style="display:flex;flex-wrap:wrap;gap:7px;margin-top:13px"><button class="btn-alt" type="button" data-edit-lead="${h(l.id)}">Editar</button>${canMessage?`<a class="btn-alt" href="https://wa.me/${phone}?text=${msg}" target="_blank" rel="noopener noreferrer">Abrir WhatsApp ↗</a>`:''}</div></div>`}).join(''):'<p>Nenhum contato encontrado.</p>';
$$('[data-edit-lead]').forEach(b=>b.addEventListener('click',()=>editLead(b.dataset.editLead)));}
function resetLead(){currentLeadId='';$('#lead-form').reset();$('#lead-form-title').textContent='Novo contato';$('#lead-feedback').textContent='';}
function editLead(id){let l=leads.find(x=>x.id===id);if(!l)return;currentLeadId=l.id;for(let key of ['name','phone','segment','city','source','stage','notes'])$('#lead-'+key).value=l[key]||'';$('#lead-form-title').textContent='Editar '+l.name;$('#lead-form').scrollIntoView({behavior:'smooth'});}
$('#lead-form').addEventListener('submit',async e=>{e.preventDefault();let payload={id:currentLeadId};for(let key of ['name','phone','segment','city','source','stage','notes'])payload[key]=$('#lead-'+key).value;try{await api('/api/admin/lead',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});resetLead();await loadLeads();$('#lead-feedback').textContent='Contato salvo com sucesso.';}catch(err){$('#lead-feedback').textContent=err.message;}});
$('#lead-reset').addEventListener('click',resetLead);$('#leads-refresh').addEventListener('click',loadLeads);$('#lead-search').addEventListener('input',renderLeads);
$('#lead-csv').addEventListener('click',()=>{let cols=['name','phone','segment','city','source','stage','notes','created_at'];let csv=[cols.join(';'),...leads.map(l=>cols.map(c=>{let val=String(l[c]||'');if(/^[=+@-]/.test(val))val="'"+val;return '"'+val.replace(/"/g,'""')+'"';}).join(';'))].join('\r\n');let blob=new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='stayvision_contatos.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);});
start().then(()=>Promise.all([checkCheckoutReadiness(),stage7Readiness()])).catch(e=>{console.error(e);showLogin();$('#auth-feedback').textContent=e.message;});

// StayVision Railway: nenhuma venda real e nenhum registro manual de pagamentos nesta etapa.
$('#pix-diagnostic-btn').disabled=true; // Teste de Pix continua desligado na Railway; produção permite apenas GET.
