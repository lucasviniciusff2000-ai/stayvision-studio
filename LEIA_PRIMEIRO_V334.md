# StayVision Business V3.34 — recuperação do acompanhamento e painel

**Atualização incremental para a V3.33 comercial já instalada na Railway.** Não substitui o servidor inteiro.

## Correções

1. O operador autenticado pode gerar e copiar um **novo link privado de acompanhamento** diretamente nos detalhes de cada pedido. O endereço original continua válido. Os links adicionais são registrados **somente por hash** no volume `/data/jornada_cliente_v37/acessos_adicionais`. Não é necessário repetir a cobrança ou produzir imagem. A emissão requer sessão administrativa válida, origem de mesmo domínio e token CSRF. Os 10 links adicionais mais recentes ficam válidos, além do link original; novos links adicionais além do limite revogam os adicionais mais antigos.
2. O painel na Railway passa a identificar checkout real, fila automática e entrega automática por sinalizadores **locais de configuração**, sem chamar APIs pagas. O diagnóstico de configuração **não prova** que uma produção futura será bem-sucedida.
3. “Liberar galeria” foi alterado para **“Abrir galeria aprovada”**, pois o botão anterior apenas abria a galeria; a ação de revogação permanece separada.
4. Avisos desatualizados de ambiente local foram corrigidos no painel, no site inicial e na página de contratação.

## Teste seguro antes de publicar

Extraia o ZIP em uma pasta e execute `TESTAR_V334_SEM_CREDITOS_WINDOWS.bat`. O resultado esperado é **7/7 PASSOU**. O teste usa dados temporários, não conecta ao Mercado Pago, Gemini ou fal.ai e não consome créditos.

## Aplicação na branch `stayvision-v333-publicacao`

1. Guarde a versão anterior no GitHub (histórico de commits) ou em backup.
2. Faça upload **na raiz do repositório**, preservando os caminhos, dos arquivos:
   - `commerce_flow.py`
   - `admin_panel.py`
   - `web_public.py`
   - `painel_admin_v38.html`
   - `comprar_premium.html`
   - `index.html`
   - `assets/admin_v38.js` (precisa ficar **dentro de assets**).
3. **Não** envie `.env`, tokens, senhas ou arquivos de clientes. O ZIP não contém esses dados.
4. Confirme o commit na branch `stayvision-v333-publicacao`. Na Railway, publique o **último commit da branch**, não use Redeploy da versão antiga. Aguarde status Active e `/health` saudável.
5. Consulte `/api/status` para verificar `release: V3.34_UNIFIED_RAILWAY`; entre no painel, selecione o pedido aprovado e clique **Copiar novo link de acompanhamento**. O link abre `/acompanhar/...` sem pagamentos extras.
6. Não compartilhe publicamente os links privados. Se houver pedidos pagos **pendentes de produção**, reiniciar a aplicação poderá reativar o processamento em fila; verifique antes de fazer o deploy para não gerar consumo inesperado.

## Preservado

- Pagamento Mercado Pago e preços oficiais: Fotos Business R$ 59,90, Perfil Express R$ 149,90, Vitrine Digital R$ 249,90, Feed Premium R$ 399,90.
- Fila semiautomática existente, auditoria de qualidade e entrega condicionada à aprovação.
- Reserva do piloto único de R$ 1 já usado, no volume persistente; nenhuma tentativa adicional.
- Pedidos, galeria, fotos e acesso do administrador existentes.

**Limites**: o novo link é gerado **quando o administrador clica no botão**. Não é possível reconstruir o token original a partir do hash. Testes offline não substituem a validação após o deploy.
