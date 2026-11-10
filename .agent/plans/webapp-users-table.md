<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#escopo">Escopo</a></li>
        <li><a href="#dependências">Dependências</a></li>
        <li><a href="#resumo-dos-gates">Resumo dos gates</a></li>
        <li><a href="#g1-fundamentos-css">G1 Fundamentos CSS</a></li>
        <li><a href="#g2-lógica-pura">G2 Lógica pura</a></li>
        <li><a href="#g3-marcação">G3 Marcação</a></li>
        <li><a href="#g4-controlador">G4 Controlador</a></li>
        <li><a href="#g5-validação-de-navegador">G5 Validação de navegador</a></li>
        <li><a href="#g6-documentação">G6 Documentação</a></li>
        <li><a href="#fora-do-escopo-e-riscos">Fora do escopo e riscos</a></li>
    </ol>
</details>

# Plano: tabela de usuários da webapp

## Escopo

Este plano implementa o [contrato da tabela de usuários](../contracts/webapp-users-table.md) na SPA de `webapp/frontend/`. O contrato é a fonte normativa: requisitos REQ-01 a REQ-12, critérios AC-01 a AC-12, decisões D1 a D9, R1, R2, ícones, desvios a a e e premissas P1 a P8.

Cada gate fecha com um commit próprio e só avança quando sua validação passa.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Dependências

- Contrato: [webapp-users-table](../contracts/webapp-users-table.md). Os gates citam os IDs dele.
- Plano base: [webapp-crud](webapp-crud.md), já implementado.
- Arquivos existentes usados: `webapp/frontend/index.html`, `webapp/frontend/styles.css`, `webapp/frontend/app.js` e `webapp/frontend/tests/`.
- Assets vendorizados: `webapp/frontend/assets/vendor/govbr-core-3.7.0/core.min.css` e `chevron-left.svg` e `chevron-right.svg` em `webapp/frontend/assets/vendor/fontawesome-5.11.2/solid/`.
- Nenhuma dependência nova. Testes usam `node --test` e verificação de sintaxe usa `node --check`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Resumo dos gates

| Gate | Nome | Arquivos | ACs cobertos | Depende de |
|---|---|---|---|---|
| G1 | Fundamentos CSS | `webapp/frontend/styles.css` | Estilos de AC-03, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12 | Nenhum |
| G2 | Lógica pura | `webapp/frontend/table-model.mjs` (novo), `webapp/frontend/tests/table-model.test.mjs` (novo) | AC-01, AC-02, AC-04, AC-05, AC-06, AC-09, AC-11 | Nenhum |
| G3 | Marcação | `webapp/frontend/index.html`, `webapp/frontend/styles.css` | Estrutura de AC-03, AC-07, AC-08, AC-09, AC-10, AC-12 | G1 |
| G4 | Controlador | `webapp/frontend/app.js` | AC-03, AC-04, AC-05, AC-07, AC-08, AC-09, AC-11, AC-12 | G2, G3 |
| G5 | Validação de navegador | Nenhum arquivo de código. Evidência em `.agent/memory/webapp-users-table-validation.md` | AC-03 a AC-12 | G4 |
| G6 | Documentação | `docs/recipes/govbr-design-system.md`, `docs/recipes/webapp-crud.md` | Desvios a a e, comportamento validado em G5 | G5 |

Ordem: G1 e G2 podem ocorrer em paralelo. G3 segue G1. G4 segue G2 e G3. G5 segue G4. G6 segue G5.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## G1 Fundamentos CSS

- **Escopo.** Base visual dos componentes novos, sem marcação nova.
- **Arquivos.** Somente `webapp/frontend/styles.css`.
- **Mudanças.**
  - Indicador de ordenação com dois triângulos, alinhados à direita, com direção ativa destacada (D1, P1).
  - Spinner somente CSS com `@keyframes` de rotação. Sob `prefers-reduced-motion: reduce`, remove a rotação e aplica pulsação lenta de opacidade (R2).
  - Mecanismo de ocultação: atributo HTML `hidden`. Cada componente novo que define `display` recebe regra `seletor[hidden] { display: none; }` com o mesmo seletor, para vencer o `display` da classe.
  - Chip: botão pequeno com "x" à esquerda do texto e foco visível (D4).
  - Menu Ellipsis-v: painel, itens, item ativo com marcador visual e foco visível, em todas as larguras (D1).
  - Barra de paginação: rodapé com "Exibir", contador, "Página" e setas (D2, D8).
  - Banner de limite com bloco informativo (R1).
  - Seletores de estado: `.table-sort-indicator.is-ascending`, `.table-sort-indicator.is-descending`, `.table-sort-menu-item.is-active`, `.table-sort-menu-item[aria-current="true"]`, `.table-loading-spinner[hidden]` e `.table-scroll[aria-busy="true"]`; `.table-card-cell` e `.table-card-label-row` são criadas por `createUserRow` em G4 e usam o override CSS de G1.
  - Tokens: usar somente custom properties definidas em `styles.css` ou em `assets/vendor/govbr-core-3.7.0/core.min.css`.
- **ACs cobertos.** Estilos de AC-03, AC-07, AC-08, AC-09, AC-10, AC-11 e AC-12. A verificação final é feita em G5.
- **Validação planejada.** `node --test webapp/frontend/tests/css-scanner.test.mjs`. Complemento: `node --test webapp/frontend/tests/navigation.test.mjs`, porque ele lê `styles.css`. O teste do scanner cobre somente o parser.
- **Depende de.** Nenhum gate.
- **Commit.** `style(webapp): add users table base styles`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## G2 Lógica pura

- **Escopo.** Funções sem DOM para busca, destaque, ordenação, limite, paginação e contador. Não usar `window` nem `document`.
- **Arquivos.** Novos: `webapp/frontend/table-model.mjs` e `webapp/frontend/tests/table-model.test.mjs`; plano e contrato usam os nomes e formatos do código.
- **Mudanças.** Exportar:
  - `parseSearchTerms(query)`: separa por espaço, trata frase entre aspas como termo único e descarta termos vazios ou que normalizam para vazio (D4, P7).
  - `normalizeText(text)`: remove marcas diacríticas e converte para minúsculas (D4).
  - `toSearchText(value)`: texto de strings; números com `String`; `Date` no formato pt-BR `dd/MM/yyyy, HH:mm`; `null` e `undefined` viram texto vazio (D3). A busca coincide com o texto que o usuário lê.
  - `rowMatches(row, terms, fields)`: combina termos com OR sobre os campos informados em `fields` (D3, D4).
  - `findHighlightRanges(text, terms)`: retorna intervalos no texto original. Mapeia os índices de volta ao texto original após NFD e mescla intervalos sobrepostos (D4).
  - `sortRows(rows, field, direction)`: usa `Intl.Collator("pt-BR", { numeric: true, sensitivity: "base" })`. Empates usam `id` em ordem crescente. Com `field` nulo, retorna cópia na ordem recebida (D6, P6).
  - `cycleSort(current, clickedField)`: campo diferente do atual resulta em ascendente. Mesmo campo alterna entre ascendente e descendente (D5, D1).
  - `filterAndCap(rows, terms, fields, cap = RESULT_CAP)`: filtra primeiro e limita depois. Retorna `{ rows, totalFiltered, isCapped }` (R1).
  - `paginate(rows, page, pageSize)`: aceita `pageSize` de 10, 50 ou 100. Limita `page` ao intervalo válido e retorna `{ items, page, totalPages, start, end }` (D2).
  - `counterText({ start, end, total })`: recebe em `total` a contagem de linhas já limitadas (`rows.length` no resultado de `filterAndCap`), não `totalFiltered`; retorna "1-10 de N itens" e, com `total` zero, "Nenhum item" (D8, P4).
- **ACs cobertos.** AC-01, AC-02, AC-04 (intervalos), AC-05 (`cycleSort`), AC-06, AC-09 (`paginate` e `counterText`) e AC-11 (`filterAndCap`).
- **Validação planejada.** `node --check webapp/frontend/table-model.mjs` e `node --test webapp/frontend/tests/table-model.test.mjs`.
- **Depende de.** Nenhum gate. Pode ocorrer em paralelo com G1.
- **Commit.** `feat(webapp): add users table model`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## G3 Marcação

- **Escopo.** Estrutura estática de todos os controles novos, com estado inicial correto e sem comportamento.
- **Arquivos.** `webapp/frontend/index.html` e `webapp/frontend/styles.css`, somente para ajustes de layout exigidos pela estrutura.
- **Mudanças.**
  - Barra de título com botão de lupa (SVG inline original) e campo de busca sobre a barra, com botão de fechar. Ambos ficam ocultos por padrão.
  - Search chip container next to search input; each chip uses GovBR Core `.br-button.small` modifier. Não adicionar `min-height` local, exceto `min-height: var(--button-size)` no chip, para manter a altura do botão pequeno com quebra de linha; exceção: `min-height: 100%` no `.table-search-field`, para que o campo tenha no mínimo a altura da barra de título.
  - Botão de reticências (SVG inline original) com `aria-expanded="false"` e `aria-controls="users-table-menu"`. O menu tem "Adicionar usuário" e o grupo "Ordenar" com Nome, Email e Localização. O menu começa com `hidden`.
  - Cabeçalhos de Nome, Email e Localização com botão de ordenação e `aria-sort="none"`. Foto e Ações não recebem botão.
  - **G3-R1 Menu clipping.** G3 must prevent `.table-sort-menu` from being clipped by the existing `.table-card { overflow: hidden; }` in cards with 0 or 1 row. For example, allow overflow on the card and preserve rounded corners on its children. G5 must verify 0 and 1 rows at 375, 768, and 1024 px.
  - **G3-R2 Chip DOM order.** Place the remove control before the term text in the DOM. Its accessible name is `Remover <termo>`. Do not reorder with CSS.
  - D-01 (G5): reticências e menu permanecem acessíveis com o campo de busca aberta; abrir o menu fecha e limpa a busca (opção B, aprovada).
  - Corrigir regressão de D-01: X mantém tamanho e chips quebram linha (flex-wrap, min-width 0).
  - D-02 (G5): o campo de busca cresce em altura para caber os chips; a área de chips rola após cerca de três linhas (opção A aprovada). Validar no G5 (check t de .agent/memory/webapp-users-table-validation.md, D-02).
  - D-03 (G5): margem-inferior do input zerada (override de .input do GOV.BR) para que o input fique centrado no botão X; validar no G5 com t3.
  - Contorno de foco dos chips: padding de 8 px (var(--spacing-scale-base)); contêiner sem chips não ocupa espaço (:not(:has(...))).
  - Ordem no HTML: chips após o botão X, sem order por CSS (G3-R2).
  - Rodapé de paginação: seletor "Exibir" com 10, 50 e 100 (10 selecionado), contador com `aria-live="polite"`, seletor "Página" e botões de seta. Cada seta usa `<img src="assets/vendor/fontawesome-5.11.2/solid/chevron-left.svg" alt="">` ou o equivalente direito, com `aria-label` ("Página anterior" e "Próxima página").
  - Banner de limite, oculto por padrão.
  - Mensagem de busca sem resultado (D9), oculta por padrão.
  - Elemento de carregamento com `role="status"`, `aria-live="polite"` e texto "Carregando usuários". O spinner fica oculto por padrão através de `.table-loading-indicator[hidden]`. O `status-region` existente mantém o uso atual.
  - Botão `#new-user-button` preservado.
  - IDs novos, fixados aqui para G4: `users-table-search-toggle`, `users-table-search-field`, `users-table-search-input`, `users-table-search-close`, `users-table-chips`, `users-table-chip-template`, `users-table-menu-button`, `users-table-menu`, `users-table-menu-add`, `users-table-menu-sort-label`, `users-table-page-size`, `users-table-page`, `users-table-page-prev`, `users-table-page-next`, `users-table-counter`, `users-table-cap-banner`, `users-table-empty` e `users-table-loading` (spinner, R2).
  - Preservar todos os IDs e classes usados pelos testes: `users-table-title`, `users-table-body`, `table-card`, `new-user-button`, `status-region`, `user-dialog`, `user-form`, `user-dialog-title`, `user-dialog-error`, `user-dialog-close`, `user-dialog-cancel`, `user-name`, `user-email`, `user-location`, `user-image`, `image-preview`, `remove-image-option`, `remove-image`, `user-save-button`, `delete-dialog`, `delete-dialog-content`, `delete-dialog-message`, `delete-dialog-error`, `delete-dialog-cancel` e `delete-confirm-button`.
- **ACs cobertos.** Estrutura de AC-03, AC-07, AC-08, AC-09, AC-10 e AC-12.
- **Validação planejada.** `node --test webapp/frontend/tests/css-scanner.test.mjs` e `node --test webapp/frontend/tests/navigation.test.mjs` e `node --test webapp/frontend/tests/table-menu-stacking.test.mjs webapp/frontend/tests/table-search-close.test.mjs`. Conferir com `grep` que cada ID da lista de preservação aparece em `index.html`.
- **Depende de.** G1, porque usa classes e tokens definidos lá.
- **Commit.** `feat(webapp): add users table markup`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## G4 Controlador

- **Escopo.** Ligação de eventos, estado e renderização. Regras de busca, ordenação, limite e paginação ficam em `table-model.mjs`.
- **Alteração por revisão.** Este gate também alterou `webapp/frontend/index.html` (`users-table-loading` sem o atributo `hidden`) e `webapp/frontend/styles.css` (regra de zero espaço para a região de carregamento e regra `[hidden]` do spinner), por decisão de revisão. As alterações em `index.html` e `styles.css` já foram commitadas em 7f57c07; o commit atual deste gate altera apenas `webapp/frontend/app.js`, o novo arquivo de teste e este plano.
- M2 resolvido: qualquer fechamento do campo de busca limpa termos, chips e texto e restaura a lista completa (decisão do usuário, opção A).
- **Arquivos.** Principal: `webapp/frontend/app.js`. `webapp/frontend/index.html` e `webapp/frontend/styles.css` são exceção de revisão aprovada (ver "Alteração por revisão" acima).
- **Mudanças.**
  - Estado: `allUsers`, `terms`, `sort: { field, direction }`, `page` e `pageSize`. `sort.field` começa nulo (P6).
  - Painéis: usar um único estado `openPanel` (`null`, busca ou menu). Abrir busca fecha menu; abrir menu fecha busca. Abrir o menu com a busca aberta fecha e limpa a busca.
  - Carregamento: mantém `users-table-loading` e seu `role="status"` no DOM; altera só o texto e a visibilidade do spinner para anunciar "Carregando usuários". Embora G3 inicie o elemento com `hidden`, G4 não oculta a região; define `aria-busy="true"` no contêiner da tabela durante `api/users` e a renderização e mantém aria-busy false ao concluir (R2).
  - Busca: ao pressionar Enter, `parseSearchTerms` divide o texto. Cada termo novo vira chip, o campo é limpo e termos repetidos não são duplicados (P7).
  - Chips: criados com `textContent`. Remover um chip atualiza `terms` e devolve o foco a `users-table-search-input` (P5, REQ-03).
  - O botão de remoção define `aria-label` por chip como `Remover <termo>`; não reutiliza o valor estático `Remover termo` do template.
  - Lupa: abre `users-table-search-input`. O botão de fechar oculta o campo e devolve o foco à lupa e, ao fechar, limpa termos, chips e texto, restaurando a lista completa.
  - Menu: abre com clique, Enter ou Espaço no botão e atualiza `aria-expanded`. Escape ou clique fora fecha e devolve o foco ao botão. "Adicionar usuário" chama o mesmo handler de `#new-user-button`. Escolher coluna chama `cycleSort`, fecha o menu e devolve o foco ao botão.
  - Cabeçalhos: clique chama `cycleSort`. Atualiza `aria-sort` em todos os cabeçalhos ordenáveis e o estado dos triângulos dos cartões (REQ-08).
  - Cartões: `createUserRow` adiciona `.table-card-cell` às células e `.table-card-label-row` com rótulo (U+00A0) e indicador de ordenação com `aria-hidden="true"`.
  - Renderização: linhas criadas com `createElement` e `textContent`. Destaque com nós de texto e `<mark>`, nunca com `innerHTML` (REQ-04).
  - Paginação: `users-table-page-size` altera `pageSize` e volta para página 1 (P8). `users-table-page` e as setas alteram `page`.
    - Os valores de `<select>` para página e `pageSize` são strings; converta ambos com `Number()` antes de chamar `paginate`: página não numérica vira 1, e `pageSize` string gera `RangeError`.
  - Contador: `users-table-counter` mostra o texto de `counterText` a cada busca, ordenação ou mudança de página.
  - Limite: `users-table-cap-banner` aparece somente quando `filterAndCap` retorna `isCapped` (R1).
  - Vazio: `users-table-empty` aparece quando há termos e nenhuma linha corresponde (D9).
  - Após criar, editar ou excluir, recarrega `api/users`, mantém termos, ordenação e página e limita a página à última válida.
- **ACs cobertos.** AC-03, AC-04, AC-05, AC-07, AC-08, AC-09, AC-11 e AC-12.
- **Validação planejada.** `node --check webapp/frontend/app.js` e `node --test webapp/frontend/tests/*.test.mjs`.
- **Testes.** `webapp/frontend/tests/app-table-controller.test.mjs`: "waitForRenderFrame returns null when requestAnimationFrame is not a function"; "waitForRenderFrame resolves only after the second animation frame"; "failed users fetch shows the empty counter and the error status"; "lupa close clears terms, input text, and chips and restores the full list"; "X close clears terms, input text, and chips and restores the full list"; "opening the sort menu while search is open closes search and clears its terms"; "app.js selectors and sort fields exist in index.html"; "Escape closes the open menu, returns focus to its button, and keeps the current page"; "a click outside the open menu closes it and leaves the list unchanged"; "a second click on the ellipsis button closes the open menu"; "a render failure while closing search from the menu shows the error status"; "a render failure while closing search clears the chips before the table renders".
- **Depende de.** G2 e G3.
- **Commit.** `feat(webapp): wire users table controls`.
- Residual: reset do contador no erro de renderUsers (app.js, bloco catch de renderUsers) sem teste unitário; coberto manualmente em G5.
- Residual: requestAnimationFrame pausa em aba oculta; render e aria-busy permanecem até a aba voltar. Aceito, sem timer por decisão do gate.
- Residual: handlers de toggle da busca, botão X, Enter no campo de busca (onSearchInputKeydown), ordenação, paginação e chips sem try/catch; erros são apenas de DOM, sem I/O de rede; mesma classe do tratamento do menu (F4).

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## G5 Validação de navegador

- **Escopo.** Verificação de comportamento em navegador real, com a stack em execução em `http://localhost:8080/webapp/index.html`. Não altera código.
- **Arquivos.** Nenhum arquivo de código. Evidência em `.agent/memory/webapp-users-table-validation.md`, criada na execução e commitada com o gate.
- **Mudanças.** Nenhuma. Defeitos voltam ao gate dono (G1 a G4), são corrigidos lá e G5 é repetido.
- **Registro obrigatório.** Navegador, versão, ferramenta de automação usada de forma externa ao projeto, larguras e método de cada cenário. A ferramenta não entra como dependência do projeto.
- **Checklist planejado.**

  | Cenário | Larguras | ACs |
  |---|---|---|
  | Fluxo completo por teclado: busca, chips, menu, cabeçalhos e paginação | Maior ou igual a 1024 px e abaixo de 768 px | AC-03, AC-05, AC-07, AC-09 |
  | Busca encontra registro fora da página 1, com 11 ou mais registros | Maior ou igual a 1024 px | AC-01, AC-09 |
  | Remoção de chip restaura a lista e move o foco para o campo de busca | Maior ou igual a 1024 px | AC-03 |
  | Escolher Nome no menu três vezes produz ascendente, descendente e ascendente | Abaixo de 768 px | AC-05, AC-07 |
  | Banner de limite com 620 registros correspondentes, com `api/users` interceptada e registro do método | Maior ou igual a 1024 px | AC-11 |
  | Spinner durante `api/users` atrasada, com `aria-busy`, texto e reduced motion emulado | Maior ou igual a 1024 px | AC-12 |
  | Sem overflow horizontal da página, com `scrollWidth` menor ou igual a `clientWidth` | 768 px, 793 px e 794 px | AC-10 |
  | Triângulos somente em Nome, Email e Localização e destaque do cartão ativo | Abaixo de 768 px | AC-08, AC-10 |

- Conferir visualmente `.table-sort-button` e `.table-page-button` em 375, 768 e 1024 px; sem regra própria, herdam `.br-button` do core.
- Conferir o raio do cartão com `.table-search-field` aberta (`inset: 0` sobre `.top-bar`), com 0 e 1 linha.
- Em 375 px, medir `scrollWidth` com 0 e 1 linhas, tanto com busca aberta quanto com menu aberto.

- **ACs cobertos.** AC-03 a AC-12.
- **Depende de.** G4.
- **Commit.** `docs(agent): record users table browser validation`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## G6 Documentação

- **Escopo.** Documentação operacional e de design system. Não inclui relatórios de teste.
- **Arquivos.** `docs/recipes/govbr-design-system.md` e `docs/recipes/webapp-crud.md`.
- **Mudanças.**
  - `govbr-design-system.md`: registrar os desvios a a e, cada um com motivo, e apontar o contrato `webapp-users-table`.
  - `webapp-crud.md`: descrever somente o comportamento da tabela: campos de busca, termos com OR, frases entre aspas, chips, ordenação e menu, paginação de 10, 50 e 100, limite de 500 com banner e carregamento.
- **Regras.** Seguir `docsDevGuide`: índice `<details>` no início, retorno ao topo em cada seção de nível superior, português brasileiro e nenhum relatório de teste em `docs/recipes/`.
- **ACs cobertos.** Nenhum AC de código. Documenta os desvios a a e e o comportamento validado em G5.
- **Validação planejada.** Revisão manual de índice, âncoras e links relativos. `git --no-pager diff --name-only` mostra somente os dois arquivos.
- **Depende de.** G5.
- **Commit.** `docs(webapp): document users table behavior and deviations`.
- **Decisão do dono (G6).** A direção de ordenação aparece só nos cartões abaixo de 768 px. Nos cabeçalhos, o destaque usa cor e `aria-sort`. Aceito como está; implementar seta no cabeçalho exigiria mudança de contrato, CSS e nova validação G5.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Fora do escopo e riscos

- **Fora do escopo.** Alterações na API, no banco, na edição e exclusão de registros e novas dependências. Busca e ordenação no servidor.
- **Limite de 500.** Registros além do limite ficam invisíveis na lista. O banner informa o total real (R1).
- **Destaque com acentos.** A normalização NFD altera índices. AC-04 e os testes de G2 cobrem o mapeamento.
- **Dependência de ambiente.** G5 exige a stack em execução. Sem ela, G5 não é executado e não é declarado como validado.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Gate G5a: ajuste de chips e OBS-01

- **Objetivo.** Trocar o critério literal de t1 e t2 por critério medido, limitar a altura da área de chips em telas estreitas e resolver OBS-01 (painel de busca sobre o topo do primeiro cartão). O gate altera somente CSS e testes. Depois, a validação G5 completa é repetida sobre o commit do gate.
- **Decisões aprovadas pelo dono.**
  1. Critério de aceite de t1 e t2 = critério medido (REQ-13 e AC-13). Substitui o literal de D-04 apenas para aceite. O literal permanece registrado como FAIL histórico em `.agent/memory/webapp-users-table-validation.md` e não é apagado.
  2. Teto por breakpoint, opção B: até 480 px, `max-height` de 172 px na área de chips, com `overflow-y: auto`; acima de 480 px, mantém 120 px (REQ-14). Consequência: t2 aceita 172 ± 2 px até 480 px. Com três termos longos a 375 px, `scrollHeight` é maior que `clientHeight`: o conteúdo excede o teto de 172 px e a área rola (medição na memória, seção G5a).
  3. OBS-01 resolvido pela opção recomendada, somente até `max-width` de 793.98 px, o campo de busca aberto entra no fluxo normal, em linha própria abaixo dos controles, sem sobrepor cartões (REQ-14). A decisão 5 amplia esse comportamento a todas as larguras. Não sobrepõe o menu e não quebra D-01 (reticências e menu acessíveis com a busca aberta), D-02 (campo cresce em altura) nem D-03 (alinhamento do X). Descartada: reservar 89 px fixos abaixo de painel absoluto, porque não acompanha a altura variável dos chips. Sobreposição a partir de 794 px (t4 de 20,7 px em 794 px; caixas do cabeçalho com 4 chips): resolvida pela decisão 5.
  4. Critério de sobreposição com o menu (aceite do dono, G5a). A prova é a medição no estado alcançável pela UI: clique real nas reticências com a busca aberta fecha a busca, abre o menu e limpa termos e chips. Nas oito larguras medidas (375, 480, 481, 768, 793, 794, 1023 e 1024 px), a interseção entre o campo de busca e o menu é 0 px², e Nome, Email e Adicionar recebem o ponteiro com o menu aberto. A medição com menu forçado (rodada 1) fica como histórico. O limite de 793,98 px deixa de existir com a decisão 5.
  5. Reflow em todas as larguras (decisão do dono, G5a). Com a busca aberta, o campo entra no fluxo normal e em linha própria abaixo dos controles do cabeçalho em qualquer largura, sem `position: absolute` nesse estado. Esta decisão altera REQ-14 e AC-14. Exige CSS, testes de flow em todas as larguras e nova validação completa: G5 com checks a–w, medição de t1, t2, teto e reflow, D-01 com 4 chips e sobreposição zero entre campo, cartões e controles do cabeçalho, em 375, 480, 481, 768, 793, 794, 1023, 1024, 1280 e 1440 px. Tags: código em `gate/table-g5a-reflow-all-widths`; validação em `gate/table-g5-validation`.
- **Dependências.** G5 final (commit 9fc7ab2, FAIL histórico) e Revisão 2 de t1 e t2 em `.agent/memory/webapp-users-table-validation.md`. Contrato: REQ-13, REQ-14, AC-13 e AC-14.
- **Arquivos.**
  - Alterar: `webapp/frontend/styles.css`.
  - Criar: `webapp/frontend/tests/table-search-breakpoint.test.mjs` e `webapp/frontend/tests/table-search-flow.test.mjs`.
  - Criar, por decisão do Coordinator (dentro do escopo do G5a): `webapp/frontend/tests/helpers/css-cascade.mjs`, helper que resolve o valor de uma propriedade em uma largura sobre `helpers/css-scanner.mjs`, e `webapp/frontend/tests/css-cascade.test.mjs`, os testes desse helper.
  - `webapp/frontend/index.html`: não alterar por ora. Alterar somente se a marcação existente não permitir o reflow.
  - Não alterar `app.js`, `table-model.mjs`, `docs/`, `deploy/` nem `.github/`. A documentação do teto e do reflow fica para G6.
- **Alterações CSS.**
  - Teto: dentro de `@media (max-width: 480px)`, `.top-bar .table-search-chips` (`styles.css`, linha 507) recebe `max-height: 172px` e mantém `overflow-y: auto`. A regra-base `.table-search-chips` (linha 456) não muda e continua com o teto de 120 px calculado por tokens.
  - Reflow: `.top-bar .table-search-field` (linha 496) sai de `position: absolute` para `position: static` em todas as larguras, sem `@media`, e entra no fluxo normal com `flex: 0 0 100%`, em linha própria abaixo dos controles do cabeçalho. `top`, `right` e `left` vão para `auto` e `min-height` para `auto`. Em todas as larguras, `.top-bar:has(.table-search-field:not([hidden]))` (linha 491) recebe `flex-wrap: wrap`, para que o cabeçalho quebre só com o campo aberto. O padding direito de 64 px é mantido, porque `table-menu-stacking.test.mjs` lê esse valor; revisá-lo exige alterar esse teste e nova validação.
  - Sem alteração: regra-base, `z-index` de `.table-search-field` (2), de `.table-menu-anchor` (3) e de `.table-sort-menu` (1). Nenhum `order` por CSS (G3-R2).
- **Testes.**
  - `css-cascade.test.mjs` (novo), com CSS inline, testa o helper:
    - a regra mais específica vence a posterior menos específica, e em empate vence a posterior;
    - `max-width` em px vale até o limite inclusive: 480 px aplica, 481 px não;
    - rejeita com erro: `em`, `rem`, espaço antes de `)`, `or`, tipo de mídia (`print and`), feature que não é largura (`(hover: none) and`), segunda condição que não é px, e feature não-width depois de um prelúdio falso;
    - `calc` de tokens resolve para 120 px; soma de px com número sem unidade e mistura de px com rem são rejeitados; `var()` não declarado lança `ReferenceError`;
    - seletor-alvo: lista que contém o alvo lança; composto com `[hidden]` lança; descendente que termina no alvo casa; seletor cujo sujeito é outro elemento não casa;
    - nome de propriedade em maiúsculas casa; regra ambígua que declara a propriedade lança, e regra ambígua que declara outra propriedade não afeta o resultado;
    - `!important` em regra aplicável lança `SyntaxError` com a regra e o valor; seletor com `#` ou `*` que não casa e declara a propriedade lança `Error` com o seletor; `*` que declara só outra propriedade não afeta o resultado.
  - `table-search-breakpoint.test.mjs` (novo), lê `styles.css` pelo helper:
    - regra-base de `.table-search-chips` fora de `@media`: `max-height` resolve para 120 px pelos tokens do GOV.BR e `overflow-y` é `auto`;
    - em 375 e 480 px: `max-height` é 172 px e `overflow-y` é `auto`;
    - em 481, 768 e 1024 px: `max-height` resolve para 120 px e `overflow-y` é `auto`;
    - `172px` é declarado somente dentro de `@media (max-width: 480px)`.
  - `table-search-flow.test.mjs` (novo), lê `styles.css` pelo helper e `index.html`:
    - reflow: `position` do campo é `static` em todas as larguras (375 a 1440 px, incluindo 793 px e 794 px);
    - `flex` do campo é `0 0 100%` em todas as larguras;
    - `flex-wrap` de `.top-bar:has(.table-search-field:not([hidden]))` é `wrap` em todas as larguras; a regra `.top-bar` não declara `flex-wrap` nas larguras testadas;
    - `min-height` do campo não é 100% em nenhuma largura, e `height` é `auto` em todas as larguras, excluindo a regra de `#users-table-loading` (ver o item de posicionamento);
    - posicionamento: em `index.html`, `#users-table-loading` fica depois do fechamento de `.top-bar`, o que justifica a exclusão acima;
    - z-index: `.table-menu-anchor` (3) é maior que `.table-search-field` (2) em todas as larguras, e `.table-sort-menu` tem `z-index: 1` em 1024 px;
    - alinhamento: `align-items: center` no campo, `margin-bottom: 0` no input (D-03) e `flex: 0 0 auto` no botão X em todas as larguras;
    - marcação: título, toggle, `.table-menu-anchor`, campo, botão X e chips aparecem nessa ordem dentro de `.top-bar`.
  - Suíte completa: `node --test webapp/frontend/tests/*.test.mjs`, com todos os testes verdes, inclusive os três testes antigos.
  - Executar `node --test webapp/frontend/tests/css-scanner.test.mjs` e `node --test webapp/frontend/tests/navigation.test.mjs`. Complemento: `node --test webapp/frontend/tests/table-menu-stacking.test.mjs`, porque também lê `styles.css` e cobre z-index e padding do campo.
  - Os testes de CSS verificam declarações. Os critérios de medição ficam com a validação de navegador.
- **Validação no host (G5a).** Sobre o commit do código, na stack em `http://localhost:8080/webapp/index.html`:
  1. Testes da seção Testes, com resultado verde.
  2. Integridade: `styles.css`, `index.html` e `app.js` servidos com o mesmo SHA-256 (16 primeiros caracteres) do commit.
  3. G5 completo, checks a–w, nas larguras da decisão 5 (375, 480, 481, 768, 793, 794, 1023, 1024, 1280 e 1440 px). i e n seguem NOT RUN abaixo de 768 px (375, 480 e 481 px), por contrato: cabeçalhos ocultos em cartões.
  4. Remedição de t1, t2, teto e reflow com 4 termos longos em 375x812 (também com 3 termos), 480, 481, 768, 793, 794, 1023, 1024x768, 1280x800 e 1440x900; s, t3 e t4 pelo script de larguras extras (`extra-widths-10w.mjs`) nas mesmas dez larguras; t3 INFO nas dez larguras neste script, e critério de t3 (PASS) só em 375 px, no checklist (`checks-10w.mjs`, linha 1151). Em 375x812 com 3 termos, t2 espera rolagem com `clientHeight` de 172 px ± 2 px, porque o conteúdo excede o teto (AC-13).
  5. Sobreposição: em cada largura da remedição, com a busca aberta, a caixa de `.table-search-field` não intersecta `#users-table-body`, o primeiro cartão nem os controles do cabeçalho. Em 768 px, 793 px e 794 px, `scrollWidth` não excede `clientWidth` (AC-10). O valor de 793,98 px não é medível como viewport inteiro; 793 px e 794 px cobrem a faixa (decisão do dono).
  6. Limpeza: remover por ID somente os registros semeados, usando a lista de IDs da semeadura. Contar registros antes da semeadura e após a limpeza. Os registros que existiam antes da semeadura devem permanecer inalterados.
- **Registro.** A validação é registrada em nova seção de `.agent/memory/webapp-users-table-validation.md`, sem alterar as seções existentes. Evidência bruta fica fora do repositório, como nas rodadas anteriores.
- **Ordem e commits.**
  1. Commit de documentação deste contrato e plano: `docs(agent): record G5a chip breakpoint and reflow criteria` (`1923217`), sem tag.
  2. Commit do código: `fix(webapp): cap chip area by breakpoint and reflow open search` (`be84d8b`), com a tag `gate/table-g5a-chip-breakpoint`.
  3. Validação sobre o commit do código.
  4. Registro da validação G5a: não há commit com o assunto planejado; a seção `G5a (be84d8b)` entrou no commit `cd921f0`, sem tag (ver item 5).
  5. Commit de documentação da decisão 5 (reflow em todas as larguras): `cd921f0` (`docs(agent): extend users table search reflow to all widths`), sem tag.
  6. Commit de código da decisão 5: `7f55528` (`fix(webapp): keep open search field in normal flow at every width`), com a tag `gate/table-g5a-reflow-all-widths`. A validação G5 sobre este commit está na seção "G5 pós-reflow (7f55528)" de `.agent/memory/webapp-users-table-validation.md`.
- **ACs cobertos.** AC-13 e AC-14. A validação G5 completa reexecuta AC-03 a AC-12 sobre o commit do gate.
- **Depende de.** G5 final (9fc7ab2) e decisões 1 a 3 aprovadas pelo dono.
- **Riscos.**
  - O intervalo de 794 a 1023 px não tinha medição anterior. A remedição deve medi-lo. Se houver sobreposição nesse intervalo, o defeito volta a este gate e não é aceito por analogia com 793.98 px.
  - O teto de 172 px depende da altura medida de chips longos (48.7 px por linha). Chips de altura diferente mudam quantas linhas cabem. A remedição usa os termos longos da Revisão 2.
  - Com o campo em linha própria, o cabeçalho fica mais alto em todas as larguras e os cartões descem. A medição deve confirmar ausência de sobreposição e de rolagem horizontal da página.
- **Dívida registrada (fora do G5a).** Migrar `table-search-close.test.mjs`, `table-menu-stacking.test.mjs` e `navigation.test.mjs` para `css-cascade.mjs`. Estado: migração pendente. Os três leem `styles.css` e `index.html` com leitura própria e não importam `css-cascade.mjs`. Motivo: escopo; esses testes já passam e não devem ser editados neste gate.
- **Limites do helper `css-cascade.mjs` (registrados no G5a).**
  - Propriedades são comparadas por nome exato, sem expansão de shorthand ou longhand: `flex` não cobre `flex-basis`, e `max-block-size` não é normalizado para `max-height`.
  - `!important` em regra aplicável lança `SyntaxError`. A importância não é resolvida.
  - Ancestrais de seletores compostos não são verificados: o matcher confere só o sujeito, como em `.top-bar .table-search-field`.
  - Media queries aceitam somente `(min-width: Npx)` e `(max-width: Npx)` unidas por `and`. Qualquer outra forma lança `SyntaxError`.
  - `#`, `*` e `\` em seletor que declara a propriedade pedida lançam `Error` sempre, casando ou não o alvo. A especificidade do helper não conta `#`, portanto ela não é usada para ranquear esses casos.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
