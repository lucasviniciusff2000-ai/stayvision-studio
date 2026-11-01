(function(){
const menu=document.getElementById('mobile-menu'),nav=document.getElementById('nav-items');
menu.addEventListener('click',()=>{const next=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(next));nav.classList.toggle('open',next)});
nav.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{nav.classList.remove('open');menu.setAttribute('aria-expanded','false')}));


const portfolio=document.getElementById('portfolio-preview');
const portfolioData={
 food:{title:'Alimentação & Delivery',company:'Brasa Prime Burger',src:'/assets/portfolio_brasa_phone_v311.webp',desc:'Perfil de hamburgueria com bio, destaques e publicações de produtos.'},
 fashion:{title:'Moda & Acessórios',company:'Royal Black',src:'/assets/portfolio_royal_burger_style_v313.webp',desc:'Mockup ilustrativo da Royal Black com bio, destaques e feed de moda.'},
 tech:{title:'Tecnologia & Eletrônicos',company:'Tech House',src:'/assets/portfolio_tech_burger_style_v313.webp',desc:'Mockup ilustrativo Tech House com produtos tecnológicos, bio, destaques e feed.'}
};
document.querySelectorAll('[data-portfolio]').forEach(link=>link.addEventListener('click',e=>{
 e.preventDefault();const item=portfolioData[link.dataset.portfolio];if(!item)return;
 document.getElementById('preview-heading').textContent=item.title;
 document.getElementById('preview-company').textContent=item.company;
 document.getElementById('preview-description').textContent=item.desc;
 const img=document.getElementById('preview-phone-image');img.src=item.src;img.alt='Prévia completa do perfil '+item.company;
 portfolio.showModal();
}));
document.getElementById('preview-close').addEventListener('click',()=>portfolio.close());
portfolio.addEventListener('click',e=>{if(e.target===portfolio)portfolio.close()});
document.getElementById('preview-plan-link').addEventListener('click',()=>portfolio.close());

const track=document.getElementById('track-dialog');document.getElementById('track-link').addEventListener('click',e=>{e.preventDefault();track.showModal()});document.getElementById('track-cancel').addEventListener('click',()=>track.close());
document.getElementById('track-open').addEventListener('click',()=>{const raw=document.getElementById('track-input').value.trim(),err=document.getElementById('track-error');let token='';try{const u=new URL(raw,location.origin);if(u.origin!==location.origin)throw new Error('host');const found=u.pathname.match(/^\/acompanhar\/([A-Za-z0-9_-]{43})$/);if(found)token=found[1]}catch(_e){}if(!token&&/^[A-Za-z0-9_-]{43}$/.test(raw))token=raw;if(!token){err.textContent='Cole um link privado válido da StayVision.';return;}window.location.href='/acompanhar/'+encodeURIComponent(token)});
})();
