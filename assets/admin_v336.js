'use strict';
// StayVision Business V3.9 dashboard. All displayed orders/counters come from the local API.
const el=id=>document.getElementById(id);
let csrf='',orders=[],selected=null,busy=false,aiReady=false,publicServer=false,autoQueueEnabled=false,autoDeliveryEnabled=false,view='overview',page=0,financeData=null;
const PAGE_SIZE=5;
let lastBalancePoll=0,balanceInFlight=false;
// V3.36: consulta iniciada assim que a sessão admin é exibida; independente do carregamento de pedidos.
async function refreshFalBalance(force=false){
 if(el('adminview').classList.contains('hidden')||balanceInFlight)return;
 const now=Date.now();if(lastBalancePoll&&now-lastBalancePoll<(force?20000:120000))return;
 lastBalancePoll=now;balanceInFlight=true;
 const btn=el('falBalanceButton'),label=el('falBalanceValue');btn.disabled=true;label.textContent='Consultando…';
 try{
   const response=await fetch('/api/admin/fal-balance',{cache:'no-store',credentials:'same-origin'});
   const d=await response.json();
   if(!response.ok||!d.ok){label.textContent='Indisponível';btn.title=String(d.error||'Falha ao consultar saldo');return;}
   const v=Number(d.balance);if(!Number.isFinite(v))throw Error('Saldo inválido');
   label.textContent=new Intl.NumberFormat('pt-BR',{style:'currency',currency:d.currency||'USD'}).format(v);
   btn.title='Saldo fal.ai atualizado. Clique para consultar novamente.';
 }catch(e){label.textContent='Indisponível';btn.title='Consulta fal.ai indisponível';}
 finally{btn.disabled=false;balanceInFlight=false;}
}

const stage={AGUARDANDO_PAGAMENTO:'Aguardando pagamento',PREPARADO_SEM_CREDITOS:'Aguardando produção',EM_PRODUCAO:'Em produção',REVISAO_NECESSARIA:'Em revisão',INTERROMPIDO_SEM_REPETICAO:'Interrompido'};
function node(tag,text=null,cls=''){const n=document.createElement(tag);if(text!==null)n.textContent=String(text);if(cls)n.className=cls;return n;}
function add(parent,tag,text=null,cls=''){const n=node(tag,text,cls);parent.append(n);return n;}
function showLogin(){el('loginview').classList.remove('hidden');el('adminview').classList.add('hidden');csrf='';lastBalancePoll=0;el('falBalanceValue').textContent='US$ —';}
function showAdmin(){el('loginview').classList.add('hidden');el('adminview').classList.remove('hidden');refreshFalBalance(true);}
function notify(message){el('toast').textContent=message||'';}
async function api(path,body=null){const options={cache:'no-store',credentials:'same-origin',headers:{}};if(body!==null){options.method='POST';options.headers['Content-Type']='application/json';options.headers['X-SV-CSRF']=csrf;options.body=JSON.stringify(body);}const r=await fetch(path,options);const data=await r.json();if(!r.ok){if(r.status===401&&path!=='/api/admin/login')showLogin();throw Error(data.error||'Falha na requisição');}return data;}
function safeDate(s){if(!s)return '—';const dt=new Date(s);if(!Number.isFinite(dt.getTime()))return '—';return dt.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'});}
function label(o){if(o.review==='APROVADO')return ['Aprovado','good'];if(o.production==='EM_PRODUCAO')return ['Em produção','good'];if(o.production==='REVISAO_NECESSARIA')return ['Em revisão','review'];if(o.production==='INTERROMPIDO_SEM_REPETICAO')return ['Interrompido',''];if(o.payment==='VERIFICADO_PROVEDOR')return ['Pagamento real aprovado','good'];if(o.payment==='ESTORNADO_PROVEDOR')return ['Estornado',''];if(o.payment==='CONTESTADO_PROVEDOR')return ['Contestado',''];if(o.payment==='SANDBOX_APROVADO')return ['Aprovado sandbox','good'];if(o.payment==='DEMO_PAGO')return ['Pagamento simulado','good'];return ['Aguardando pagamento',''];}
function percentage(o){const p=Number(o.progress_percent);if(o.review==='APROVADO')return 100;return Number.isFinite(p)?Math.max(0,Math.min(100,Math.round(p))):0;}
function avatar(name){const n=node('span','✧','client-avatar');if(/royal/i.test(name))n.textContent='♛';else if(/burger|brasa|lanche|pizza/i.test(name))n.textContent='♨';else if(/tech|eletr/i.test(name))n.textContent='⌘';else n.textContent=String(name||'?').slice(0,1).toUpperCase();return n;}
function statusTag(o){const [text,type]=label(o);return node('span','● '+text,'status-tag '+type);}
function planName(o){return o.plan==='Feed Premium'?'Premium':(o.plan||'—');}
function createBar(progress,cls){const bar=node('div',null,cls||'progress-track');const fill=node('span',null,cls?'':'progress-fill');if(cls)fill.style.width=progress+'%';else fill.style.width=progress+'%';bar.append(fill);return bar;}
function getFiltered(){const query=el('search').value.trim().toLocaleLowerCase('pt-BR'),status=el('filter').value,plan=el('planFilter').value,period=el('dateFilter').value;
 const now=Date.now();let a=orders.filter(o=>(o.brand||'').toLocaleLowerCase('pt-BR').includes(query)||(o.id||'').toLowerCase().includes(query));
 if(view==='production')a=a.filter(o=>o.production==='EM_PRODUCAO');
 if(view==='review')a=a.filter(o=>o.production==='REVISAO_NECESSARIA'&&o.review!=='APROVADO');
 if(view==='gallery')a=a.filter(o=>o.review==='APROVADO');
 if(view==='clients'){const seen=new Set();a=a.filter(o=>{const name=(o.brand||'').toLocaleLowerCase('pt-BR');if(seen.has(name))return false;seen.add(name);return true;});}
 if(status!=='all')a=a.filter(o=>status==='APROVADO'?o.review==='APROVADO':o.payment===status||o.production===status);
 if(plan!=='all')a=a.filter(o=>o.plan===plan);
 if(period!=='all')a=a.filter(o=>{const t=new Date(o.created_utc).getTime();if(!Number.isFinite(t))return false;if(period==='today')return new Date(t).toDateString()===new Date().toDateString();return now-t<=Number(period)*86400000;});
 return a;
}
function setView(newView){view=newView;page=0;document.querySelectorAll('[data-view]').forEach(x=>{x.classList.toggle('active',x.dataset.view===view);x.setAttribute('aria-current',x.dataset.view===view?'page':'false');});
 const copy={overview:['Painel administrativo','Centro de operações da StayVision Business. Gerencie pedidos, pagamentos, produção, revisão e entrega em um só lugar.'],orders:['Pedidos','Todos os pedidos registrados na StayVision.'],clients:['Clientes','Empresas que cadastraram pedidos na StayVision.'],production:['Produção','Acompanhe os pedidos que estão sendo processados.'],review:['Revisão','Confira as artes antes de liberar a galeria ao cliente.'],gallery:['Galeria','Pedidos aprovados e seus materiais de entrega.'],finance:['Financeiro','Pagamentos de demonstração não representam faturamento real.'],settings:['Configurações','Informações do ambiente e acesso do operador.']};
 el('pageTitle').textContent=copy[view][0];el('pageSubtitle').textContent=copy[view][1];
 if(view==='settings')notify('Painel protegido por login. Pagamentos reais são conciliados pela API do Mercado Pago.');
 else if(view==='finance')notify('Valores simulados, separados do faturamento real.');
 else notify('');renderContext();renderList();
}
function renderContext(){
 const root=el('viewContext');root.replaceChildren();root.classList.toggle('finance-context',view==='finance');
 if(view==='finance'){
  root.classList.remove('hidden');
  const f=financeData;
  if(!f){add(root,'p','Carregando financeiro...');return;}
  root.classList.add('finance-context');
  const money=c=>(Number(c||0)/100).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  const pilot=f.pilot_real||{};
  const plans=Array.isArray(f.by_plan)?f.by_plan:[];
  const periods=Array.isArray(f.monthly)?f.monthly:[];
  const totalOrders=plans.reduce((n,p)=>n+(Number(p.orders)||0),0);
  const paidReal=Number(f.real_paid_orders)||0;
  const dashboard=add(root,'div',null,'fin-dashboard');
  const header=add(dashboard,'div',null,'fin-hero');
  const intro=add(header,'div',null,'fin-hero-copy');
  add(intro,'span','GESTÃO FINANCEIRA · STAYVISION BUSINESS','fin-eyebrow');
  add(intro,'h2','Seu negócio em números');
  add(intro,'p','Acompanhe os planos, os pedidos e a evolução das vendas com valores reais e testes claramente separados.');
  const heroFlag=add(header,'div',null,'fin-hero-flag');
  add(heroFlag,'span','PEDIDOS DA STAYVISION','fin-hero-flag-top');
  add(heroFlag,'strong','Relatório gerencial');
  add(heroFlag,'small','Atualizado com os pedidos registrados');
  const notices=add(dashboard,'div',null,'fin-notices');
  const pilotNotice=add(notices,'div',null,'fin-notice fin-notice-pilot');
  add(pilotNotice,'strong','PILOTO REAL · '+(pilot.status==='APROVADO_REAL'?'APROVADO':(pilot.status||'NÃO CONFIRMADO').replaceAll('_',' ')));
  add(pilotNotice,'span','Piloto administrativo separado do faturamento comercial dos quatro planos.');
  const sandboxNotice=add(notices,'div',null,'fin-notice fin-notice-sandbox');
  add(sandboxNotice,'strong','SANDBOX · '+(Number(f.sandbox_confirmed_orders)||0)+' PAGAMENTO(S)');
  add(sandboxNotice,'span','Transações fictícias, sem faturamento comercial.');
  const cards=add(dashboard,'div',null,'fin-kpis');
  const kpis=[
    ['Faturamento comercial real',money(f.real_revenue_cents),`${paidReal} pagamento(s) integral(is) confirmado(s) pelo Mercado Pago`,'real'],
    ['Vendas confirmadas',String(paidReal),`${totalOrders} pedido(s) cadastrado(s) no ambiente`,'paid'],
    ['Valor dos pedidos',money(f.estimated_pipeline_cents),'Potencial pelo catálogo · não é receita recebida','pipeline'],
    ['Clientes cadastrados',String(Number(f.unique_clients)||0),'Empresas distintas identificadas por nome','clients'],
    ['Pagamentos simulados',money(f.demo_total_cents),`${Number(f.demo_paid_orders)||0} pedido(s) de demonstração`, 'demo']
  ];
  for(const [label,value,desc,kind] of kpis){
    const card=add(cards,'article',null,'fin-kpi fin-kpi-'+kind);
    add(card,'span',label,'fin-kpi-label');
    add(card,'strong',value,'fin-kpi-value');
    add(card,'p',desc,'fin-kpi-desc');
  }
  const charts=add(dashboard,'div',null,'fin-charts');
  const ranking=add(charts,'section',null,'fin-chart-panel');
  add(ranking,'span','DESEMPENHO','fin-eyebrow');
  add(ranking,'h3','Planos mais solicitados');
  add(ranking,'p','Classificação por pedidos registrados, não por vendas pagas.','fin-chart-subtitle');
  const max=Math.max(1,...plans.map(x=>Number(x.orders)||0));
  for(const [i,x] of plans.entries()){
    const row=add(ranking,'div',null,'fin-plan');
    const hdr=add(row,'div',null,'fin-plan-top');
    add(hdr,'span',String(i+1).padStart(2,'0'),'fin-plan-rank');
    add(hdr,'b',x.plan,'fin-plan-name');
    add(hdr,'strong',`${Number(x.orders)||0} pedido(s)`,'fin-plan-count');
    const bar=add(row,'div',null,'fin-track');
    const fill=add(bar,'span',null,'fin-fill');fill.style.width=((Number(x.orders)||0)/max*100)+'%';
    const details=add(row,'div',null,'fin-plan-meta');
    add(details,'span',`${Number(x.real_paid_orders)||0} venda(s) real(is)`);
    add(details,'span',`${Number(x.demo_paid_orders)||0} simulado(s)`);
  }
  const monthly=add(charts,'section',null,'fin-chart-panel');
  add(monthly,'span','EVOLUÇÃO','fin-eyebrow');
  add(monthly,'h3','Pedidos ao longo do tempo');
  add(monthly,'p','Evolução mensal dos pedidos e das vendas reais confirmadas.','fin-chart-subtitle');
  const monthMax=Math.max(1,...periods.map(x=>Number(x.orders)||0));
  if(!periods.length)add(monthly,'p','Ainda não há pedidos para apresentar neste gráfico.','fin-empty');
  for(const x of periods){
    const row=add(monthly,'div',null,'fin-month-row');
    const line=add(row,'div',null,'fin-month-top');
    add(line,'b',x.period||'Sem data');
    add(line,'span',`${Number(x.orders)||0} pedido(s)`);
    const track=add(row,'div',null,'fin-track fin-month-track');
    const fill=add(track,'span',null,'fin-fill');fill.style.width=((Number(x.orders)||0)/monthMax*100)+'%';
    const meta=add(row,'div',null,'fin-plan-meta');
    add(meta,'span','Receita real: '+money(x.real_revenue_cents));
    add(meta,'span',`${Number(x.demo_paid_orders)||0} teste(s) simulado(s)`);
  }
  const footer=add(dashboard,'div',null,'fin-disclaimer');
  add(footer,'strong','Sobre os valores exibidos');
  add(footer,'p','Faturamento comercial inclui apenas pagamentos integrais verificados na API do Mercado Pago. O piloto de R$ 1,00, o sandbox, as simulações e pedidos pendentes não compõem a receita comercial. Taxas, estornos e custos da IA precisam de conciliação antes do cálculo de lucro.');
 }else if(view==='settings'){
  root.classList.remove('hidden');add(root,'div','⚙','context-icon');const item=add(root,'div');add(item,'strong','Configuração comercial online');add(item,'p','Login do administrador protegido. As opções de pagamento e IA são gerenciadas nas variáveis privadas da Railway.');
 }else if(view==='clients'){
  root.classList.remove('hidden');add(root,'div','♧','context-icon');const item=add(root,'div');add(item,'strong','Clientes cadastrados: '+new Set(orders.map(o=>String(o.brand||'').toLocaleLowerCase('pt-BR'))).size);add(item,'p','Cada empresa aparece uma vez nesta visão; selecione para consultar o pedido mais recente.');
 }else root.classList.add('hidden');
}
function renderList(){const a=getFiltered();const count=a.length;const maxPage=Math.max(0,Math.ceil(count/PAGE_SIZE)-1);page=Math.min(maxPage,page);const list=el('orders');list.replaceChildren();el('listCount').textContent=count+' itens';el('paginationInfo').textContent=count?`Mostrando ${page*PAGE_SIZE+1}–${Math.min(count,(page+1)*PAGE_SIZE)} de ${count} pedidos`:'Nenhum pedido no filtro';
 if(count===0){list.append(node('div','Nenhum pedido encontrado. Ajuste os filtros ou cadastre um pedido pelo site do cliente.','empty-orders'));}
 for(const o of a.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)){
   const row=node('button',null,'orderitem'+(selected===o.id?' selected':''));row.type='button';row.setAttribute('aria-label','Abrir pedido '+o.brand);row.onclick=()=>detail(o.id);
   const left=add(row,'div',null,'client-cell');left.append(avatar(o.brand));const cname=add(left,'div',null,'client-text');add(cname,'strong',o.brand);add(cname,'small',o.id);
   add(row,'span',planName(o),'plan-tag');row.append(statusTag(o));const prog=add(row,'div',null,'progress-small');add(prog,'span',percentage(o)+'%');prog.append(createBar(percentage(o)));
   add(row,'span',safeDate(o.created_utc),'time-cell');add(row,'span','Abrir ›','open-cell');list.append(row);
 }
 const root=el('pagination');root.replaceChildren();if(maxPage>0){const prev=add(root,'button','‹','page-btn');prev.disabled=page===0;prev.onclick=()=>{page--;renderList();};for(let i=0;i<=maxPage&&i<7;i++){const p=add(root,'button',String(i+1),'page-btn'+(page===i?' active':''));p.onclick=()=>{page=i;renderList();};}if(maxPage>6)add(root,'span','…');const next=add(root,'button','›','page-btn');next.disabled=page===maxPage;next.onclick=()=>{page++;renderList();};}
}
async function login(e){e.preventDefault();const err=el('loginError');err.textContent='Verificando acesso...';try{const data=await api('/api/admin/login',{username:el('loginUser').value.trim(),password:el('loginCode').value,operator_code:el('loginCode').value.trim()});csrf=data.csrf;el('loginCode').value='';err.textContent='';showAdmin();await refresh();}catch(error){err.textContent=error.message;}}
async function refresh(){if(busy)return;busy=true;try{const s=await api('/api/admin/overview');orders=s.orders||[];financeData=s.finance||null;const m=s.summary;el('countAll').textContent=m.orders;el('countPending').textContent=m.pending_payment;el('countWork').textContent=m.producing;el('countApproved').textContent=m.approved;const plans=[...new Set(orders.map(o=>o.plan).filter(Boolean))];const select=el('planFilter');const current=select.value;select.replaceChildren(new Option('Todos os planos','all'));for(const p of plans)select.append(new Option(p,p));select.value=plans.includes(current)?current:'all';renderContext();renderList();refreshFalBalance();if(selected&&orders.some(o=>o.id===selected)&&!el('details').querySelector('.detail-review:focus-within')&&!el('details').querySelector('[data-check]:checked'))await detail(selected,false);else if(selected){selected=null;renderEmptyDetail();} }catch(e){notify(e.message)}finally{busy=false;}}
function renderEmptyDetail(){const root=el('details');root.className='detailEmpty';root.replaceChildren(add(node('div',null),'div','▣','empty-detail-icon'),node('h2','Selecione um pedido'),node('p','Escolha uma empresa para conferir os dados, andamento e ações disponíveis.'));}
function actionButton(text,fn,kind='',disabled=false){const b=node('button',text,'btn '+kind);b.type='button';b.disabled=disabled;b.onclick=fn;return b;}
function detailMeta(parent,name,value){const c=add(parent,'div',null,'meta-item');add(c,'span',name);add(c,'strong',value||'—');}
function stepper(root,o){const stages=['Pedido','Pagamento','Produção','Revisão','Entrega'];let max=0;
 if(o.payment==='SANDBOX_APROVADO'||o.payment==='DEMO_PAGO'||o.payment==='VERIFICADO_PROVEDOR')max=1;if(o.production==='EM_PRODUCAO')max=2;if(o.production==='REVISAO_NECESSARIA')max=3;if(o.review==='APROVADO')max=4;
 const bar=add(root,'div',null,'stepper');stages.forEach((label,i)=>{const st=add(bar,'div',null,'step'+(i<max?' done':'')+(i===max?' current':''));add(st,'div',i<max?'✓':i===max?'•':'','step-circle');add(st,'strong',label);add(st,'small',i<max?'Concluído':i===max?'Atual':'Aguardando');});}
async function detail(id,rerender=true){selected=id;if(rerender)renderList();const root=el('details');root.className='';root.replaceChildren(node('p','Carregando detalhes...','muted'));
 try{
  const d=await api('/api/admin/orders/'+id),o=d.order;root.replaceChildren();
  const hd=add(root,'div',null,'detail-head');hd.append(avatar(o.brand));const cp=add(hd,'div',null,'detail-head-copy');add(cp,'h2',o.brand);add(cp,'p',d.instagram||'Instagram não informado');add(hd,'span',o.id,'detail-id');
  const meta=add(root,'div',null,'detail-metadata');detailMeta(meta,'Contato',d.contact);detailMeta(meta,'Plano',planName(o));detailMeta(meta,'Pagamento',o.payment==='VERIFICADO_PROVEDOR'?(o.e2e_trial?'PILOTO REAL R$ 1,00 (1 foto)':'Aprovado REAL (plano)'):o.payment==='ESTORNADO_PROVEDOR'?'Estornado':o.payment==='CONTESTADO_PROVEDOR'?'Contestado':o.payment==='SANDBOX_APROVADO'?'Aprovado no sandbox (teste)':o.payment==='DEMO_PAGO'?'Simulado (teste)':'Pendente');
  const prog=percentage(o);const line=add(root,'div',null,'section-line');add(line,'span','▣  Produção');add(line,'span',`Progresso: ${prog}%`);root.append(createBar(prog,'progress'));add(root,'p','Etapa atual: '+(o.phase||label(o)[0]),'production-step');stepper(root,o);
  const actions=add(root,'div',null,'actions');
  if(!publicServer&&o.payment==='PENDENTE'&&!d.checkout_real)actions.append(actionButton('▤  Simular pagamento',()=>act(id,'demo-payment','SIMULAR_PAGAMENTO')));
  if((o.payment==='DEMO_PAGO'||o.payment==='VERIFICADO_PROVEDOR')&&o.production==='PREPARADO_SEM_CREDITOS'){
   if(publicServer&&autoQueueEnabled)actions.append(actionButton('Aguardando fila automática',()=>{},'ghost',true));
   else if(!publicServer)actions.append(actionButton('▶  Autorizar produção',()=>act(id,'start-production','AUTORIZO_PRODUCAO_COM_CUSTOS'),'primary',!aiReady));
  }
  if(o.production==='REVISAO_NECESSARIA'){
   const preview=add(actions,'a','✎  Revisar no painel','btn ghost');preview.href='/painel';preview.target='_blank';preview.rel='noopener';
  }
  if(o.review==='APROVADO'&&d.quality?.delivery_link){const l=add(actions,'a','▧  Abrir galeria aprovada','btn primary');l.href=d.quality.delivery_link;l.target='_blank';l.rel='noopener noreferrer';actions.append(actionButton('Copiar link da galeria',()=>copyDeliveryLink(d.quality.delivery_link),'ghost'));actions.append(actionButton('Revogar acesso',()=>act(id,'revoke',''),'ghost'));}
  if(publicServer)actions.append(actionButton('Copiar novo link de acompanhamento',()=>newTrackingLink(id),'ghost'));
  if(d.checkout_real){actions.append(actionButton('Consultar pagamento REAL do plano',()=>checkPlan(id),'ghost'));}
  const pil=d.pilot_real||{};
  if(pil.enabled&&!pil.taken){actions.append(actionButton('TESTE CONTROLADO: gerar checkout REAL R$ 1,00',()=>createPilot(id),'ghost'));}
  if(pil.taken&&pil.order_id===id){
   const section=add(root,'div',null,'pilot-box');add(section,'p','Piloto de pagamento REAL separado do plano — R$ 1,00 · '+(pil.status||'—'),'notice');
   if(pil.url){const l=add(section,'a','Abrir checkout REAL de R$ 1,00 (somente operador)','btn ghost');l.href=pil.url;l.target='_blank';l.rel='noopener noreferrer';}
   if(pil.enabled&&pil.preference_id)section.append(actionButton('Consultar o pagamento REAL no Mercado Pago',()=>checkPilot(id),'ghost'));
  }
  if(!actions.children.length){actions.append(actionButton('Aguardando próxima etapa',()=>{},'ghost',true));}
  if(!publicServer&&!aiReady&&(o.payment==='DEMO_PAGO'||o.payment==='VERIFICADO_PROVEDOR')&&o.production==='PREPARADO_SEM_CREDITOS')add(root,'p','A IA não está habilitada neste ambiente local.','notice');
  if(d.errors?.length)add(root,'p','Erros registrados: '+d.errors.join(' · '),'notice');
  if(o.production==='REVISAO_NECESSARIA'&&o.review!=='APROVADO'){
   const box=add(root,'section',null,'detail-review');add(box,'h3','Revisão obrigatória antes da entrega');
   const audit=d.auto_delivery;
   if(audit?.status==='REVISAO_NECESSARIA'&&audit.issues?.length)add(box,'p','Auditoria automática reteve a entrega: '+audit.issues.join('; '),'notice');
   else if(audit?.status==='AUDITORIA_PENDENTE')add(box,'p','Auditoria automática pendente. Atualize o pedido após alguns segundos.','notice');
   else if(audit?.status==='VERIFICAR_RESERVA')add(box,'p','Reserva automática inconclusiva. Confira manualmente antes de liberar.','notice');
   if(d.quality?.missing?.length)add(box,'p','Arquivos pendentes: '+d.quality.missing.join('; '),'notice');
   const checklist=[['identidade','Identidade preservada'],['produto','Produtos fiéis às fotos'],['texto','Bio, legendas e dados corretos'],['arquivos','Arquivos e prévias conferidos']];
   for(const [key,text] of checklist){const wrap=add(box,'label',null,'checkline');const input=add(wrap,'input');input.type='checkbox';input.dataset.check=key;add(wrap,'span',text);}
   const note=add(box,'textarea');note.className='note';note.id='reviewNote';note.placeholder='Observações da revisão (opcional)';
   const buttons=add(box,'div',null,'actions');buttons.append(actionButton('✓ Aprovar e liberar',()=>submitReview(id,'approved'),'primary'),actionButton('✕ Reprovar',()=>submitReview(id,'rejected'),'danger'));
  }
  const bottom=add(root,'div',null,'detail-bottom');add(bottom,'h3','◷  Atividades recentes');const recent=add(bottom,'div',null,'activity');add(recent,'b',label(o)[0]);add(recent,'p',o.phase||'Pedido registrado no acompanhamento.');const original=add(bottom,'div',null,'activity');add(original,'b','Pedido criado');add(original,'p',o.created_utc?new Date(o.created_utc).toLocaleString('pt-BR'):'Data não informada');
 }catch(e){root.replaceChildren(node('p',e.message,'bad'));}
}
async function copyPrivateUrl(url){
 try{await navigator.clipboard.writeText(url);notify('Link privado copiado. Envie somente ao cliente deste pedido.');}
 catch(e){window.prompt('Copie o link privado abaixo:',url);notify('Link privado exibido para cópia.');}
}
function copyDeliveryLink(path){
 if(!path||!path.startsWith('/entrega/')){notify('Link de entrega indisponível.');return;}
 return copyPrivateUrl(location.origin+path);
}
async function newTrackingLink(job){
 if(!window.confirm('Gerar NOVO link privado de acompanhamento para este pedido? O link original continuará válido. Não há cobrança nem uso de IA.'))return;
 try{
  const r=await api('/api/admin/orders/'+encodeURIComponent(job)+'/tracking-link',{confirm:'GERAR_LINK_PRIVADO'});
  if(!/^\/acompanhar\/[A-Za-z0-9_-]{43}$/.test(r.customer_link))throw Error('Resposta de link inválida.');
  const url=location.origin+r.customer_link;
  const actions=el('details').querySelector('.actions');
  if(actions){const box=add(actions,'div',null,'tracking-result');add(box,'span','Novo acompanhamento privado gerado');const a=add(box,'a','Abrir link do cliente');a.href=url;a.target='_blank';a.rel='noopener noreferrer';box.append(actionButton('Copiar novamente',()=>copyPrivateUrl(url),'ghost'));}
  await copyPrivateUrl(url);
 }catch(e){notify('Não foi possível emitir o link: '+e.message);}
}
async function checkPlan(job){try{const x=await api('/api/admin/plan-payment/check',{job});await refresh();await detail(job);notify('Mercado Pago: '+x.status);}catch(e){notify(e.message);}}
async function createPilot(job){
 const warning='ATENÇÃO: ESTE É UM PAGAMENTO REAL DE R$ 1,00. Pode haver taxas. Será permitida UMA ÚNICA tentativa nesta instalação. A operação não paga o plano nem libera a IA. Você deseja GERAR a cobrança?';
 if(!window.confirm(warning))return;
 const typed=window.prompt('Para gerar a cobrança real, digite exatamente: AUTORIZO UM PILOTO REAL DE R$ 1,00');
 if(typed!=='AUTORIZO UM PILOTO REAL DE R$ 1,00')return;
 try{await api('/api/admin/pilot/create',{job,confirm:typed});await refresh();await detail(job);notify('Checkout piloto criado. Abra o link somente se quiser efetuar o pagamento real de R$ 1,00.');}catch(e){notify(e.message);await detail(job);}
}
async function checkPilot(job){
 try{const d=await api('/api/admin/pilot/check',{job});await refresh();await detail(job);notify('Mercado Pago: '+d.pilot.status+' (piloto real, sem IA).');}catch(e){notify(e.message);}
}
async function act(id,verb,confirm){const warns={'demo-payment':'Esta ação registra apenas um PAGAMENTO SIMULADO, sem Pix ou dinheiro real.','start-production':'Atenção: iniciar chamadas REAIS da Gemini/fal.ai pode consumir créditos.','revoke':'Revogar o link de entrega existente?'};if(!window.confirm((warns[verb]||'Confirma a ação?')+'\nPedido: '+id))return;try{notify('Processando...');const r=await api('/api/admin/orders/'+id+'/'+verb,{confirm});await refresh();notify(r.message||'Concluído.');}catch(e){notify(e.message);}}
async function submitReview(id,decision){const checks={};for(const i of el('details').querySelectorAll('[data-check]'))checks[i.dataset.check]=i.checked;if(decision==='approved'&&!Object.values(checks).every(Boolean)){notify('Confirme os quatro itens antes de aprovar.');return;}if(!window.confirm((decision==='approved'?'Aprovar e LIBERAR galeria?':'Reprovar e BLOQUEAR entrega?')+'\nPedido: '+id))return;try{const r=await api('/api/admin/orders/'+id+'/review',{decision,checks,notes:el('reviewNote').value});await refresh();notify(r.message||'Revisão salva.');}catch(e){notify(e.message);}}
async function start(){el('falBalanceButton').addEventListener('click',()=>refreshFalBalance(true));el('loginform').addEventListener('submit',login);el('refresh').onclick=refresh;el('filterButton').onclick=()=>{page=0;renderList();};el('clearFilters').onclick=()=>{el('search').value='';el('globalSearch').value='';el('filter').value='all';el('planFilter').value='all';el('dateFilter').value='all';page=0;renderList();};el('search').oninput=()=>{page=0;renderList();};el('globalSearch').oninput=()=>{el('search').value=el('globalSearch').value;page=0;renderList();};el('filter').onchange=()=>{page=0;renderList();};el('planFilter').onchange=()=>{page=0;renderList();};el('dateFilter').onchange=()=>{page=0;renderList();};document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));el('logout').onclick=async()=>{try{await api('/api/admin/logout',{});}catch(e){}showLogin();};document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'&&!el('adminview').classList.contains('hidden')){e.preventDefault();el('globalSearch').focus();}});
 try{
  const r=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());
  publicServer=r.public_server===true;autoQueueEnabled=r.ai_queue_enabled===true;autoDeliveryEnabled=r.auto_delivery_enabled===true;
  aiReady=publicServer?autoQueueEnabled:Boolean(r.ai_ready&&r.image_ai_enabled);
  if(publicServer){
   el('sidebarEnvironment').textContent='☷  Produção online';
   el('sidebarPayments').textContent=r.real_plan_checkout_enabled?'● Mercado Pago real configurado':'● Checkout real indisponível';
   el('sidebarAI').textContent=autoQueueEnabled?'● Fila de IA configurada':'● Fila de IA indisponível';
   el('envModeText').textContent=r.real_plan_checkout_enabled?'CHECKOUT REAL DE PLANOS HABILITADO':'CHECKOUT REAL NÃO HABILITADO';
   el('envModeNote').textContent='Cobranças com valores integrais • Mercado Pago de produção';
   el('aiBanner').textContent=autoQueueEnabled?(autoDeliveryEnabled?'Fila de IA e entrega automática configuradas':'Fila de IA configurada · entrega sob revisão'):'Fila de IA indisponível';
  }else{
   el('sidebarEnvironment').textContent='☷  Ambiente local';
   el('sidebarPayments').textContent='● Testes separados de pagamentos reais';
   el('sidebarAI').textContent='● IA conforme configuração local';
   el('aiBanner').textContent=aiReady?'IA habilitada mediante autorização':'IA desativada neste modo';
  }
 }catch(e){el('aiBanner').textContent='Status da automação não verificado';}
 try{const s=await api('/api/admin/session');csrf=s.csrf;if(s.ok){showAdmin();await refresh();}}catch(e){showLogin();}
 setInterval(()=>{if(!el('adminview').classList.contains('hidden'))refresh();},12000);
}
start();
