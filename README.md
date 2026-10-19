# StayVision V1 — Etapa 4: teste de recebimento de webhooks (Railway)

**NOVO: monitoramento de notificações do Mercado Pago. NENHUMA COBRANÇA REAL é criada.
Nenhum pedido é marcado como pago por esta versão.**

Esta é uma atualização incremental da Etapa 3: mantém o visual V1, o volume `/data`, pedidos,
links de acompanhamento, login administrativo e diagnóstico Pix de produção.

## Atualizar o GitHub (preservando pedidos)

1. Verifique que o serviço está `Active`, que o volume `/data` está montado e que fez backup dos dados.
2. Faça upload para seu repositório do conteúdo extraído deste ZIP na raiz,
   preservando `Dockerfile`, `server_online.py`, `payments_readiness.py`, `static/`.
3. **NUNCA** envie `.env`, tokens, banco de dados ou fotos de clientes ao GitHub.
4. Faça commit, espere Railway `Active` e confira `/api/health`: `payments` deve continuar `false`.
5. Mantenha `STAYVISION_ENABLE_DEMO_ORDERS=0`.
6. Os pedidos e arquivos já salvos no volume `/data` não são substituídos por esse pacote.

## Configurar notificações no Mercado Pago — sem criar cobrança

1. Mercado Pago Developers → aplicação StayVision Studio → **Webhooks** → configurar.
2. Na aba **Modo produtivo**, configurar URL HTTPS:

   `https://truthful-embrace-production-c05b.up.railway.app/api/mp/webhook`

3. Marcar somente o evento **Pagamentos** e salvar.
4. O Mercado Pago mostrará uma **chave secreta do webhook**. Na Railway → serviço → Variables,
   cadastrar `MP_WEBHOOK_SECRET` com essa chave. Não revelar nem enviar ao GitHub.
5. Aplicar e aguardar Active. O status admin mostra apenas se a chave existe (não seu valor).
6. No Mercado Pago → Webhooks → **Simular**. Selecionar o evento **payment** e inserir
   um Data ID numérico fictício (apenas para teste de entrega). Enviar simulação.
7. No painel StayVision → **Configurações → Notificações Mercado Pago** → clicar em
   "Atualizar diagnóstico de notificações". Deve contar uma notificação autenticada.
   Se o simulador gerar cabeçalhos ou parâmetros diferentes, consulte o status e os logs;
   não altere nem compartilhe tokens ou segredos para tentar contornar a validação.

A notificação só é aceita quando `x-signature` e `x-request-id` validam
`data.id` pela chave secreta. É gravado um registro mínimo e idempotente em `/data`.
O código **não busca pagamentos, não valida valor, não marca pedido como pago e não cria Pix**.

### Controles de segurança

- Por padrão, nenhuma cobrança é autorizada, mesmo com credencial de produção configurada.
- Endpoints de checkout real e verificação de pagamento continuam bloqueados (`403`).
- Sem chave de webhook cadastrada o endpoint de notificação não funciona (`503`).
- Cabeçalhos HMAC inválidos geram `401`. Reenvios de mesmo `x-request-id` não duplicam registros.
- Nenhuma informação pessoal do pagamento é salva; apenas momento, tipo de evento, ID da notificação
  (internamente) e identificador do recurso.
- A validação de recebimento não prova que o pagamento foi aprovado. Isso exigirá consultar a
  API de pagamentos e confrontar valor, moeda, referência e destinatário, em fase posterior.
- Antes de ativar vendas: testar backup/restauração, limites contra abuso e requisitos de privacidade.

### Testes

`python -m unittest -v test_online test_payments_readiness test_webhook_diagnostic`

Referência oficial: https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/payment-notifications
