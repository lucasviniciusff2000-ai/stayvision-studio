# StayVision Studio V1 — Prévia segura para Railway

Esta etapa publica somente a **apresentação visual** do site StayVision V1. O layout, os planos e as imagens de referência estão incluídos.

- **Não** recebe pedidos, fotos ou dados pessoais.
- **Não** oferece painel de administração pela internet.
- **Não** tem pagamentos ou credenciais Mercado Pago.
- Não use a pasta antiga com `.env.local`/`dados` no GitHub.
- No Railway: conecte repositório GitHub privado contendo estes arquivos (Dockerfile no diretório principal), faça deploy, depois gere domínio em Networking.
- Endpoint de saúde: `/api/health`.
- Precisa testar a publicação visual **antes** de migrar o sistema real com login seguro, armazenamento persistente e integração de pagamentos.

> A estrutura de trabalho local completa continua separada. Não apague arquivos da versão Windows.
