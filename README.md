# StayVision V1 — Etapa 8: verificação segura do vendedor

Atualização incremental do checkout restrito da StayVision V1. Mantém o site, o painel, os pedidos e o volume persistente da Railway. **Não cria cobranças, links ou Pix ao ser instalada.** O objetivo é comprovar, usando a API oficial, se o `MP_PRODUCTION_COLLECTOR_ID` pertence à conta identificada por `MP_PRODUCTION_ACCESS_TOKEN`.

## O que muda

- Painel → Configurações → **Etapa 8 — Conferir proprietário do token** → **Confirmar identidade da conta vendedora**.
- O servidor faz uma única consulta autenticada por GET ao endpoint de identificação do Mercado Pago/Mercado Livre: `https://api.mercadolibre.com/users/me`.
- A comparação usa o `id` retornado e `MP_PRODUCTION_COLLECTOR_ID` guardado nas variáveis privadas da Railway.
- A resposta ao navegador contém somente se os IDs correspondem, últimos quatro dígitos de cada ID para diagnóstico, e um aviso. **Nunca retorna token, nome, e-mail ou dados pessoais da conta.**
- Antes de uma tentativa futura de criar checkout restrito, o servidor repetirá a verificação. Se houver divergência, erro de rede, token ausente ou resposta inesperada, **nenhuma nova tentativa de cobrança será criada**.
- Nenhuma alteração da configuração do checkout público, da confirmação automática de pedidos, dos preços ou das credenciais.

## Instalação segura — sem ativar checkout

1. **Não apague o volume `/data`.** Guarde um backup de pedidos e fotos de teste antes de atualizar o código.
2. Descompacte o ZIP e envie o conteúdo para a **raiz** do repositório GitHub da StayVision. Substitua os arquivos da Etapa 7 e inclua o novo arquivo `seller_identity.py`. O `Dockerfile` desta versão já o copia para a imagem.
3. **Não envie** `.env`, Access Token, senha, banco de dados ou fotos de clientes para o GitHub.
4. Aguarde o deploy da Railway ficar **Active**.
5. Mantenha estas variáveis — **não ative o checkout**:

```text
STAYVISION_ENABLE_DEMO_ORDERS=0
STAYVISION_MP_CHECKOUT_MODE=locked
STAYVISION_MP_AUTO_CONFIRM=0
```

`STAYVISION_MP_CHECKOUT_MODE` e `STAYVISION_MP_AUTO_CONFIRM` podem ser omitidas, pois o padrão já é seguro.

6. Abra `https://truthful-embrace-production-c05b.up.railway.app/painel` → **Configurações → Etapa 8** → **Confirmar identidade da conta vendedora**.
7. O botão efetua **somente GET**, sem criar preferências ou pagamentos. Veja o resultado:
   - **IDENTIDADE CONFIRMADA** — o `User ID` retornado pelo serviço corresponde ao ID configurado. Ainda não indica que Pix aparecerá no checkout.
   - **IDENTIDADE DIVERGENTE** — confirme o `User ID` da conta vendedora de PRODUÇÃO no Mercado Pago Developers e corrija a variável `MP_PRODUCTION_COLLECTOR_ID` na Railway. Não desbloqueie checkout.
   - **Consulta não realizada** — API indisponível, falta de permissão no token, dados inválidos ou outra falha; mantenha checkout bloqueado e informe somente a mensagem de erro, **sem enviar credenciais**.

**Nenhuma cobrança real foi executada nem será executada automaticamente por esta instalação.** O checkout restrito de um único pedido Photo R$ 49 só poderá ser habilitado em etapa separada, com decisão explícita do responsável. Abrir um link não é pagar. Se, posteriormente, alguém pagar um link de produção, haverá movimentação financeira real sujeita a tarifas, estornos e regras do Mercado Pago.

## Testes locais (sem internet nem uso de credenciais reais)

```bash
python -m unittest -q test_online test_payments_readiness test_webhook_diagnostic test_reconciliation test_checkout_stage6 test_checkout_stage7 test_seller_stage8
```

**66 testes aprovados** em 19/10/2026. Incluem bloqueio padrão, rejeição de vendedor divergente, autenticação administrativa, erro de API, inexistência de tentativa registrada após divergência, e verificação de que a consulta da identidade usa apenas GET. Chamadas de escrita à API foram simuladas nos testes.

Documentação oficial: https://www.mercadopago.com.br/developers/pt/docs/checkout-api-orders/resources/credentials?scope=prod

> Nota: esta é uma integração de pré-lançamento. Antes de vendas públicas, ainda serão necessários teste controlado do Checkout Pro e do Pix, confirmação automática, revisão de segurança e fluxos de reembolso. Esta atualização não executa essas etapas por conta própria.


## Atualização 8.1 — diagnóstico na própria tela

O botão existente **Confirmar identidade da conta vendedora** agora exibe também os últimos quatro dígitos do ID configurado na Railway e do ID reconhecido pelo Access Token. Não é necessário abrir `/api/admin/seller-identity` em outra aba, pois isso pode não compartilhar os cookies de sessão. A alteração é apenas em `static/painel.js` e não altera o servidor nem as regras de bloqueio de pagamento. Após o deploy, atualize a aba do painel com Ctrl+Shift+R.
