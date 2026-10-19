# StayVision Studio V1 — Etapa 6: Checkout Pro restrito (prévia SEM cobranças)

Esta versão evolui a Etapa 5 e mantém o **visual original da StayVision V1**. O novo código prepara a criação de uma preferência real de Checkout Pro para **um único pedido Photo de R$ 49**, mas **a criação está bloqueada por padrão**. Nenhuma compra, Pix ou movimentação financeira real é feita ao instalar este pacote.

## Recursos implementados

- Prévia administrativa de checkout vinculada a um pedido Photo existente — **não chama a API de cobranças**.
- Módulo `checkout_production.py`: payload de preferência com item de R$ 49, `external_reference` do pedido, retorno ao site por HTTPS e webhook. Não inclui dados privados de acompanhamento nos links de retorno.
- Registro `mp_checkout_registry` no SQLite, com reserva idempotente por pedido. Se uma criação real tiver resultado incerto, **o servidor não tenta criar novamente automaticamente**.
- Endpoint administrativo de criação de preferência protegido por senha, limite de requisições e **quatro travas de autorização**, desativadas por padrão. O site público **não recebe links de checkout real** nesta etapa.
- Código de conciliação de pagamento aprovado com validação da referência, preferência emitida pelo servidor, valor BRL exato, vendedor, `live_mode` e repetição de evento. A baixa automática também fica **desativada por padrão**.
- Tela de retorno que avisa que o redirecionamento do navegador **não comprova pagamento**.
- O webhook assinado e a consulta à API do Mercado Pago seguem ativos para **diagnósticos**, como na Etapa 5.
- Produção por IA, pagamentos reais públicos e liberação automática de arquivos **não estão disponíveis**.

## Instalação segura na Railway

1. **Não apague o volume `/data`.** Antes de atualizar, faça backup dos dados importantes da Railway. No plano de teste limitado, não considere o volume como backup definitivo.
2. Extraia o ZIP e envie **o conteúdo da pasta extraída, não o ZIP**, ao repositório GitHub conectado ao projeto Railway, preservando a estrutura. Confira especialmente `Dockerfile`, `server_online.py`, `checkout_production.py`, `payment_reconciliation.py`, `payments_readiness.py` e `static/`.
3. **Não envie** tokens, `.env`, banco de dados, senhas ou fotos privadas ao GitHub.
4. Aguarde o deploy Railway ficar **Active**. Confira `https://truthful-embrace-production-c05b.up.railway.app/api/health` — o servidor deve responder com `ok:true`, `mode:pedidos_demo`, `payments:false`.
5. Mantenha `STAYVISION_ENABLE_DEMO_ORDERS=0` e suas variáveis já existentes (`STAYVISION_DATA_DIR=/data`, `STAYVISION_PUBLIC_URL`, usuário e senha do admin, `MP_PRODUCTION_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET`).
6. **Não crie nem altere variáveis de habilitação de checkout real.** O estado seguro padrão é `STAYVISION_MP_CHECKOUT_MODE=locked` e `STAYVISION_MP_AUTO_CONFIRM=0` (não é necessário criá-las na Railway).
7. Entre em `/painel` → **Configurações** → **Etapa 6 — Preparação de checkout real restrito**.
8. Confira a mensagem **“Checkout real BLOQUEADO”**. Digite **o código de um pedido Photo fictício já cadastrado** e clique em **“Validar pedido sem criar cobrança”**.
9. Esperado: `Prévia sem cobrança ... Checkout restrito: BLOQUEADO. Nenhuma cobrança foi criada.`

Se o navegador mostrar informações antigas, recarregue com `Ctrl + Shift + R`. Nenhum pedido antigo é apagado pela migração do banco: ela somente cria a nova tabela `mp_checkout_registry`, se não existir. Faça backup mesmo assim.

## O que NÃO fazer nesta etapa

- Não ativar vendas públicas, não divulgar links de cobrança, não inserir a Public Key ou Access Token no frontend e não enviar tokens no chat.
- Não criar uma cobrança real nem testar Pix com dinheiro real ainda. O Pix consta na API de produção da conta, mas **isso não garante que será apresentado no checkout**.
- Não habilitar o mecanismo de baixa automática sem antes validar um pagamento real controlado com autorização explícita, inclusive fluxo de cancelamento/estorno.
- Não oferecer tours 3D com entrega automática antes de integrar e validar a ferramenta de produção.

## Informações para a futura prova de pagamento (não configurar agora)

A criação real de preferência só funciona se forem habilitadas em conjunto, de forma intencional, variáveis privadas adicionais de acesso restrito, uma whitelist do código do pedido e a identificação confirmada do vendedor de produção. O servidor nunca habilita pagamentos por um botão público. Essa ativação deve ser feita **somente depois de uma autorização explícita para o teste com dinheiro real**, quando também verificaremos o fluxo de volta, recebimento de webhook, consulta oficial, cancelamento e estorno.

## Testes locais

```bash
python -m unittest -v test_online test_payments_readiness test_webhook_diagnostic test_reconciliation test_checkout_stage6
```

42 testes automatizados passaram no ambiente de desenvolvimento, todos **sem acesso real à API de cobranças**. Os testes de POST real usam mocks, não criam pagamentos. Os testes e o deploy não substituem uma revisão de segurança profissional antes da operação comercial.

Documentação oficial do Mercado Pago:
- https://www.mercadopago.com.br/developers/pt/reference/online-payments/checkout-pro-preferences/overview
- https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/create-payment-preference
- https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/payment-notifications
