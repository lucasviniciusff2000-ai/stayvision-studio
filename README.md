# StayVision Studio V1 — Etapa 7: checkout real restrito, sem vendas públicas

Esta versão mantém o **visual da StayVision V1**, o painel, os pedidos e os arquivos de imagem já existentes. Prepara a geração de **um link de Checkout Pro de produção** somente para um pedido Photo de **R$ 49**, depois de autorização específica do administrador. **A instalação, por si só, não cria preferências, QR Codes, Pix ou cobranças.**

## O que foi acrescentado

- Área **Etapa 7 — Teste real RESTRITO** dentro de **Painel → Configurações**.
- O botão de gerar link permanece **desabilitado** enquanto a autorização de pedido único não for configurada deliberadamente no servidor.
- Para gerar link de um pedido autorizado, o administrador precisará fazer login, informar código do pedido, marcar a confirmação, digitar a frase específica do pedido e confirmar uma segunda vez no navegador.
- Requisições financeiras exigem `Origin` HTTPS da StayVision, cabeçalho adicional e autorização explícita; tentativas sem isso são rejeitadas.
- **Um único registro de preferência por pedido**. Diante de erro de rede ambíguo, não repete automaticamente a criação.
- Consulta administrativa **somente leitura** de um identificador real de pagamento vinculado ao pedido. Ela confere a resposta da API, mas **não altera status nem libera arquivos**.
- Código da confirmação automática de pagamentos segue condicionado a autorização separada; o modo padrão é **desligado**.
- O checkout **público** permanece desativado e não expõe links reais aos visitantes.

## Instalar SEM ativar pagamentos reais

1. Faça um backup confiável dos dados atuais, especialmente dos pedidos e das fotos no volume `/data`. O plano Railway Trial não equivale a backup.
2. Extraia o ZIP e envie os **arquivos dentro dele**, mantendo `Dockerfile`, `server_online.py`, `checkout_production.py`, `payment_reconciliation.py`, `payments_readiness.py` e a pasta `static/`, ao repositório GitHub conectado à Railway.
3. Não envie os dados do volume, credenciais, `.env`, senhas ou fotografias privadas ao GitHub.
4. Aguarde o deploy ficar **Active** e abra `/api/health`: resposta esperada `ok: true`, `mode: "pedidos_demo"`, `payments: false`.
5. Entre no painel em `https://truthful-embrace-production-c05b.up.railway.app/painel` → **Configurações → Etapa 7**.
6. A situação segura normal é **BLOQUEADO** e **Gerar link restrito** desabilitado.
7. Verifique se os pedidos antigos e o painel continuam acessíveis e se as imagens de teste continuam disponíveis.

**Por enquanto, mantenha estas variáveis:**

```text
STAYVISION_ENABLE_DEMO_ORDERS=0
STAYVISION_MP_CHECKOUT_MODE=locked
STAYVISION_MP_AUTO_CONFIRM=0
```

As duas últimas podem ser **omitidas**: esses são os valores padrão. **Não crie nem altere variáveis de desbloqueio de checkout nesta instalação.** Os tokens de produção existentes ficam privados na Railway; a versão não os exibe no navegador.

## Antes de um teste real de Pix (NÃO fazer nesta instalação)

Será necessária **autorização explícita e específica** para gerar uma preferência em produção de R$ 49 para um pedido previamente criado com dados e imagens fictícias. Após a autorização, conferiremos primeiro o código desse pedido, o ID do vendedor no Mercado Pago, a disponibilidade de estorno e os limites operacionais, antes de habilitar temporariamente as travas na Railway. O ato de abrir e pagar o link poderá movimentar dinheiro de verdade. A aparência do Pix no Checkout Pro **não está garantida**, mesmo aparecendo na lista de meios da API.

A URL de retorno do navegador não comprova pagamento. O servidor deve consultar o pagamento na API oficial, verificando `status`, `live_mode`, moeda, valor, pedido, vendedor e preferência. A confirmação automática de pedido permanecerá desligada até validarmos esse fluxo.

## Testes automatizados (offline)

```bash
python -m unittest -q test_online test_payments_readiness test_webhook_diagnostic test_reconciliation test_checkout_stage6 test_checkout_stage7
```

**52 testes aprovados** localmente, incluindo tentativas sem `Origin` correto, confirmação ausente e leitura do pagamento sem alterar o pedido. As chamadas que poderiam criar preferências são simuladas nos testes; **nenhum pagamento real foi criado** durante o desenvolvimento.

Documentação oficial:

- https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/create-payment-preference
- https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/payment-notifications
- https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/configure-back-urls

> Aviso: trata-se de integração pré-lançamento. Faça revisão de segurança e testes operacionais, incluindo reembolsos e divergências, antes de abrir vendas públicas ou usar fotos de clientes reais.
