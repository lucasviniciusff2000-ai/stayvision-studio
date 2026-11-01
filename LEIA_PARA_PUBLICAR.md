# STAYVISION V3.33 — UM SERVIÇO RAILWAY (PREPARAÇÃO COMERCIAL)

Este pacote junta o site V3.13, checkout dos **quatro planos**, reconciliação pelo **Mercado Pago API**, fila semiautomática de produção de imagens, painel administrativo e galeria de entrega. Usa o motor criativo V3.31 (estúdio). **Não instale sobre sua V3.31 local.**

## Implantação (um serviço)

1. **Backup** do sistema local; os pedidos locais **não são migrados automaticamente**.
2. No projeto Railway, crie **um novo serviço**, vinculando este conteúdo por GitHub ou `railway up`. Não substitua a `stayvision-previa`.
3. Adicione ao **mesmo serviço** um **Volume** Railway montado em **`/data`**. Ative backups do volume. Sem volume, o app se recusa a iniciar para não perder pedidos.
4. Em Variables, copie as variáveis de `.env.example` e troque as credenciais pelas **suas**, exclusivamente na Railway. `SV_PUBLIC_ORIGIN` deve ser a URL HTTPS gerada por Railway em Networking (não inclua `/` no final). Nunca cole chaves no chat.
5. Start Command: **`python web_public.py`**. **Healthcheck Path**: `/health`. Mantenha **1 réplica**, porque a fila/gravação em arquivos não é multiprocessual.
6. Gere domínio em Networking e confirme `/health` e `/api/status`. Abra `/painel` e entre com `SV_ADMIN_USER` / `SV_ADMIN_PASSWORD`.
7. **ANTES DE DIVULGAR**, faça pedido em modo controlado no domínio público, valide cobrança integral, reconciliação automática, edição, revisão, revogação/estorno e download no celular. O piloto de R$1 anterior não equivale ao teste comercial dos quatro planos.

## Valores fixos dos planos no backend
Fotos Business R$59,90 (1–6 fotos); Perfil Express R$149,90; Vitrine Digital R$249,90; Feed Premium R$399,90. **R$ 1 não é um valor comercial ativo**.

## Segurança operacional
- CHECKOUT: habilitado somente se token Mercado Pago, credenciais IA, volume permanente e autenticação estiverem configurados. Checagem do pagamento é feita no servidor pela API do Mercado Pago. Não usa o retorno do navegador como comprovante.
- PRODUTOS: no estado atual, o worker executa um pedido por vez, e reserva o custo *antes* de chamar a IA. Se houver interrupção ou dúvida, **não repete a cobrança de IA automaticamente**.
- ENTREGA: só é feita se o pagamento integral foi conciliado e a auditoria determinística passar. Uma foto pode ser ruim mesmo passando auditoria: casos sinalizados ficam retidos para aprovação humana. Esta análise **não garante qualidade semântica**.
- ACESSO: links do cliente têm tokens privados; o painel exige login; rotas locais de teste não são expostas. Links privados devem ser tratados como credenciais.
- SEGURANÇA: este é um **candidato de implantação** testado offline. Não foi possível fazer teste de integração no domínio Railway, em Mercado Pago nem na fal.ai a partir daqui. Não há garantia de 100% nem de ausência de bugs. Antes da venda pública são necessários testes reais, teste de carga, plano de privacidade/LGPD e recuperação de backups.
- LIMITE: `SV_AUTO_AI_BUDGET_MAX_CALLS` reserva, no máximo, a quantidade TOTAL de chamadas IA aprovada (não é mensal); `STAYVISION_IMAGE_SESSION_LIMIT` limita calls até reiniciar o processo; `SV_AUTO_DELIVERY_MAX_ORDERS` limita entregas automáticas por volume. Ajuste conscientemente após acompanhar custos na fal.ai.
- ESCOPO: o app usa arquivos JSON em volume, não banco transacional: **uma réplica só**. Para operação com muitos pagamentos simultâneos, mover estado para DB, usar jobs persistentes e revisar concorrência antes de escalar.

## Notas importantes
O Mercado Pago pode continuar cobrando mesmo que ninguém conheça o domínio — **não publique credenciais por engano**. Se quiser bloquear as vendas temporariamente, mude `SV_REAL_PLANS_ENABLED=0` e reinicie: o servidor não abrirá o checkout. Não compartilhe `SV_ADMIN_PASSWORD`, `GEMINI_API_KEY`, `FAL_KEY` ou `MP_LIVE_ACCESS_TOKEN`.

**Indexação:** enquanto `SV_SITE_PUBLIC_INDEX=0`, o servidor devolve `X-Robots-Tag: noindex, nofollow` para evitar indexação casual. Isso **não é senha** nem impede acesso de quem conhece a URL.
