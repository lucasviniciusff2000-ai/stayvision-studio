# Gupshup + StayVision — Integração de atendimento IA (proposta)

## Estado atual
- Gupshup app StayVisionBusiness está Live por Coexistência.
- Webhook usará formato Meta v3 e exigirá cabeçalho secreto customizado.
- A rota está somente na branch de proposta. NÃO está publicada na Railway.
- Respostas automáticas ficam DESLIGADAS por padrão.

## Gupshup > Webhooks > Add Webhook
- Webhook name: StayVisionIA
- Callback URL, APÓS publicação: https://truthful-embrace-production-c05b.up.railway.app/api/gupshup/webhook
- Payload format: Meta format (v3).
- Eventos: mensagens recebidas (Incoming/Message received).
- Include headers: X-StayVision-Webhook-Key = segredo aleatório forte, mínimo 32 caracteres. O MESMO segredo deve estar na Railway em SV_GS_WEBHOOK_SECRET.
- Se o painel NÃO permitir configurar esse header, NÃO HABILITE o webhook. Necessário outro controle de autenticidade antes.
- Deixar controles de BSUID inalterados.

## Railway > truthful-embrace > Variables
Definir exclusivamente na Railway, sem expor tokens em prints/GitHub:
SV_WA_PROVIDER=gupshup
SV_GS_APP_ID=<ID UUID verdadeiro do app Gupshup>
SV_GS_SOURCE=<DDI DDD numero comercial, apenas digitos>
SV_GS_APP_NAME=StayVisionBusiness
SV_GS_API_KEY=<API key privada do app Gupshup>
SV_GS_WEBHOOK_SECRET=<mesmo segredo de 32+ caracteres do header>
GEMINI_API_KEY=<ja existente>
SV_WA_AUTO_REPLY_ENABLED=0
SV_WA_TEST_PHONE=<seu numero de teste, apenas digitos>
SV_WA_LIVE_APPROVED nao deve ser habilitada no piloto.

## Ordem operacional
1. Revisar codigo e executar testes locais.
2. Publicar a branch revisada no Railway com auto reply DESLIGADO.
3. Configurar callback Gupshup com header e selecionar mensagens recebidas.
4. Confirmar que notificacoes entram com seguranca.
5. Ativar o piloto somente para o numero de teste. Validar pergunta sobre planos, duplicatas, custos e transferencia humana.
6. Somente apos homologacao, revisar custos, suporte humano e ativacao geral.

## Limites atuais
- Respostas somente a mensagens recebidas, dentro da janela de 24h.
- Precos sao lidos de engine.PLANS. Sem envio de marketing ou disparo em massa.
- Texto persistido em SQLite em /data; deduplicacao, limites de envio, pausa para atendente humano.
- Falta interface para retomar bot apos pausa. Sem suporte a audios/imagens nesta fase.
- Um envio aceito pela Gupshup nao prova entrega ao cliente. Confirmar pelo painel.
- Nao modificar fluxo de compra, pagamento e producao.
- Testes estaticos estao no repositorio, mas validacao integrada ainda nao foi concluida.

## Documentacao oficial
https://partner-docs.gupshup.io/docs/events
https://docs.gupshup.io/docs/what-is-a-webhook
https://www.gupshup.io/developer/guide?name=whatsapp-api-documentation
