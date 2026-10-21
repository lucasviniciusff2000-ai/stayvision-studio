# Módulo StayVision Tour 3D — plano técnico, ainda não implementado

## Por que fotos isoladas não bastam

Fotos de cômodos sem sobreposição não contêm a geometria que liga um quarto ao corredor, à sala e à cozinha. Uma IA generativa pode **inventar portas, paredes, dimensões e móveis**. Para uso imobiliário isso é inadequado. O efeito "2.5D" instalado agora é somente animação estética; NÃO é tour fiel.

## Arquitetura futura

1. **Captura guiada**: vídeo do celular caminhando por todo o imóvel com cenas sobrepostas e exposição estável; metadados opcionais de profundidade LiDAR.
2. **Estimativa/correção de poses** de câmera: SfM (por exemplo COLMAP), com análise dos pontos em comum e cobertura dos ambientes.
3. **Reconstrução 3D**: fotogrametria / Gaussian Splatting / NeRF, com necessidade de GPU, textura, escala e controle de distorção.
4. **Tour navegável**: visualização com controles de câmera, posições de partida, cômodos, escala e nomenclatura verificada.
5. **QA imobiliário obrigatório**: cruzamento com fotos reais, sem portas ou quartos inventados; não publicar se a geometria falhar.
6. **Custo e infraestrutura**: worker GPU separado da pequena Railway (que deve manter apenas painel, armazenamento e filas). Provedor e cobrança precisam ser autorizados antes de processar.

## Gancho já presente na Etapa 11

Cada produção inclui `projeto_3d_futuro.json`, com lista dos arquivos processados e pré-requisitos. Uma integração futura poderá associar um modelo 3D e o respectivo identificador do projeto sem alterar checkout, clientes ou o fluxo de entregas.

## Critério de aceite

O tour só será "3D real" quando o usuário conseguir percorrer ambientes conectados e quando a navegação corresponder visualmente às fotos, dimensões e portas capturadas. Caso contrário, apresentar apenas como **vídeo ilustrativo**.
