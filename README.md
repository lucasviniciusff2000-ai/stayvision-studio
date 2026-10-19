# StayVision Studio V1 — Etapa 3: consulta ao Pix de produção (Railway)

**Versão preparada para implantação. Não modifica sua conta Mercado Pago até você cadastrar
`MP_PRODUCTION_ACCESS_TOKEN` na Railway. Nenhuma cobrança real pode ser iniciada por este pacote.**

Este pacote atualiza a V1 já publicada e funcionando com pedidos demonstrativos, mantendo
seu design, SQLite e arquivos em `/data`, painel e acompanhamento.

## Antes de instalar

- Confirme no Railway que existe um Volume montado em `/data`, que
  `STAYVISION_DATA_DIR=/data`, e que a V1 anterior responde em `/api/health`.
- Faça **backup/exportação dos pedidos e fotos** do volume antes de alterações maiores.
  Não apague nem desmonte o volume. Seu conteúdo não está neste ZIP.
- Mantenha `STAYVISION_ENABLE_DEMO_ORDERS=0` enquanto a integração comercial está em andamento.
- Não cole chaves em GitHub, tickets, prints, ChatGPT ou no navegador.

## Atualizar GitHub

1. Extraia este ZIP em uma pasta.
2. No repositório `lucasviniciusff2000-ai/stayvision-studio`, abra **Add file → Upload files**.
3. Envie **os arquivos e a pasta `static`**, descompactados, na raiz do repositório.
   Substitua `Dockerfile`, `server_online.py`, `README.md`, `static/painel.js` e `static/painel.html`.
   **Novo arquivo obrigatório:** `payments_readiness.py`.
4. Clique em **Commit changes**, aguarde o novo deploy na Railway e confira `Active`.
5. Teste `https://truthful-embrace-production-c05b.up.railway.app/api/health`. Resultado esperado:
   `{"ok":true,"mode":"pedidos_demo","payments":false}`.
6. Verifique o login do `/painel` e um pedido antigo. A versão não altera dados de pedidos existentes.

## Cadastrar chave de produção — SEM habilitar pagamentos reais

1. Railway → StayVision → serviço web → **Variables → New Variable**.
2. **Nome:** `MP_PRODUCTION_ACCESS_TOKEN`.
3. **Valor:** copie o Access Token na aba **Credenciais de produção** do Mercado Pago.
   Não é a Public Key. Use o campo secreto de variável, não faça upload da chave em arquivo.
4. Aplique as alterações e espere o serviço ficar `Active`.
5. Abra `/painel` → **Configurações → Publicação e cobranças**.
6. Clique em **Verificar Pix (produção — somente consulta)**.
   O painel deve dizer se Pix consta na API. Isso **não garante** que o Pix aparecerá no Checkout Pro.
7. Nunca habilite vendas reais só porque a API informou `Pix listado`.

O endpoint autenticado `/api/admin/mp-readiness` também informa **somente booleanos**
indicando se há credencial e HTTPS; ele não retorna chaves. O endpoint
`/api/admin/pix-production-diagnostic` faz apenas um `GET /v1/payment_methods`.

## O que ainda está desligado (intencionalmente)

- Checkout Pix/cartão reais e criação de preferência (`POST /checkout/preferences`).
- Recebimento/processamento de webhooks e aprovação automática de pagamentos.
- Ativação pública de vendas (formulário de demonstração fica desligado por padrão).
- Serviço de geração de fotos/vídeos por IA.

O módulo `payments_readiness.py` já inclui funções **offline, não ligadas a endpoints públicos**
para conferir assinaturas HMAC de futuros webhooks e validar dados de pagamento
(valor, moeda, referência, modo produção e recebedor) após consulta à API.
Essas funções por si só **não** constituem um sistema de pagamento pronto.
Antes de abrir vendas, implementar idempotência, reconciliação, tratamento de estornos,
webhook em HTTPS, backups testados, proteção contra uploads abusivos, políticas LGPD
e revisão da infraestrutura.

Para webhooks do Mercado Pago, a chave secreta será obtida em
**Mercado Pago Developers → sua aplicação → Webhooks → Configurar notificações**.
Ela será usada em uma fase posterior, não é necessária agora.

## Verificar localmente

`python -m unittest -v test_online test_payments_readiness`

Bibliotecas externas: nenhuma. Python 3.12. 

Referências oficiais:
- https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/create-payment-preference
- https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/payment-notifications
- https://www.mercadopago.com.br/developers/pt/reference/online-payments/checkout-pro-preferences/overview
