/* StayVision: normaliza imagens no navegador sem chamadas pagas. */
(function(){'use strict';
const SUPPORTED=/\.(jpe?g|png|webp|heic|heif|avif|gif|bmp|tiff?)$/i;
const types={heic:'image/heic',heif:'image/heif',avif:'image/avif',tif:'image/tiff',tiff:'image/tiff',bmp:'image/bmp',gif:'image/gif',jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',webp:'image/webp'};
function dataUrl(file){return new Promise((ok,fail)=>{const r=new FileReader();r.onload=()=>ok(String(r.result));r.onerror=()=>fail(Error('Não foi possível ler o arquivo.'));r.readAsDataURL(file)})}
function toBlob(c,quality){return new Promise((ok,fail)=>c.toBlob(b=>b?ok(b):fail(Error('Não foi possível compactar a imagem.')),'image/jpeg',quality))}
async function read(file){
 if(!file || !(file.type.startsWith('image/') || SUPPORTED.test(file.name)))throw Error('Selecione uma foto em JPG, PNG, WebP, HEIC/HEIF, AVIF, TIFF, BMP ou GIF.');
 if(file.size>26e6)throw Error('Foto acima de 26 MB. Compacte antes de enviar.');
 let bitmap=null, url=null;
 try{
   if('createImageBitmap' in window)bitmap=await createImageBitmap(file,{imageOrientation:'from-image'});
   else{url=URL.createObjectURL(file);bitmap=await new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>reject(Error('Formato não legível pelo navegador.'));img.src=url});}
   const w=bitmap.width,h=bitmap.height;
   if(!w||!h||w*h>80e6)throw Error('Foto acima de 80 megapixels. Reduza antes de enviar.');
   const scale=Math.min(1,2400/Math.max(w,h));
   const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(w*scale));canvas.height=Math.max(1,Math.round(h*scale));
   const ctx=canvas.getContext('2d',{alpha:false});if(!ctx)throw Error('Navegador não conseguiu preparar a foto.');
   ctx.fillStyle='#f7f7f7';ctx.fillRect(0,0,canvas.width,canvas.height);
   ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
   let blob=await toBlob(canvas,.89);
   if(blob.size>7e6)blob=await toBlob(canvas,.76);
   const data=await dataUrl(blob);
   return {name:file.name,data,original_width:w,original_height:h,normalized_width:canvas.width,normalized_height:canvas.height,warning:Math.min(w,h)<500?'Foto pequena: avaliar nitidez na revisão.':''};
 }catch(e){
   // HEIC pode não ser renderizado pelo navegador; o servidor pode convertê-lo via pillow-heif.
   const ext=(file.name.split('.').pop()||'').toLowerCase();
   if(!['heic','heif','avif','tif','tiff'].includes(ext))throw e;
   let data=await dataUrl(file);const mime=types[ext];
   data=data.replace(/^data:[^;]*;base64,/,'data:'+mime+';base64,');
   return {name:file.name,data,warning:'Conversão deste formato será feita pelo servidor.'};
 }finally{if(bitmap && typeof bitmap.close==='function')bitmap.close();if(url)URL.revokeObjectURL(url)}
}
window.StayVisionImages={read};
})();
