# StayVision Advanced Imaging — plano de implementação com critérios de aprovação

## Foto neural de alta qualidade

1. Validar Photo Engine V3 com 20+ imagens de diferentes imóveis (interno escuro, céu claro, baixa resolução, fachada noturna, pisos texturizados).
2. Integrar um serviço privado de super-resolução (opção Real-ESRGAN x2 ou outro modelo de qualidade) **somente depois de** fechar infraestrutura GPU ou opção CPU comprovadamente viável. Pesos precisam ter licença verificada.
3. Criar modo `fidelidade` versus `mais nitidez`, controle de intensidade e fallback para V3 quando o modelo neural apresentar defeitos.
4. Validar textura de pedra/tijolo/azulejo em 100% e exigir revisão antes de entrega. Não criar móveis, janelas ou modificar anúncio.

## Vídeo cinematográfico

1. Escolher orientação e enquadramento apropriados para cada conjunto de fotos; produzir sequências a partir de fontes ≥1080p; aplicar trilha licenciada opcional.
2. Para vídeo generativo, submeter job assíncrono a provedor com política de privacidade, orçamento e licença comercial; comparar com fotos reais e rejeitar criação de portas/paredes inexistentes.
3. Modelar custo por minuto, tempo e taxa de falhas; plano R$197 não pode ter custo de geração superior à margem disponível.

## Tour 3D real

- Requisito de captura: vídeo contínuo/uma série sobreposta de fotos cobrindo caminhos e ângulos; 3 fotos desconexas de piscina não fornecem geometria para atravessar cômodos.
- Pipeline: SfM/COLMAP para poses, reconstrução multi-view / 3D Gaussian Splatting ou fotogrametria, visualizador web, calibração e mascaramento.
- Critérios: paredes não atravessáveis, geometria estável, escala e portas coerentes, navegação suave e revisão de privacidade. Em casos sem cobertura adequada, recusar tour real e oferecer vídeo 2D.
- É um produto separado com infraestrutura GPU e roteiro de captura; **não faz parte da entrega funcional desta versão**.

## Liberação comercial

- 10 pedidos de teste completos incluindo conciliação Pix automática e entrega.
- Pelo menos 20 fotos aprovadas por revisão humana sem alterações enganosas do imóvel.
- Vídeo com fontes adequadas, 1080p quando possível, orientação correta e direitos de trilha.
- Política de privacidade e de retenção das fotos, backup automático e método de restauração testado.
- Limites de custo por processamento, timeout, logs de falha e fila de produção escalável.
