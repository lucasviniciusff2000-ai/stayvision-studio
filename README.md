**NOVO: Veja `README_ETAPA12_PHOTO_V2.md` para a atualização fotográfica V2.**

# NOVA VERSÃO: STAYVISION STUDIO ETAPA 11 — FOTOS E VÍDEOS

**Comece por `README_ETAPA11_IA.md`.** Esta atualização adiciona o Creative Engine (tratamento de fotos, vídeos 16:9 / 9:16, efeito espacial ilustrativo 2.5D e planos para futuro tour 3D). O documento abaixo é o histórico financeiro da Etapa 10, mantido para referência.

---

# StayVision Studio V1 — Etapa 10: conciliação segura de pagamentos já recebidos

Esta atualização corrige a função antiga no **painel de pedidos**, que mostrava "Pagamentos indisponíveis nesta versão online de demonstração". Depois de receber um Pix real, o administrador pode consultar o ID numérico existente na API oficial do Mercado Pago e, após verificação rigorosa, vincular o pagamento ao pedido **sem gerar nova cobrança**.

**Uso:** após instalar e dar Ctrl+F5, abra o pedido → **Conciliar pagamento real já recebido** → informe o ID numérico da operação no Mercado Pago → **Conferir e conciliar pagamento**. O servidor só marca `pago` após confirmar na API: transação de produção aprovada, BRL, valor exato, pedido, vendedor e preferência da própria StayVision. Funciona mesmo com novos checkouts bloqueados, mas exige `STAYVISION_MP_AUTO_CONFIRM=1`. Uma consulta inválida não altera nada. O mesmo pagamento não pode ser vinculado a pedidos diferentes.

A integração de **notificações webhook** ainda precisa ser diagnosticada porque esse primeiro Pix não foi atualizado automaticamente. Essa nova conciliação é um mecanismo seguro de recuperação para o pedido já pago, **não prova que os próximos pagamentos serão confirmados automaticamente**. Antes de lançar, confira eventos de webhook e corrija a causa de qualquer falha.

**Não pagar novamente. Não abrir vendas públicas. Não incluir credenciais, dados pessoais ou banco no GitHub. Preservar o volume Railway `/data`.** O modo `restricted` ou `locked` pode ser mantido, assim como a ausência de `STAYVISION_MP_PUBLIC_LAUNCH`.

---

# StayVision Studio V1 — Etapa 9: checkout completo, pronto para testes de lançamento

Esta é uma atualização **pré-lançamento** da V1 (visual verde-escuro/creme preservado). Foi construída em cima da Etapa 8.2, que já confirmou a identidade do vendedor. Ela **não ativa pagamentos reais quando instalada**: a configuração padrão permanece bloqueada, independentemente de o domínio ser público. Nenhum Access Token, senha, Webhook Secret, banco de dados ou fotos de clientes está incluído neste pacote.

## O que foi implementado

- Checkout Pro de **pagamento avulso** para três serviços: Photo, Video e Partner (preços padrão R$ 49, R$ 197 e R$ 697). **O plano Partner não é uma assinatura recorrente**: cada pedido gera uma cobrança única; renovações precisariam de desenvolvimento separado.
- Formulário público de pedido com upload validado, código e link privado de acompanhamento, **liberado somente após o lançamento**.
- Criação de preferência Mercado Pago pelo backend; credenciais nunca vão ao browser. Conferência do vendedor antes da criação, valor salvo no pedido, referência externa, URLs de retorno e webhook.
- Registro de idempotência em SQLite: cada pedido utiliza apenas uma preferência; diante de resultado ambíguo da API, não repete a tentativa de cobrança automaticamente.
- Confirmação de pagamento **apenas após webhook assinado + GET do pagamento na API oficial**, verificando ambiente de produção, status, moeda, valor, proprietário, número do pedido e preferência criada pelo próprio site. Um retorno de navegador não comprova pagamento.
- Atualização de `pago` com vínculo único ao ID de pagamento; não altera o estado para `concluido` nem envia material automaticamente.
- Estorno/chargeback (status `refunded` e `charged_back`) verificado via API e por associação a um pedido previamente cadastrado: estado `estornado` impede download da entrega. Estornos parciais, cancelamentos e disputas complexas devem ser revisados manualmente no Mercado Pago.
- Diagnóstico no painel preservado (Etapas 7 e 8), confirmação de identidade e eventos de webhook, sem mostrar chaves.

## 1. Instalar, sem ativar vendas

1. Faça um **backup do volume Railway `/data`** (banco de pedidos e uploads) antes de publicar o novo código. Não apague/recrie o volume.
2. Extraia o ZIP, abra o repositório GitHub `lucasviniciusff2000-ai/stayvision-studio` e **substitua os arquivos na raiz**. Coloque `static/` na pasta correta, sem criar subpasta adicional. Faça um commit; aguarde o deploy ficar `Active`.
3. Mantenha as variáveis existentes no servidor. Configurações seguras de pré-lançamento:

```ini
STAYVISION_DATA_DIR=/data
STAYVISION_MP_CHECKOUT_MODE=locked
STAYVISION_ENABLE_DEMO_ORDERS=0
STAYVISION_MP_AUTO_CONFIRM=0
# STAYVISION_MP_PUBLIC_LAUNCH NÃO DEVE SER CONFIGURADA AINDA
```

A URL pública HTTPS, a chave de webhook, Access Token, Collector ID, login e senha do admin continuam configurados apenas na Railway. O código não necessita que eles sejam alterados agora. Nunca envie tokens a um chat, PDF, repositório ou cliente.

4. Verifique no painel que **checkout bloqueado** e **identidade confirmada**, e que uma compra pública não pode ser iniciada.

## 2. Teste privado obrigatório com dinheiro real (quando você decidir)

É impossível assegurar que o Pix aparece e que webhook/checkout foram aceitos pela sua conta específica **sem fazer pelo menos um teste real controlado**. O programa não realiza esse teste automaticamente.

A Etapa 7 continua funcionando com autorização **apenas** do pedido Photo R$ 49:

```ini
STAYVISION_MP_CHECKOUT_MODE=restricted
STAYVISION_MP_ALLOWED_ORDER_ID=SV-...              # troque pelo pedido autorizado
STAYVISION_MP_REAL_TEST_AUTHORIZATION=EXPLICIT_SINGLE_ORDER_TEST
STAYVISION_MP_AUTO_CONFIRM=1
```

Isso **não abre vendas públicas**. No painel → Etapa 7, use somente o pedido de teste autorizado e a frase exata solicitada pelo próprio painel. **Criar uma preferência não cobra ninguém automaticamente**; pagar o link transfere dinheiro real, sujeito a regras e tarifas do Mercado Pago. Confirme com antecedência quem arcará com taxas, política de estorno e valores.

Valide manualmente: preço R$ 49, identidade do vendedor, meios de pagamento oferecidos (Pix é decisão do Mercado Pago), conclusão de um pagamento real explicitamente autorizado, chegada do webhook assinado, confirmação `pago` no painel, vínculo ao pedido, e, se apropriado, o processo de estorno. Não use dados de clientes reais para esse teste. Uma operação de teste com conta própria pode sofrer restrições pelo provedor; consulte as regras do Mercado Pago.

**Após o teste, não desligue imediatamente `STAYVISION_MP_AUTO_CONFIRM` caso ainda haja links pendentes**, porque pagamentos de preferências já emitidas podem chegar mais tarde.

## 3. Preparar tudo para o dia do lançamento, mas manter fechado

Depois de concluir o teste privado, você pode deixar estas duas configurações prontas:

```ini
STAYVISION_MP_CHECKOUT_MODE=public
STAYVISION_MP_AUTO_CONFIRM=1
# STAYVISION_MP_PUBLIC_LAUNCH AUSENTE/VAZIA
```

**Assim o checkout público CONTINUA FECHADO.** A flag adicional é uma segunda autorização independente, além da configuração `public`.

## 4. No dia que você QUISER abrir as vendas

Você terá que **decidir conscientemente** habilitar a única chave final, na Railway → Variables:

```ini
STAYVISION_MP_PUBLIC_LAUNCH=I_AUTHORIZE_PUBLIC_SALES
```

Apenas com `STAYVISION_MP_CHECKOUT_MODE=public`, `STAYVISION_MP_AUTO_CONFIRM=1`, `STAYVISION_MP_PUBLIC_LAUNCH=I_AUTHORIZE_PUBLIC_SALES`, credenciais de produção, Collector ID numérico, Webhook Secret e URL HTTPS válida **em conjunto** o servidor libera novas compras. A verificação real de identidade do vendedor continua sendo exigida antes da criação de cada preferência. A aprovação do Mercado Pago para efetuar cobranças reais continua necessária.

**Pausar novas vendas:** retire `STAYVISION_MP_PUBLIC_LAUNCH` e, preferencialmente, use `STAYVISION_MP_CHECKOUT_MODE=locked`. **Links já criados podem continuar pagáveis no Mercado Pago mesmo depois de bloquear novas vendas**; acompanhe e reconcilie pedidos existentes. Mantenha confirmação automática dos pagamentos anteriores enquanto houver pendências.

## 5. Testes locais (tudo simulado — nenhuma chamada real ao Mercado Pago)

```bash
python -m unittest -q test_online test_payments_readiness test_webhook_diagnostic test_reconciliation test_checkout_stage6 test_checkout_stage7 test_seller_stage8 test_seller_stage8_2 test_checkout_stage9
```

Também execute `node --check static/app.js`, `node --check static/acompanhar.js` e `node --check static/painel.js` se tiver Node instalado.

## 6. Limitações explícitas antes de divulgar

- **Nenhuma operação real foi realizada no preparo deste ZIP.** É necessário validar a integração na sua conta e no domínio da Railway, em ambiente real, antes de afirmar que o checkout está homologado.
- A automação de aprimoramento de fotos e geração de vídeos ainda **não existe** nesta versão; a entrega ocorre manualmente no painel. Não anuncie edição automática até que a IA esteja integrada e testada.
- Não há envio automático de e-mails transacionais. O cliente deve guardar o link privado do acompanhamento. Para escala, é recomendável integrar um provedor de e-mail.
- O Partner de R$ 697 é **pagamento único** por pacote de serviços; assinatura recorrente e renegociação de escopo precisam de implementação própria.
- Cobranças múltiplas, disputas, chargebacks parciais, conciliação financeira contábil, impostos, cumprimento de LGPD e política de cancelamento/reembolso exigem revisão operacional antes das vendas públicas.
- A verificação automática de pagamentos depende da entrega de webhooks pelo provedor e da disponibilidade de sua API. Monitore a sessão Notificações no painel. Os testes existentes são locais e simulados, não substituem o teste de ponta a ponta.

**Arquivos a preservar no Railway:** volume `/data`, credenciais privadas e configurações de domínio. **Nunca coloque no GitHub:** `.env.local`, senhas, token, Client Secret, bancos de pedidos, uploads e imagens de clientes.

Registro anterior: `README_ETAPA8_HISTORICO.md`.
