'use strict';
const $ = id=>document.getElementById(id);
const PLANS={
 fotos:{name:'Fotos Business',price:'59,90',items:['6 fotos aprimoradas por IA','Comparativo antes e depois','Arquivo pronto para divulgação','Revisão visual de qualidade']},
 perfil:{name:'Perfil Express',price:'149,90',items:['Bio e posicionamento criativo','Foto de perfil com identidade','5 capas de destaques','Paleta e prévia do perfil']},
 vitrine:{name:'Vitrine Digital',price:'249,90',items:['Tudo do Perfil Express','6 artes para feed','4 stories personalizados','Legendas e prévia do feed']},
 premium:{name:'Feed Premium',price:'399,90',items:['Tudo da Vitrine Digital','Até 8 fotos profissionais','3 artes extras','Direção visual consistente']}
};
const SECTORS={"Alimentação & Delivery":{"name":"BRASA EXPRESS","handle":"@brasaexpress.delivery","type":"Hambúrgueres artesanais • Delivery","bio":"Smash burgers preparados na hora 🍔\nCombos, batatas e muito sabor 🔥\nConfira o cardápio e faça seu pedido ↓","color":"#FF6414","color2":"#FDB52A","logo":"flame","caption":"Burgers com presença de marca","desc":"Uma hamburgueria fictícia com um posicionamento claro: smash burgers, combos e pedidos. Nenhuma pizza misturada ao conteúdo.","highlights":["Cardápio","Combos","Pedidos","Contato"],"headlines":["SMASH DO DIA","COMBOS DA CASA","FEITO NA BRASA","DELIVERY COM SABOR"],"src":["card_fotos.webp","card_perfil_food.webp","burger_comercial_01.jpg","burger_comercial_02.jpg","burger_comercial_03.jpg"],"hero":"card_fotos.webp","key":"food","label":"ALIMENTAÇÃO & DELIVERY","words":["SMASH DO DIA","COMBOS DA CASA","FEITO NA BRASA","DELIVERY COM SABOR"]},"Moda & Acessórios":{"name":"ATELIÊ AURA","handle":"@atelieaura.style","type":"Moda feminina • Acessórios","bio":"Moda com personalidade, do casual ao especial ✨\nPeças e acessórios para seu estilo.\nDescubra a coleção e inspire seu próximo look ↓","color":"#F2448D","color2":"#FFA4C9","logo":"hanger","caption":"Sua coleção em evidência","desc":"Uma boutique demonstrativa com coleção, looks e acessórios — um feed editorial com linguagem própria.","highlights":["Coleções","Looks","Acessórios","Atendimento"],"headlines":["NOVA COLEÇÃO","LOOK DO DIA","SEU ESTILO","PEÇAS QUE INSPIRAM"],"src":["fashion_reference.png","sector_fashion.webp","sector_ref_2.webp"],"hero":"fashion_reference.png","key":"fashion","label":"MODA & ACESSÓRIOS","words":["NOVA COLEÇÃO","LOOK DO DIA","SEU ESTILO","PEÇAS QUE INSPIRAM"]},"Beleza & Cosméticos":{"name":"LUMIÈRE BEAUTY","handle":"@lumiere.beauty","type":"Beleza • Maquiagem e skincare","bio":"Beleza que valoriza sua autenticidade ✨\nMaquiagem, cuidado e rituais para você.\nConheça nossa curadoria e descubra favoritos ↓","color":"#DB77AB","color2":"#F4C7B4","logo":"sparkle","caption":"Seu ritual, sua essência","desc":"Uma marca fictícia de cosméticos: produtos, rituais e lançamentos em uma identidade rosé elegante.","highlights":["Produtos","Rotina","Novidades","Contato"],"headlines":["SEU RITUAL","NOVA LINHA","BELEZA REAL","CUIDADO EM DETALHES"],"src":["sector_beauty.webp","sector_ref_3.webp","fashion_reference.png"],"hero":"sector_beauty.webp","key":"beauty","label":"BELEZA & COSMÉTICOS","words":["SEU RITUAL","NOVA LINHA","BELEZA REAL","CUIDADO EM DETALHES"]},"Tecnologia & Eletrônicos":{"name":"NEXO TECH","handle":"@nexotech.store","type":"Eletrônicos • Acessórios e gadgets","bio":"Tecnologia com design e praticidade ⚡\nAcessórios e dispositivos para sua rotina.\nExplore os produtos e encontre seu próximo upgrade ↓","color":"#4B9CF8","color2":"#63DCFC","logo":"circuit","caption":"Upgrade seu dia","desc":"Uma loja fictícia de eletrônicos, com foco em dispositivos, acessórios e inovação visual.","highlights":["Produtos","Lançamentos","Ofertas","Suporte"],"headlines":["NEXT LEVEL","SEU NOVO SETUP","DESIGN INTELIGENTE","TECNOLOGIA TODO DIA"],"src":["sector_tech.webp","sector_ref_4.webp"],"hero":"sector_tech.webp","key":"tech","label":"TECNOLOGIA & ELETRÔNICOS","words":["NEXT LEVEL","SEU NOVO SETUP","DESIGN INTELIGENTE","TECNOLOGIA TODO DIA"]},"Casa & Decoração":{"name":"CASA ESSENZA","handle":"@casaessenza.decor","type":"Decoração • Ambientes e detalhes","bio":"Ambientes que acolhem e inspiram 🏡\nDesign, conforto e peças para a sua casa.\nEncontre novas ideias para transformar seu espaço ↓","color":"#D6A46B","color2":"#F6D3A3","logo":"home","caption":"Design que acolhe","desc":"Uma marca fictícia de decoração com ambientes, materiais e composições acolhedoras.","highlights":["Ambientes","Coleção","Inspiração","Contato"],"headlines":["CASA COM ALMA","NOVOS AMBIENTES","DETALHES ÚNICOS","SINTA-SE EM CASA"],"src":["sector_home.webp","sector_ref_5.webp"],"hero":"sector_home.webp","key":"home","label":"CASA & DECORAÇÃO","words":["CASA COM ALMA","NOVOS AMBIENTES","DETALHES ÚNICOS","SINTA-SE EM CASA"]},"Pets & Serviços":{"name":"PATA & CIA","handle":"@pataecia.pet","type":"Pet shop • Cuidado e bem-estar","bio":"Carinho em cada patinha 🐾\nCuidados, produtos e mimos para pets.\nConheça nossos serviços e fale com a equipe ↓","color":"#FFB24A","color2":"#92D9B8","logo":"paw","caption":"Amor de quatro patas","desc":"Um pet shop fictício com serviços, cuidados e produtos pensados para tutores.","highlights":["Serviços","Cuidados","Produtos","Contato"],"headlines":["PATAS FELIZES","CARINHO TODO DIA","NOSSO CUIDADO","MUNDO PET"],"src":["sector_pets.webp","sector_ref_7.webp"],"hero":"sector_pets.webp","key":"pets","label":"PETS & SERVIÇOS","words":["PATAS FELIZES","CARINHO TODO DIA","NOSSO CUIDADO","MUNDO PET"]},"Saúde & Fitness":{"name":"ATLAS FIT","handle":"@atlasfit.studio","type":"Treino • Fitness e movimento","bio":"Movimento que fortalece sua rotina 💪\nTreinos, disciplina e evolução possível.\nConheça o espaço e fale com nossa equipe ↓","color":"#95ED72","color2":"#47A6CE","logo":"dumbbell","caption":"Sua energia em movimento","desc":"Um estúdio fitness fictício focado em treinos, consistência e uma identidade esportiva própria.","highlights":["Treinos","Espaço","Agenda","Equipe"],"headlines":["TREINE FORTE","MAIS MOVIMENTO","ROTINA ATIVA","SEU PRÓXIMO PASSO"],"src":["sector_fitness.webp","sector_ref_6.webp"],"hero":"sector_fitness.webp","key":"fitness","label":"SAÚDE & FITNESS","words":["TREINE FORTE","MAIS MOVIMENTO","ROTINA ATIVA","SEU PRÓXIMO PASSO"]}};
let activeSector='Alimentação & Delivery', selectedPlan='perfil', activeStep=1;
const asset=n=>'assets/'+n;
const image=(filename,alt,classname='')=>{let x=document.createElement('img');x.src=asset(filename);x.alt=alt;x.loading='lazy';if(classname)x.className=classname;return x;};
function renderProfile(el, data, small){
 if(!el)return;el.replaceChildren();
 const head=document.createElement('div');head.className='profile-head';
 const ava=document.createElement('img');ava.src=asset('brand_'+data.key+'_logo.svg');ava.alt='Logotipo fictício '+data.name;ava.className='avatar';
 const info=document.createElement('div');info.className='profile-info';
 const handle=document.createElement('strong');handle.className='handle';handle.textContent=data.handle;
 const type=document.createElement('span');type.className='profile-type';type.textContent=data.name+' · '+data.type;
 const bio=document.createElement('p');bio.className='bio';bio.textContent=data.bio;
 info.append(handle,type,bio);head.append(ava,info);el.append(head);
 const actions=document.createElement('div');actions.className='profile-actions';
 if(small){actions.innerHTML='<span class="action-main">Seguir</span><span>Mensagem</span>';}else{actions.innerHTML='<span>Marca própria</span><span>Destaques coerentes</span><span>Campanhas variadas</span>';}
 el.append(actions);
 const stories=document.createElement('div');stories.className='story-line';
 const storyPhotos=[1,3,5,7];
 for(let i=0;i<4;i++){const item=document.createElement('div');item.className='story';const ic=document.createElement('div');ic.className='story-ring';ic.append(image(data.key+'_post_'+storyPhotos[i]+'.webp','Destaque '+(data.highlights[i]||'')));const lab=document.createElement('small');lab.textContent=data.highlights[i]||'Destaque';item.append(ic,lab);stories.append(item);}el.append(stories);
 const separator=document.createElement('div');separator.className='profile-divider';separator.textContent=small?'▦  PUBLICAÇÕES':'▦  CONTEÚDO VISUAL  ✦';el.append(separator);
 const feed=document.createElement('div');feed.className='profile-feed';
 for(let i=1;i<=9;i++){let f=document.createElement('div');f.className='feeditem';f.append(image(data.key+'_post_'+i+'.webp','Publicação demonstrativa '+i+' de '+data.name));feed.append(f);}el.append(feed);
}
function setSector(sector,scroll){
 let data=SECTORS[sector];if(!data)return;activeSector=sector;
 document.documentElement.style.setProperty('--seg-color',data.color);
 document.querySelectorAll('[data-sector]').forEach(b=>{const on=b.dataset.sector===sector;b.classList.toggle('selected',on);b.setAttribute('aria-pressed',on?'true':'false');});
 const intro=$('sectorintro');intro.textContent=data.label;
 $('currentSector').textContent=data.name+' · '+data.type;
 $('brandPitch').textContent=data.key==='food'?'BURGER É MAIS QUE COMIDA. É EXPERIÊNCIA.':data.caption;
 renderProfile($('phoneProfile'),data,true);
 renderProfile($('largeProfile'),data,false);
 $('sectorLabel').textContent='DEMONSTRAÇÃO · '+data.name;
 if(scroll) $('perfil').scrollIntoView({behavior:'smooth',block:'start'});
}
for(let btn of document.querySelectorAll('[data-sector]'))btn.addEventListener('click',()=>setSector(btn.dataset.sector,true));
setSector(activeSector,false);
function showOrder(plan){selectedPlan=PLANS[plan]?plan:'perfil';$('planSelect').value=selectedPlan;updateOrder();$('orderDialog').hidden=false;document.body.classList.add('modal-open');setStep(1);$('orderDialog').scrollTop=0;}
function closeOrder(){$('orderDialog').hidden=true;document.body.classList.remove('modal-open');}
function updateOrder(){let p=PLANS[selectedPlan];$('planSelect').value=selectedPlan;$('summaryTitle').textContent=p.name;$('summaryPrice').textContent='R$ '+p.price;$('summaryItems').replaceChildren(...p.items.map(t=>{let li=document.createElement('li');li.textContent=t;return li}));}
function setStep(n){activeStep=n;document.querySelectorAll('.order-step').forEach(x=>x.hidden=Number(x.dataset.step)!==n);document.querySelectorAll('.step-pill').forEach(x=>x.classList.toggle('active',Number(x.dataset.step)===n));$('orderDialog').scrollTop=0;}
function validateAndReview(){const form=$('orderForm');if(!form.reportValidity())return;const files=$('filesInput').files;const logo=$('brandLogo').files[0];
 if(files.length>8){$('orderError').textContent='Selecione no máximo oito fotos.';return;}
 for(const f of [...files,...(logo?[logo]:[])]){if(f.size>12*1024*1024){$('orderError').textContent='Arquivo acima de 12 MB: '+f.name;return;}}
 $('orderError').textContent='';let data=[['Plano',PLANS[selectedPlan].name],['Nome da empresa',$('brandName').value],['Instagram',$('instagram').value],['Contato',$('contact').value],['Ramo',$('businessType').value],['Identidade visual',logo?'Vamos preservar seu logotipo':'Vamos criar sua proposta de logotipo'],['Fotos de referência',files.length?String(files.length)+' foto(s)':'Nenhuma por enquanto']];
 $('reviewLines').replaceChildren(...data.map(([a,b])=>{let row=document.createElement('div');row.className='review-line';let l=document.createElement('span');l.textContent=a;let r=document.createElement('b');r.textContent=b;row.append(l,r);return row;}));setStep(3);
}
window.openOrder=showOrder;window.closeOrder=closeOrder;
$('planSelect').addEventListener('change',e=>{selectedPlan=e.target.value;updateOrder();});
$('toDetails').addEventListener('click',()=>setStep(2));$('backToPlans').addEventListener('click',()=>setStep(1));
$('orderForm').addEventListener('submit',e=>{e.preventDefault();validateAndReview()});
$('backToDetails').addEventListener('click',()=>setStep(2));
$('finishDemo').addEventListener('click',()=>setStep(4));
$('closeDone').addEventListener('click',closeOrder);
$('filesInput').addEventListener('change',e=>$('fileCount').textContent=e.target.files.length?e.target.files.length+' foto(s) selecionada(s) — não enviadas':'Nenhuma foto selecionada');
$('brandLogo').addEventListener('change',e=>$('logoHelp').textContent=e.target.files.length?'Logotipo recebido na prévia. Preservaremos a identidade existente.':'Se você tiver um logotipo, vamos preservar e valorizar sua marca. Se não tiver, criaremos uma proposta para você.');
$('orderClose').addEventListener('click',closeOrder);
$('orderDialog').addEventListener('click',e=>{if(e.target===$('orderDialog'))closeOrder()});
$('openTrack').addEventListener('click',()=>{document.querySelector('#trackDialog').hidden=false;});
$('trackClose').addEventListener('click',()=>{$('trackDialog').hidden=true});
$('navtoggle').addEventListener('click',()=>{$('navlinks').classList.toggle('open')});
document.querySelectorAll('#navlinks a').forEach(a=>a.addEventListener('click',()=>$('navlinks').classList.remove('open')));
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeOrder();$('trackDialog').hidden=true}});

// V3.8: connect existing tracking button to the private customer status link.
$('trackGo').addEventListener('click',()=>{
  const raw=$('trackLink').value.trim();let token='';
  try{const u=new URL(raw,location.origin);if(!['127.0.0.1','localhost'].includes(u.hostname))throw Error('local');
    const match=u.pathname.match(/^\/acompanhar\/([A-Za-z0-9_-]{43})$/);if(match)token=match[1];}
  catch(e){}
  if(!token&&/^[A-Za-z0-9_-]{43}$/.test(raw))token=raw;
  if(!token){$('trackWarning').textContent='Informe o link privado /acompanhar recebido no cadastro deste pedido.';return;}
  location.href='/acompanhar/'+encodeURIComponent(token);
});
