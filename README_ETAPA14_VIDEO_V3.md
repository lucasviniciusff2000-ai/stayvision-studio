# StayVision — Etapa 14: Video Engine V3 (estabilizado)

## Problema observado e mudança real

O vídeo V2 fazia `zoompan` com as posições da janela de zoom arredondadas no FFmpeg e aplicava zoom/pan contínuos. Bordas arquitetônicas pareciam vibrar e os cortes entre fotografias eram abruptos.

O motor V3 utiliza **OpenCV** com interpolação subpixel (`warpAffine`), trajetória *smootherstep* (derivadas nulas no início e fim), deslocamentos reduzidos e **crossfade de 0,5 s** entre cenas. Renderiza um único fluxo de quadros para o FFmpeg, sem concatenar clipes independentes com saltos.

**Isto NÃO é um serviço de vídeo generativo de IA.** É edição determinística fiel à foto. Também não é tour 3D. Não há promessa de caminhar entre ambientes.

## Instalação (mesma StayVision V1)

1. Guarde o backup atual do volume Railway `/data` (SQLite `stayvision.db`, uploads, entregas). O projeto instalável não contém banco nem fotos pessoais.
2. Substitua os arquivos da raiz do GitHub pelos do ZIP. **Importante:** o `Dockerfile` agora copia `video_engine_v3.py` para o container. Sem ele o render não funcionará.
3. Aguarde Railway `Active` e acesse `/painel` → Pedidos → Abrir → Produção inteligente.
4. Na seção **PHOTO ENGINE V3 · VIDEO V3**, escolha `Fotos + vídeo estável V3`, horizontal ou vertical, e inicie. Revise antes de entregar.
5. Não altere as credenciais do Mercado Pago. **Checkout público continua bloqueado até a conciliação Pix/webhook estar validada.** A produção não muda status de pagamento nem autoriza entrega.

## Qualidade, estabilidade e custos

- MP4 H.264, 30 fps, CRF 19, até 1080p com fotos adequadas, 720p nos demais casos.
- Cada fotografia dura 4 s e as transições se sobrepõem 0,5 s; três fotos → 11 s.
- No modo padrão, zoom muito sutil (cerca de 1–4% considerando enquadramento) e deslocamento lateral/vertical no máximo ~1% da tela.
- Fotos verticais em vídeo horizontal preservam o enquadramento com laterais desfocadas. Uma foto não pode preencher um vídeo de proporção contrária sem cortar ou deformar partes do imóvel.
- Sem trilha musical (licenciamento à parte) e sem criação inventada de cômodos.
- Um render Full HD pode consumir CPU e tempo consideráveis na Railway; um pedido por vez.
- O painel continua exigindo revisão humana e pagamento confirmado para entrega ao cliente.

## Variáveis opcionais da Railway

- `STAYVISION_VIDEO_QUALITY=auto`: padrão; 1080p somente se todas as fotos forem grandes o suficiente e até 8 fotos. `balanced`: 720p com menor CPU. `hd`: forçar 1080p, **não acrescenta detalhes às fotos pequenas**.
- `STAYVISION_VIDEO_MOTION=gentle`: padrão, movimento pequeno. `minimal`: aproximadamente 38% do movimento. `static`: nenhum pan/zoom, apenas crossfades (modo mais conservador).

Não é necessário criar nenhuma dessas variáveis: ambos os padrões funcionam sem configuração adicional. **Essas variáveis não alteram o Mercado Pago.**

## Testar no seu computador antes do deploy

Em Windows com Python, FFmpeg no PATH e as dependências do `requirements.txt`:

```powershell
pip install -r requirements.txt
python -m unittest discover -p "test_*.py" -q
python executar_demo_video_v3.py "C:\FotosImovel" --aspect horizontal --quality balanced --motion gentle
python executar_demo_video_v3.py "C:\FotosImovel" --aspect vertical --quality balanced --motion minimal
```

A pasta `<FotosImovel>_StayVision_V3` será criada ao lado da original. O script não altera fotos nem envia material à internet.

## Limites comerciais

As fotos de teste (duas verticais, uma horizontal) demonstram estabilidade técnica e transições. Isso não garante que a estética final já seja comercialmente excelente. Para anúncio premium, revisar enquadramentos, disponibilidade de fotos horizontais, quantidade de cenas, roteiro e trilha licenciada.

O modo `spatial` continua uma **ilustração 2.5D** com transformações da foto, não um passeio 3D real. Integração de vídeo por IA generativa (Kling/Runway etc.) não foi implementada e só deve ser ativada com orçamento, controle de arquitetura e consentimento de conteúdo.

## Compatibilidade e segurança

Foram preservados os endpoints `/api/admin/ai/*`, formatos de pedidos, sessão protegida, downloads privados e lógica financeira existentes. `run_pipeline` continua gerando fotos + vídeo/espacial conforme o modo, e grava metadados do motor no `manifest.json`. A versão V3 não altera o status de pagamento. Sempre verifique visualmente os resultados e mantenha `/data` persistente.
