# StayVision Business — atendimento automático via WhatsApp Cloud API

## Escopo
Este módulo responde **somente mensagens de texto recebidas** no número oficial do WhatsApp Business. Não prospecta nem inicia conversas comerciais, não altera checkout, painel financeiro nem motor de imagens. Desligado por padrão. A mensagem de prospecção já aprovada permanece inalterada em sua rotina separada.

A API precisa do WhatsApp Business Platform (Meta Cloud API). Apenas instalar WhatsApp no celular, abrir WhatsApp Web ou cadastrar o número na Central não conecta uma API.

## Credenciais — somente Railway > truthful-embrace > Variables
Configure os seguintes valores no serviço da StayVision, **sem colar tokens no chat nem subir segredos ao GitHub**:

| Variável | Origem |
|---|---|
| SV_WA_CLOUD_TOKEN | Token de usuário do sistema da Meta com permissões para WhatsApp Business Messaging |
| SV_WA_PHONE_NUMBER_ID | Identificador numérico do número na Meta (não é o próprio telefone) |
| SV_WA_APP_SECRET | Meta App > Configurações > Básico > Chave secreta do aplicativo |
| SV_WA_WEBHOOK_VERIFY_TOKEN | Segredo longo e aleatório criado por você para confirmar o webhook |
| SV_WA_GRAPH_VERSION | Opcional, v26.0 por padrão |
| SV_WA_GEMINI_MODEL | Opcional, herda creative_ai.DEFAULT_MODEL |
| SV_WA_TEST_PHONE | Número do seu CELULAR DE TESTE, DDI+DDD+telefone, só dígitos |
| SV_WA_AUTO_REPLY_ENABLED | Comece em 0; passe a 1 somente no teste |
| SV_WA_LIVE_APPROVED | **Não definir durante piloto.** Após homologação, definir 1 e retirar SV_WA_TEST_PHONE para atendimento generalizado |

A variável GEMINI_API_KEY já integra o motor criativo StayVision e é reutilizada.

**Importante:** se SV_WA_TEST_PHONE estiver vazio e SV_WA_LIVE_APPROVED não for 1, o bot não responde ninguém. SV_WA_AUTO_REPLY_ENABLED=0 é o desligamento geral.

## Meta — Webhooks
1. Publique a atualização da branch (mesclar PR na branch conectada ao Railway, com bot desligado).
2. Abra https://developers.facebook.com/apps/ e escolha o aplicativo que possui o número.
3. WhatsApp > Configuração (ou Casos de uso > Personalizar > Configuração) > Webhooks.
4. **URL de callback:** https://truthful-embrace-production-c05b.up.railway.app/api/whatsapp/webhook
5. **Token de verificação:** exatamente o conteúdo de SV_WA_WEBHOOK_VERIFY_TOKEN.
6. Clique em Verificar e salvar; assine o evento **messages**. O backend compara o token e devolve o challenge.
7. Garanta que o número está habilitado na Cloud API, registrado para envio e que o token tem acesso à conta correta.

## Homologação restrita
1. Configure SV_WA_TEST_PHONE com um celular diferente do número comercial.
2. Defina SV_WA_AUTO_REPLY_ENABLED=1 (o Railway reinicia o serviço).
3. Do celular de teste, envie 'Oi, como funciona?' ao número comercial.
4. Verifique a resposta: ela deve falar dos planos reais, sem inventar descontos/prazos.
5. Escreva 'quero falar com um atendente': o bot oferece transferência e pausa a automação para o número.
6. Confira conversa e estados pelo endpoint privado GET /api/admin/whatsapp/status (exige login).
7. Em caso de problema, volte SV_WA_AUTO_REPLY_ENABLED=0 na Railway.

Não é garantida entrega só porque a Meta aceitou envio. O sistema guarda estados e não repete tentativas incertas automaticamente.

## Características e limites
- Assinatura HMAC SHA-256 obrigatória nos POSTs, número da API conferido, webhook de verificação GET.
- Mensagens recebidas são registradas em SQLite no volume persistente /data, sem logs de texto pessoal.
- Fila em segundo plano, deduplicação por ID, limite de 12 respostas por telefone e 100 globais em 24 h.
- Textos do cliente não são instruções de sistema para a IA. Respostas usam tabela oficial de planos da própria aplicação.
- Histórico recente para contextualização e retenção de até 30 dias, limpeza na inicialização.
- Sem resposta para mídia/áudio neste MVP. A IA pausa o atendimento quando pedem pessoa, mas o operador deve acompanhar a fila; a retomada da IA não está pronta nesta versão.
- A Meta limita mensagens livres à janela de 24 h aberta por mensagens recebidas do cliente. Para iniciar conversas ou escrever após o encerramento da janela, siga requisitos de consentimento e template aprovado, usando o mecanismo comercial separado.
- Meta e Gemini podem cobrar pelo uso; confira tarifas aplicáveis e defina orçamento.

## Testes locais
Na raiz do repositório execute:
python -m unittest discover -s tests -p test_whatsapp_ai_atendimento.py -v

Os testes são locais, usam números e segredos fictícios e não enviam mensagens.
