# StayVision Studio V1 — Etapa 11 · Creative Engine

**Atualização instalada sobre a Etapa 10 do código**, mantendo a interface V1 (verde escuro/creme), pedidos, painel, checkout e conciliação Pix. **Nenhum dado pessoal, token ou banco de produção está neste ZIP.**

## O que realmente funciona nesta entrega

| Função | Implementação | Situação |
| --- | --- | --- |
| Melhorar até 12 fotos de um pedido | Pillow: rotação EXIF, correção moderada de luz/contraste/balanço de branco/cor, nitidez, compressão JPEG | **Testado localmente** |
| Baixar fotografias tratadas | ZIP com JPGs prontos para revisão | **Testado localmente** |
| Vídeo horizontal 16:9 | FFmpeg: MP4 1280×720, 24fps, cenas de ~4s/foto, suave movimento de câmera, **sem áudio** | **Testado localmente** |
| Vídeo vertical 9:16 | FFmpeg: MP4 720×1280, para Shorts/Reels, cenas iguais | **Testado localmente** |
| Efeito espacial experimental | Segundo MP4 com enquadramento/movimento diferente; efeito ilustrativo **2.5D**, não representa a geometria do imóvel | **Testado localmente** |
| Pacote final | ZIP com fotos e vídeos para anexar pelo painel em um único arquivo | **Testado localmente** |
| Iniciar no painel | Painel → Pedidos → Abrir → Produção inteligente → selecionar modo e estilo → Iniciar | **Testado em simulação HTTP local** |
| Histórico e downloads privados | Banco SQLite persistente; somente admin logado; bloqueio de caminhos inválidos | **Testado localmente** |
| Fila de renderização | Uma renderização por processo; tratamento de reinício com status interrompido | **Testado localmente** |
| Processamento opcional após pagamento confirmado | Se `STAYVISION_AI_AUTO_PROCESS=1`, quando API validar Pix, gera materiais para **revisão**, sem entregar automaticamente | **Implementado; integração real webhook pendente de validação** |
| **Tour 3D verdadeiro** | Exige múltiplas visões, reconstrução, calibração, qualidade e navegação; projeto inicial e contrato futuro inclusos | **NÃO implementado** |
| Vídeo gerado por rede neural (passeio criativo entre cômodos) | Necessita provedor externo pago com consentimento e validação espacial | **NÃO implementado** |

**Transparência:** o motor local de imagem usa algoritmos de processamento fotográfico adaptativos, não um modelo generativo de IA. Não é adequado alegar que ele recria ambientes ou faz staging virtual. O vídeo usa fotos animadas, **não uma câmera real ou reconstrução 3D**. Essas limitações são intencionais para evitar alterações enganosas em imóveis.

## Instalação na Railway sem abrir vendas

1. **Guarde o ZIP do backup que você já fez de `/data`**. Se houve novos pedidos depois, faça outro backup antes de atualizar.
2. Extraia este ZIP, envie os arquivos para a **raiz** do mesmo repositório GitHub `stayvision-studio`, incluindo `Dockerfile`, `ai_engine.py`, `server_online.py` e `static/`. Não crie pasta filha extra. Faça commit na branch usada pela Railway.
3. Quando a Railway voltar a permitir deploys, aguarde o novo deploy ficar **Active**. Como adicionamos Pillow e FFmpeg, a primeira construção pode demorar mais.
4. **Não altere** `MP_PRODUCTION_ACCESS_TOKEN`, `MP_PRODUCTION_COLLECTOR_ID`, `MP_WEBHOOK_SECRET` nem as credenciais do painel. **Preserve o volume `/data`**.
5. Não habilite vendas públicas. Uma configuração segura durante o desenvolvimento:

```ini
STAYVISION_DATA_DIR=/data
STAYVISION_MP_CHECKOUT_MODE=locked
STAYVISION_MP_AUTO_CONFIRM=1
STAYVISION_AI_AUTO_PROCESS=0
# STAYVISION_MP_PUBLIC_LAUNCH deve estar AUSENTE
```

O modo `locked` impede novas preferências, mas **não bloqueia conciliações de pagamentos que já existem**, quando as respectivas verificações estiverem corretamente habilitadas.

6. Abra `https://SEU-DOMINIO/painel`, faça login, abra o pedido de fotos e procure **Produção inteligente de fotos e vídeos**. O pedido pode estar pendente para testes internos, mas **o cliente só recebe arquivos manualmente após confirmação do pagamento**.
7. Escolha **Fotos tratadas**, **Vídeo**, **Movimento 2.5D** ou **Pacote completo**. Escolha estilo e orientação do vídeo; clique **Iniciar processamento**. Aguarde o indicador e baixe os arquivos.
8. Revise visualmente todos os ambientes: enquadramento, detalhes do imóvel, paredes, azulejos e janelas. Para entregar ao cliente, use o formulário já existente **Entregar arquivo final**, selecionando o ZIP do pacote, **somente após conferir pagamento aprovado**.

### E se o botão apresentar uma falha?

- `FFmpeg ausente`: o `Dockerfile` atualizado não foi publicado ou a Railway ainda está usando a versão anterior.
- `Outro pedido está renderizando`: o serviço só processa um pedido por vez. Aguarde.
- `Foto inválida`: confira extensão e conteúdo (JPG, PNG ou WEBP). Não aceite imagens corruptas.
- `interrompido`: Railway reiniciou o container no meio da produção; clique para iniciar outra vez quando estiver estabilizada.
- Sem botão novo: Ctrl+F5, confira commit/deploy **Active**, verifique no GitHub se `ai_engine.py` foi enviado.
- O recurso de fotos/vídeos **não depende das novas chaves pagas de IA**.

## Teste local no Windows

Requisitos: Python 3.10+, FFmpeg instalado e no PATH (para vídeo).

```powershell
pip install -r requirements.txt
python executar_demo_ia.py --modo complete
```

A demonstração processa duas fotos de referência que já existem no diretório `static/assets/`. Os resultados vão para `demo_ia_saida/` (pasta ignorada pelo Git). Você também pode informar `--modo photo` caso FFmpeg não esteja instalado.

Teste técnico (sem Mercado Pago real):

```powershell
python -m unittest -q test_ai_stage11 test_online test_payments_readiness test_webhook_diagnostic test_reconciliation test_checkout_stage6 test_checkout_stage7 test_seller_stage8 test_seller_stage8_2 test_checkout_stage9 test_checkout_stage10
```

## Segurança e limites

- **Nenhuma função de geração chama a API do Mercado Pago, produz preferência de pagamento ou transfere dinheiro.** A reconciliação existente da Etapa 10 foi preservada.
- O processamento acontece no servidor e nunca expõe tokens ou arquivos de clientes publicamente; resultados passam apenas pelos endpoints privados do admin.
- Apenas o admin pode executar processamento. Os arquivos permanecem em `/data/ai_gerados/<pedido>/<execucao>/`, além dos arquivos originais em `/data/uploads/`.
- O volume do servidor precisa de espaço. Evite processar o mesmo pedido repetidamente sem revisar o armazenamento.
- Há **um processo de renderização por vez**, sem fila distribuída. Reinícios podem interromper vídeos.
- Não envie fotos privadas a fornecedores externos sem autorização e política de privacidade clara.
- O primeiro Pix do Mercado Pago **foi recebido, segundo o relato**, mas a confirmação automática no pedido **ainda não está validada**. Não anuncie vendas públicas antes de conferir a conciliação + webhook real e a entrega.
- Não divulgue passeios 3D reais; apenas o efeito 2.5D está disponível nesta versão.

Veja `PLANO_3D_VERDADEIRO.md` para a próxima etapa, que depende de imagens sobrepostas ou vídeos gravados percorrendo o imóvel e/ou serviço de visão computacional mais caro.
