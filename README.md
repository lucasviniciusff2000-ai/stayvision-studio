# StayVision Studio V1 — Etapa 5: conferir pagamentos sem criar cobranças

**Objetivo:** consultar o pagamento diretamente no Mercado Pago após receber um webhook autenticado, comparar o resultado com os pedidos existentes e exibir uma auditoria privada no painel. Esta é uma **etapa de observação**, não de cobrança ou baixa financeira.

## Proteções

- O Checkout Pro **real permanece desativado**: `/api/client/checkout` e `/api/admin/verify-payment` respondem 403.
- A variável `STAYVISION_ENABLE_DEMO_ORDERS` deve continuar em `0` até você decidir testar pedidos fictícios novamente.
- Nenhum pedido muda para `pago`, `recusado` ou `estornado`; nenhum arquivo é liberado a partir dos webhooks.
- A verificação consulta exclusivamente `GET https://api.mercadopago.com/v1/payments/{id}` com o Access Token de produção no **servidor**, após validar a assinatura HMAC.
- Os dados do comprador não são guardados no histórico da conferência; apenas o ID técnico do recurso e um resultado de auditoria privado.
- Falhas temporárias da API devolvem 503 para permitir novo envio; IDs fictícios/inexistentes ficam registrados como `pagamento_nao_encontrado`.
- A API pode devolver `status=approved`, mas isso **não é suficiente** para marcar o pedido como pago. O sistema ainda exige referência, preço exato, BRL, modo de produção, vendedor certo e preferência vinculada ao pedido. Esta versão não cria preferências reais.
- Todos os arquivos de dados e fotografias anteriores permanecem no volume Railway em `/data`. Não apague ou substitua o volume. Faça backup antes de implantar.

## Instalação na Railway

1. Faça backup do volume `/data` e confira que a versão anterior funciona.
2. Extraia o ZIP e atualize o repositório `stayvision-studio` com o **conteúdo** do ZIP (arquivos na raiz), preservando `Dockerfile`, `server_online.py`, `payments_readiness.py`, **`payment_reconciliation.py`**, `static/`, etc.
3. Não envie `.env`, tokens, dados, senhas ou fotos privadas ao GitHub.
4. O `Dockerfile` inclui o módulo `payment_reconciliation.py`.
5. Espere Railway ficar `Active` e verifique `/api/health`: `payments` deve continuar `false`.
6. Confirme que as variáveis existentes continuam configuradas diretamente na Railway: `MP_PRODUCTION_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`, `STAYVISION_DATA_DIR=/data`, `STAYVISION_ADMIN_USER`, `STAYVISION_ADMIN_PASSWORD`, `STAYVISION_PUBLIC_URL`.
7. Opcional para auditoria de destinatário: `MP_PRODUCTION_COLLECTOR_ID` deve ser o **ID de vendedor de produção** da sua conta. Se não souber, não chute: o relatório continuará cauteloso (`id_vendedor_nao_configurado`). **Não use User ID de teste.**
8. Mantenha `STAYVISION_ENABLE_DEMO_ORDERS=0`. Não crie variáveis para liberar cobranças reais; esta versão não tem essa função.

## Teste seguro

1. No Mercado Pago Developers, na aplicação StayVision Studio, deixe configurado o webhook de **Pagamentos** para `https://truthful-embrace-production-c05b.up.railway.app/api/mp/webhook` e a chave secreta correta na Railway.
2. Use **Simular notificações** com um ID de pagamento **fictício**, sem executar transação.
3. No painel StayVision → Configurações → **Notificações Mercado Pago — conferência somente leitura** → Atualizar diagnóstico. Um ID que não existe deve aparecer como `pagamento_nao_encontrado`.
4. O contador de notificações recebidas sobe, mas nenhum pedido muda de situação financeira. Se a API ficar temporariamente indisponível, poderá haver resposta 503: aguarde ou reenvie a simulação.
5. Nos testes, **não use IDs reais de pagamentos de clientes** nem habilite checkout real para validar esta etapa.

## Próxima etapa ainda pendente

Criar preferências reais no backend, vinculá-las a cada pedido, proteger o fluxo de retorno e a conciliação/baixa idempotente, realizar uma compra controlada autorizada e validar Pix/cartão. Somente depois disso liberar produção e entrega. Esta versão não está pronta para receber pagamento real de clientes.

## Testes locais

```bash
python -m unittest -v test_online test_payments_readiness test_webhook_diagnostic test_reconciliation
```

Documentação oficial: https://www.mercadopago.com.br/developers/pt/reference/online-payments/checkout-pro-preferences/get-payment/get
