const $=q=>document.querySelector(q),$$=q=>[...document.querySelectorAll(q)];
const h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL',maximumFractionDigits:0}).format(v);
const labels={recebido:'Recebido',aguardando_pagamento:'Pagamento pendente',em_producao:'Em produção',em_revisao:'Em revisão',concluido:'Concluído',cancelado:'Cancelado'};
async function api(path,options={}){let r=await fetch(path,{credentials:'same-origin',...options});let data=await r.json().catch(()=>({error:'Resposta inválida'}));if(!r.ok)throw Error(data.error||'Requisição falhou');return data;}
let currentOrder=null,orders=[],settings=null,initialized=false;
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
$('#edit-status').value=o.status;$('#edit-payment').value=o.payment_status;$('#edit-note').value=o.admin_note;$('#update-feedback').textContent='';$('#delivery-feedback').textContent='';$('#verify-feedback').textContent='';$('#mp-payment-id').value='';$('#order-editor').scrollIntoView({behavior:'smooth'});
}catch(err){alert(err.message);}}
$('#close-order').addEventListener('click',()=>{$('#order-editor').classList.add('hidden');currentOrder=null;});
$('#update-form').addEventListener('submit',async e=>{e.preventDefault();if(!currentOrder)return;try{await api('/api/admin/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:currentOrder.id,status:$('#edit-status').value,payment_status:$('#edit-payment').value,admin_note:$('#edit-note').value})});$('#update-feedback').textContent='Alterações salvas com sucesso.';await refresh();}catch(err){$('#update-feedback').textContent=err.message;}});
$('#verify-payment-form').addEventListener('submit',async e=>{e.preventDefault();if(!currentOrder)return;const feed=$('#verify-feedback');feed.textContent='Consultando o Mercado Pago...';try{const response=await api('/api/admin/verify-payment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:currentOrder.id,payment_id:$('#mp-payment-id').value.trim()})});await refresh();await openOrder(currentOrder.id);$('#verify-feedback').textContent='Consulta concluída: '+response.payment_status+' (Mercado Pago: '+response.provider_status+').';}catch(err){feed.textContent=err.message;}});
$('#delivery-form').addEventListener('submit',async e=>{e.preventDefault();if(!currentOrder)return;const f=$('#delivery-file').files[0];if(!f)return;if(f.size>94371840){$('#delivery-feedback').textContent='Arquivo maior que 90 MB.';return;}let form=new FormData();form.append('id',currentOrder.id);form.append('delivery',f);$('#delivery-feedback').textContent='Enviando arquivo, aguarde...';try{await api('/api/admin/deliver',{method:'POST',body:form});$('#delivery-feedback').textContent='Arquivo salvo! A entrega é liberada quando o pagamento estiver confirmado.';$('#edit-status').value='concluido';$('#delivery-file').value='';await refresh();}catch(err){$('#delivery-feedback').textContent=err.message;}});
async function loadSettings(){settings=await api('/api/admin/settings');$('#brand-setting').value=settings.brand_name;$('#whatsapp-setting').value=settings.contact_whatsapp;$('#settings-prices').innerHTML=settings.plans.map(p=>`<div><label for="price-${p.code}">${h(p.name)}</label><input class="input" type="number" min="1" max="100000" step="1" id="price-${p.code}" value="${p.price}"><p style="font-size:11px;color:#7b8978">${h(p.description)}</p></div>`).join('');$('#payment-toggles').classList.add('hidden');$('#pix-production-credential-status').textContent=settings.pix_production_diagnostic_ready?'Token de produção cadastrado no servidor (valor oculto).':'Token de produção ainda não cadastrado na Railway.';$('#payment-toggle').checked=!!settings.payment_enabled;$('#sales-toggle').checked=!!settings.sales_enabled;$('#payment-diagnostics').innerHTML='<b>Checkout real desativado.</b> Você pode conferir o Pix com a conta de produção em modo somente leitura. Nenhuma cobrança pode ser criada por esta versão.';}
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
    (latest?'Última: '+latest.received_at+' — '+latest.event_type+'. ':'')+
    'Nenhuma alteração de status de pagamento foi realizada.';
 }catch(e){output.textContent='Falha na consulta: '+e.message;}
});
$('#settings-form').addEventListener('submit',async e=>{e.preventDefault();if(!settings)return;try{let plans=settings.plans.map(p=>({...p,price:Number($('#price-'+p.code).value)}));await api('/api/admin/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plans,brand_name:$('#brand-setting').value,contact_whatsapp:$('#whatsapp-setting').value})});$('#settings-feedback').textContent='Configurações salvas. Atualize o site para ver os valores.';await loadSettings();}catch(err){$('#settings-feedback').textContent=err.message;}});
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
start().catch(e=>{console.error(e);showLogin();$('#auth-feedback').textContent=e.message;});

// StayVision Railway: nenhuma venda real e nenhum registro manual de pagamentos nesta etapa.
$('#pix-diagnostic-btn').disabled=true; // Teste de Pix continua desligado na Railway; produção permite apenas GET.
