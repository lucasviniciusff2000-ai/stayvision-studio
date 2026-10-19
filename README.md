# StayVision Studio V1 — Etapa 2: pedidos demonstrativos na Railway

**Versão de homologação online, não pronta para clientes reais nem transações financeiras.**

Preserva o visual V1 e adiciona o servidor privado de pedidos, upload de imagens de teste, acompanhamento, painel e central de operações. O checkout, tokens Mercado Pago e IA estão desativados no código desta distribuição.

## Antes de atualizar o GitHub

1. **Faça backup** da versão local no Windows. Os dados antigos do Windows **não** migram automaticamente.
2. Na Railway, abra o **mesmo serviço** do projeto Estúdio StayVision que já está ativo.
3. Anexe **um Volume** a esse serviço (opção Volume / Add Volume ou menu de contexto do projeto), com `Mount Path` exatamente `/data`. O Railway Trial admite volumes, normalmente com **limite de 0,5 GB**. Fonte: https://docs.railway.com/volumes/reference
4. Em **Variables** do mesmo serviço, cadastre (os exemplos abaixo não são senhas reais):

   | Nome | Valor |
   |------|-------|
   | `STAYVISION_DATA_DIR` | `/data` |
   | `STAYVISION_PUBLIC_URL` | `https://truthful-embrace-production-c05b.up.railway.app` |
   | `STAYVISION_ADMIN_USER` | usuário escolhido por você, de 3–30 caracteres alfanuméricos, `_` ou `-` |
   | `STAYVISION_ADMIN_PASSWORD` | uma senha **única**, com **pelo menos 16 caracteres** |
   | `STAYVISION_ENABLE_DEMO_ORDERS` | `0` (inicialmente) |

   *Jamais coloque essas variáveis, senha ou chaves Mercado Pago no GitHub, em código ou em prints.*

5. A Railway aplica alterações de variáveis/volume em implantações. Confirme as alterações na interface.

## Atualizar o repositório existente

1. Extraia este ZIP no computador.
2. Abra seu repositório `lucasviniciusff2000-ai/stayvision-studio`, aba **Code → Add file → Upload files**.
3. Adicione os **arquivos e a pasta `static` extraídos** na raiz do repositório (mesmo nível do `Dockerfile`). Confirme a substituição dos arquivos antigos, se o GitHub pedir. Não envie o ZIP intacto.
4. Faça **Commit changes** na branch conectada à Railway (`main`, se essa for a principal).
5. Confira a aba **Deployments** da Railway. Se houver falha, veja os logs sem compartilhar variáveis privadas.
6. Acesse `https://truthful-embrace-production-c05b.up.railway.app/api/health` e procure `{"ok": true, "mode": "pedidos_demo", "payments": false}`.
7. Acesse `/painel` e faça login com `STAYVISION_ADMIN_USER` e `STAYVISION_ADMIN_PASSWORD` cadastrados em Variables. **Não existe cadastro público de administrador.**

## Liberar apenas pedidos de DEMONSTRAÇÃO

Quando login e armazenamento estiverem funcionando:

1. Em Railway → Variables, altere `STAYVISION_ENABLE_DEMO_ORDERS` para `1`.
2. Salve, aplique/reimplante e recarregue o site.
3. Use **somente fotos de demonstração** e informações fictícias para conferir o formulário e o painel. O site não gera cobrança e nenhum valor deve ser pago.
4. Consulte `/painel` e `/operacoes`. O cliente pode acompanhar um pedido criado com o link privado.
5. Se quiser interromper novos pedidos, defina `STAYVISION_ENABLE_DEMO_ORDERS=0` novamente.

## Segurança e limites

- Nenhuma senha, token financeiro, arquivo pessoal ou banco está incluído neste pacote.
- Nenhum endpoint pode criar cobranças ou marcar pagamento como aprovado por conta própria. **Pix real ainda não foi conectado.**
- Ao usar `/data`, os arquivos permanecem no Volume entre reinícios/deploys, mas **um Volume não substitui backup**, e os dados de Trial podem expirar quando o plano termina. Consulte https://docs.railway.com/pricing/free-trial e https://docs.railway.com/volumes.
- Ao criar o volume, a Railway monta como root. Este contêiner executa o servidor como root para escrita no volume no ambiente demonstrativo. Para operar com fotos de clientes reais, realizar auditoria e endurecimento adicional e migrar para armazenamento/infra com princípio do menor privilégio.
- Não habilitar vendas reais antes de concluir implantação de pagamentos, validação de webhook, política de privacidade, termos, proteção antiabuso, backups e testes de restauração.
- Versão de teste pensada para **uma réplica** com SQLite. Arquivos de teste contam para o limite de armazenamento, e a API limita tamanho de imagens e taxa de pedidos.

## Arquivos essenciais

- `Dockerfile` — configura o servidor Python na Railway.
- `server_online.py` — backend de demonstração protegido, não usa Mercado Pago.
- `static/` — visual original V1, área do cliente, painel e central de operações.
- `test_online.py` — testes automatizados (`python -m unittest -v test_online`, sem bibliotecas extras).
