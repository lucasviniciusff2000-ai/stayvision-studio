# StayVision Photo Engine V2 — versão para avaliação

**O que muda:** a versão anterior aplicava predominantemente exposição e contraste. A V2 tem processamento independente para balanço de branco baseado em regiões neutras, denoise seletivo, abertura de sombras em luminância, CLAHE de intensidade controlada, saturação suave e nitidez limitada a bordas; preserva a geometria dos imóveis, os uploads originais e os dados do pedido.

**Importante:** não é um modelo generativo. O tratamento local V2 é um pipeline de visão computacional — e não recupera detalhes perdidos em fotos minúsculas. O módulo opcional FSRCNN permite usar um modelo neural *se o administrador fornecer o arquivo de pesos pré-treinados*; ele não acompanha o ZIP e está DESATIVADO por padrão. Não prometa imagens recriadas ou resolução alta artificial. Para anúncios profissionais, peça imagens originais de câmera/celular em resolução alta (idealmente 1920 px ou mais no lado menor, quando possível). Fotos usadas na demonstração original são apenas ~372×506 px, abaixo do recomendado.

## Usar a versão V2 no painel

1. Guarde o backup recente de `/data` e mantenha as vendas públicas bloqueadas.
2. Extraia o ZIP da etapa 12 e publique os **arquivos extraídos na raiz do seu repositório**. Não carregue um diretório pai inteiro, e **não envie arquivos secretos ou o banco de produção**.
3. Confirme que `ai_engine.py`, **`photo_engine_v2.py`**, `requirements.txt`, `Dockerfile` e `static/` foram atualizados no GitHub.
4. Aguarde o deploy Railway **Active**. O novo `opencv-contrib-python-headless` aumenta o tamanho de instalação e o consumo de RAM/CPU; o seu plano deve ter recursos suficientes.
5. Entre em `/painel` → **Pedidos** → **Abrir** → **Produção inteligente** → selecione **Fotos tratadas** e **Claro** ou **Natural**, depois **Iniciar processamento**.
6. Baixe `Fotos_StayVision.zip` e avalie TODAS as fotos lado a lado com os originais antes de entregar. O painel alerta quando o arquivo de origem é muito pequeno.

A V2 não mexe em `MP_PRODUCTION_ACCESS_TOKEN`, `MP_PRODUCTION_COLLECTOR_ID`, `MP_WEBHOOK_SECRET`, pagamentos, `STAYVISION_MP_CHECKOUT_MODE` ou envios ao cliente. Recomenda-se manter `STAYVISION_MP_CHECKOUT_MODE=locked` enquanto a conciliação Pix não estiver validada.

## Para fotos pequenas: super-resolução neural opcional (não incluída)

A V2 está preparada para ler um **modelo FSRCNN x2** compatível com a API OpenCV DNN Super Resolution. A melhoria depende da qualidade do modelo e pode criar artefatos, portanto deve ser revisada. O arquivo de pesos não acompanha o projeto e não existe download automático. Modelos compatíveis são apresentados no tutorial oficial do OpenCV: https://docs.opencv.org/4.x/d5/d29/tutorial_dnn_superres_upscale_image_single.html

Se você tiver obtido um modelo compatível e autorizado para uso, salve no volume seguro por exemplo em `/data/models/FSRCNN_x2.pb` e defina em Railway:

```ini
STAYVISION_PHOTO_SUPERRES_MODEL=/data/models/FSRCNN_x2.pb
```

Ele só será usado em imagens com até 1,8 megapixels antes do upscale. Sem esse arquivo, a V2 mantém a resolução real e **não afirma ter usado uma rede neural**. Não use esse modo sem testar qualidade e licença do modelo. Para fotografia imobiliária de alto padrão, métodos neurais de maior qualidade podem exigir um serviço GPU externo com autorização explícita do cliente e custo por imagem.

## Correção de rotação opcional

Por segurança, a rotação automática de linhas de construção fica desabilitada porque a maioria dos imóveis já é fotografada nivelada e detecções equivocadas podem distorcer cantos. Para experimentar em cópias:

```ini
STAYVISION_PHOTO_AUTO_LEVEL=1
```

A correção só ocorre se várias linhas concordarem e o ângulo estimado for de 0,6° a 2°. Ela não faz correção de perspectiva completa: corrigir paralelas de fotografias interiores exige calibração e validação humana.

## Prova e testes locais

```powershell
pip install -r requirements.txt
python -m unittest -q test_photo_v2 test_ai_stage11 test_online test_payments_readiness test_webhook_diagnostic test_reconciliation test_checkout_stage6 test_checkout_stage7 test_seller_stage8 test_seller_stage8_2 test_checkout_stage9 test_checkout_stage10
python executar_demo_ia.py --modo photo --estilo claro
```

O pacote de demonstração à parte contém originais e derivados para comparar, **sem material privado de clientes**.

## Limitações atuais

- A melhora fotográfica é limitada pela qualidade de origem. Imagens extremamente comprimidas são detectadas como pequenas; nenhuma técnica clássica restaura texturas perdidas.
- O vídeo continua usando o motor V1 da Etapa 11, já que nesta entrega a prioridade é Photo V2; 3D real e vídeo neural ainda não são recursos entregues.
- O primeiro Pix real recebido ainda precisa ter reconciliação + webhook confirmados em produção. Não libere compras públicas antes de validar.
- Existe apenas um trabalho de mídia ativo por vez no servidor Railway. Não é uma fila distribuída.
