# StayVision — Etapa 13: Photo Engine V3 + Video Export V2

## Objetivo

Esta entrega substitui o tratamento V2 por uma edição imobiliária **fiel à fotografia** e melhora a exportação do vídeo. Ela é a versão mais funcional implementável neste servidor sem uma GPU externa, assinatura de modelo generativo ou pesos de uma rede neural adicionais. **Não há reconstrução real de cômodos, vídeo generativo nem milagre de restauração de fotos irrecuperáveis.**

## Instalação segura no GitHub / Railway

1. Guarde o backup mais recente da Railway (`/data`: banco, uploads e entregas) e não apague o volume.
2. Extraia o ZIP entregue e envie os arquivos **da raiz** ao repositório `lucasviniciusff2000-ai/stayvision-studio`, mantendo o mesmo local de `server_online.py`, `Dockerfile`, `photo_engine_v2.py`, `photo_engine_v3.py`, `ai_engine.py` e a pasta `static`.
3. Confira o deploy `Active` e o painel administrativo. A nova seção informa `PHOTO ENGINE V3 · VIDEO V2`.
4. **Mantenha o checkout público bloqueado** enquanto o reconhecimento automático do Pix não for confirmado pela API, webhook e painel. Para pré-lançamento, não configure `STAYVISION_MP_PUBLIC_LAUNCH`; use `STAYVISION_MP_CHECKOUT_MODE=locked` após os testes restritos.
5. Não envie banco SQLite, diretório `/data`, senhas ou tokens para o GitHub. O pacote não inclui credenciais nem dados de pedidos reais.

### Operar no painel

- `Pedidos` → `Abrir` → `Produção inteligente`.
- `Fotos tratadas` com estilo **Claro** para fotos escuras; **Natural** para fotos boas; **Premium** para ajuste moderado de contraste e cor.
- Clique **Iniciar processamento** e baixe: `Fotos_StayVision.zip`, `Comparativo_StayVision_V3.jpg` e `Relatorio_Qualidade_V3.json`.
- Compare com as imagens originais em tamanho integral, especialmente **linhas retas, vegetação, piscina, céu, pisos, letras e portas**. Não entregue se aparecerem halos, borrões ou detalhes falsos.
- A revisão não altera status de Pix nem libera arquivos automaticamente ao cliente.

## Tratamento V3 — feito e testado

1. Correção leve de balanço de branco em tons neutros.
2. Detecção conservadora de ruído e redução leve quando necessário.
3. Abertura de sombras usando máscara de iluminação espacial de baixa frequência.
4. Contraste local controlado, preservando altas luzes. Não inventa detalhes estourados.
5. Redução seletiva de saturação exagerada em azul/ciano (céu e piscina), sem colorir gramados secos artificialmente.
6. Nitidez nas bordas em luminância, com limite contra halos.
7. Auditoria de cores e avisos de qualidade (baixa resolução, sombras sem informação, estourados, ruído).
8. Relatório por foto + folha de comparação real. Arquivos originais são preservados.

**Limite técnico importante:** V3 é **visão computacional / edição**, não rede generativa. Por padrão a resolução permanece igual à fonte. Super-resolução neural x2 FSRCNN é um caminho opcional legado quando um operador fornece pesos pré-treinados compatíveis no volume (`STAYVISION_PHOTO_SUPERRES_MODEL`). **Não vem junto**; não foi ativada nem validada com suas fotos neste pacote. Rede neural também pode criar texturas inexistentes, então exige revisão humana.

## Video V2 — feito e testado

- H.264 MP4, **30 fps**, CRF 19 em vez de 25 (menos compressão).
- Imagens de alta resolução podem gerar **1920×1080** horizontal ou **1080×1920** vertical; fotos pequenas geram 720p com menos custo.
- `STAYVISION_VIDEO_QUALITY=auto` (padrão): Full HD para até 8 fotos, todas com lado menor ≥950px; em outros casos 720p.
- `STAYVISION_VIDEO_QUALITY=balanced`: força 720p em Railway com pouca CPU.
- `STAYVISION_VIDEO_QUALITY=hd`: força 1080p, mas isso **não aumenta detalhe** de origem pequena; mais gasto de processamento.
- Cenas de 4 segundos por foto com movimento lento; ainda é um **vídeo 2D feito de fotos**, sem travessia 3D.
- Fotos verticais em vídeo horizontal terão preenchimento nas laterais: escolha **9:16 vertical** quando a maioria das fotos for vertical. Misturar orientações reduz a qualidade estética.
- Não há trilha musical incluída: adicionar música exige licença de utilização e projeto adicional.

## Como testar localmente no Windows

Com Python 3.12 (ou compatível) e FFmpeg instalados:

```powershell
pip install -r requirements.txt
python -m unittest discover -p "test_*.py" -q
python avaliar_photo_v3.py "C:\Fotos-Imovel" --estilo claro
```

O comando gera uma pasta separada `<pasta>_StayVision_V3` com as fotos, comparativo e relatório. Nunca sobrescreve a pasta original.

## Teste com fotografias reais do usuário

Três fotos externas de piscina receberam correção de luz, ruído, cor e contraste, sem remoção/recriação de objetos. Foi feito também um teste **sintético**: cada foto foi reduzida a 720px de largura, escurecida 28%, recebeu ruído gaussiano e foi salva como JPEG de qualidade 42. A métrica PSNR comparou cada versão com a original reduzida na mesma resolução:

| Foto | Entrada degradada | Após V3 | Diferença |
|------|-------------------|---------|-----------|
| Piscina frontal | 15,53 dB | 16,40 dB | +0,87 dB |
| Piscina lateral | 16,57 dB | 18,71 dB | +2,14 dB |
| Vista ampla | 16,33 dB | 18,63 dB | +2,30 dB |

PSNR **não equivale** a avaliação de marketing nem comprova recuperação de detalhes. O teste de degradação foi controlado; fotografias naturalmente ruins podem ter outro resultado. As comparações reais e o vídeo de prévia estão em ZIP separado (não publique fotos de imóveis do cliente no repositório).

## Política de qualidade comercial StayVision

- Nunca reconstruir cômodos/móveis/janelas/pisos inexistentes sem informar que é imagem ilustrativa.
- Se a imagem é insuficiente, solicitar original melhor. Não prometer detalhes invisíveis.
- Reduzir HDR exagerado, árvores radioativas, céu sintético, água neon.
- Medir artefatos em 100% de zoom; conferir fachadas, tijolos, pisos e texto.
- Aprovar individualmente as fotos tratadas e manter originais para auditoria.
- Não chamar efeito espacial 2.5D de tour 3D real.

## Situação do negócio — não considerar lançado

- **Foto:** edição V3 pronta para testes comerciais, ainda exige aprovação visual do resultado no imóvel real.
- **Vídeo:** exportação melhorada, ainda não generativa/3D real; requer curadoria e fontes adequadas.
- **3D real:** não implementado; exigirá captura orientada com cobertura e sobreposição, calibração, reconstrução multi-view (SfM/Gaussian splatting/NeRF), visualizador e revisão.
- **Neural super-resolution avançada:** precisa infraestrutura/modelos externos com testes, licenças e orçamento. Avaliar Real-ESRGAN (padrão geral); seu uso em imóveis demanda checagem de invenções de textura. Links informativos: https://github.com/xinntao/Real-ESRGAN e https://docs.opencv.org/4.x/d5/d29/tutorial_dnn_superres_upscale_image_single.html.
- **Financeiro:** primeiro Pix real foi recebido, mas o reconhecimento automático no painel não foi confirmado. A conciliação manual segura da Etapa 10 continua disponível; investigar webhook e repetir testes controlados de ponta a ponta antes de permitir vendas públicas.

## Arquitetura para a próxima evolução neural

`Site V1 → Pedido/upload → Volume /data → Job de produção → (pré-processamento V3 local) → (GPU worker opcional com modelo neural) → Auditoria antes/depois → Aprovação humana → Entrega após pagamento confirmado`.

Separar servidor web e worker GPU é necessário para evitar que uma única geração de vídeo paralise o site. Credenciais de serviços/modelos devem ficar na Railway/worker (variáveis privadas). Não submeter fotografias pessoais a serviços externos sem autorização informada do cliente. Não habilitar coberturas automáticas de custo sem tetos por pedido e controle de tentativas.

## Integridade / testes

- Suite: `python -m unittest discover -p 'test_*.py' -q` — **124 testes locais aprovados** durante desenvolvimento.
- Testes incluem fotos, MP4 H.264 720p/1080p, autenticação/admin, pedidos e simulação da reconciliação de pagamentos.
- **Não houve deploy na Railway nem teste de produção ao vivo desta V3**. O upgrade depende da publicação pelo proprietário ou conexão autorizada ao repositório.
