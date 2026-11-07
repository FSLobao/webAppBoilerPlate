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
  - Search chip container next to search input; each chip uses GovBR Core `.br-button.small` modifier. Do not add a local `min-height`.
  - Botão de reticências (SVG inline original) com `aria-expanded="false"` e `aria-controls="users-table-menu"`. O menu tem "Adicionar usuário" e o grupo "Ordenar" com Nome, Email e Localização. O menu começa com `hidden`.
  - Cabeçalhos de Nome, Email e Localização com botão de ordenação e `aria-sort="none"`. Foto e Ações não recebem botão.
  - **G3-R1 Menu clipping.** G3 must prevent `.table-sort-menu` from being clipped by the existing `.table-card { overflow: hidden; }` in cards with 0 or 1 row. For example, allow overflow on the card and preserve rounded corners on its children. G5 must verify 0 and 1 rows at 375, 768, and 1024 px.
  - **G3-R2 Chip DOM order.** Place the remove control before the term text in the DOM. Its accessible name is `Remover <termo>`. Do not reorder with CSS.
  - Rodapé de paginação: seletor "Exibir" com 10, 50 e 100 (10 selecionado), contador com `aria-live="polite"`, seletor "Página" e botões de seta. Cada seta usa `<img src="assets/vendor/fontawesome-5.11.2/solid/chevron-left.svg" alt="">` ou o equivalente direito, com `aria-label` ("Página anterior" e "Próxima página").
  - Banner de limite, oculto por padrão.
  - Mensagem de busca sem resultado (D9), oculta por padrão.
  - Elemento de carregamento com `role="status"`, `aria-live="polite"` e texto "Carregando usuários". O spinner fica oculto por padrão através de `.table-loading-indicator[hidden]`. O `status-region` existente mantém o uso atual.
  - Botão `#new-user-button` preservado.
  - IDs novos, fixados aqui para G4: `users-table-search-toggle`, `users-table-search-field`, `users-table-search-input`, `users-table-search-close`, `users-table-chips`, `users-table-chip-template`, `users-table-menu-button`, `users-table-menu`, `users-table-menu-add`, `users-table-menu-sort-label`, `users-table-page-size`, `users-table-page`, `users-table-page-prev`, `users-table-page-next`, `users-table-counter`, `users-table-cap-banner`, `users-table-empty` e `users-table-loading` (spinner, R2).
  - Preservar todos os IDs e classes usados pelos testes: `users-table-title`, `users-table-body`, `table-card`, `new-user-button`, `status-region`, `user-dialog`, `user-form`, `user-dialog-title`, `user-dialog-error`, `user-dialog-close`, `user-dialog-cancel`, `user-name`, `user-email`, `user-location`, `user-image`, `image-preview`, `remove-image-option`, `remove-image`, `user-save-button`, `delete-dialog`, `delete-dialog-content`, `delete-dialog-message`, `delete-dialog-error`, `delete-dialog-cancel` e `delete-confirm-button`.
- **ACs cobertos.** Estrutura de AC-03, AC-07, AC-08, AC-09, AC-10 e AC-12.
- **Validação planejada.** `node --test webapp/frontend/tests/css-scanner.test.mjs` e `node --test webapp/frontend/tests/navigation.test.mjs`. Conferir com `grep` que cada ID da lista de preservação aparece em `index.html`.
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
- **Alteração por revisão.** Este gate também alterou `webapp/frontend/index.html` (`users-table-loading` sem o atributo `hidden`) e `webapp/frontend/styles.css` (regra de zero espaço para a região de carregamento e regra `[hidden]` do spinner), por decisão de revisão.
- M2 aberto: fechar pela lupa mantém termos e oculta chips; fechar pelo X limpa termos. Opções: A (qualquer fechamento limpa termos) ou B (painel permanece aberto enquanto houver termos). Decisão pendente do usuário.
- **Arquivos.** Principal: `webapp/frontend/app.js`. `webapp/frontend/index.html` e `webapp/frontend/styles.css` são exceção de revisão aprovada (ver "Alteração por revisão" acima).
- **Mudanças.**
  - Estado: `allUsers`, `terms`, `sort: { field, direction }`, `page` e `pageSize`. `sort.field` começa nulo (P6).
  - Painéis: usar um único estado `openPanel` (`null`, busca ou menu). Abrir busca fecha menu; abrir menu fecha busca.
  - Carregamento: mantém `users-table-loading` e seu `role="status"` no DOM; altera só o texto e a visibilidade do spinner para anunciar "Carregando usuários". Embora G3 inicie o elemento com `hidden`, G4 não oculta a região; define `aria-busy="true"` no contêiner da tabela durante `api/users` e a renderização e mantém aria-busy false ao concluir (R2).
  - Busca: ao pressionar Enter, `parseSearchTerms` divide o texto. Cada termo novo vira chip, o campo é limpo e termos repetidos não são duplicados (P7).
  - Chips: criados com `textContent`. Remover um chip atualiza `terms` e devolve o foco a `users-table-search-input` (P5, REQ-03).
  - O botão de remoção define `aria-label` por chip como `Remover <termo>`; não reutiliza o valor estático `Remover termo` do template.
  - Lupa: abre `users-table-search-input`. O botão de fechar oculta o campo e devolve o foco à lupa.
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
- **Depende de.** G2 e G3.
- **Commit.** `feat(webapp): wire users table controls`.
- Residual: sem teste unitário para waitForRenderFrame e para o reset do contador no erro; cobertura manual em G5.
- Residual: requestAnimationFrame pausa em aba oculta; render e aria-busy permanecem até a aba voltar. Aceito, sem timer por decisão do gate.

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
  | Sem overflow horizontal da página, com `scrollWidth` menor ou igual a `clientWidth` | 768 px e 793.98 px | AC-10 |
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
