<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#escopo">Escopo</a></li>
        <li><a href="#fonte">Fonte</a></li>
        <li><a href="#decisões-vinculantes">Decisões vinculantes</a></li>
        <li><a href="#requisitos-normativos">Requisitos normativos</a></li>
        <li><a href="#critérios-de-aceitação">Critérios de aceitação</a></li>
        <li><a href="#desvios-do-padrão">Desvios do padrão</a></li>
        <li><a href="#premissas-aceitas">Premissas aceitas</a></li>
    </ol>
</details>

# Contrato: tabela de usuários da webapp

## Escopo

Este contrato define o comportamento da tabela de usuários da SPA em `webapp/frontend/`: busca, ordenação, barra de paginação, responsividade, carregamento e ícones. A tabela carrega a lista completa de `api/users` e filtra, ordena e pagina no navegador.

Fora do escopo: edição de registros, alterações na API ou no banco e novas dependências. Os termos "deve" e "não deve" são normativos. O plano de execução está em [plano da tabela de usuários](../plans/webapp-users-table.md). Este contrato complementa o [plano CRUD da webapp](../plans/webapp-crud.md) e segue o [contrato de arquitetura](ARCHITECTURE.md).

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Fonte

| Item | Valor |
|---|---|
| Componente | gov.br Table, Padrão Digital de Governo - Componentes - Table |
| Seções usadas | Busca (6), Ordenação (9), Barra de Paginação, Responsividade (grade de 4 colunas com rolagem horizontal), Ícones de ordenação |
| Procedimento de reuso | [Design System gov.br](../../docs/recipes/govbr-design-system.md) |

Onde este contrato diverge da fonte, a seção [Desvios do padrão](#desvios-do-padrão) prevalece.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Decisões vinculantes

| ID | Decisão |
|---|---|
| D1 | Menu de ordenação em todas as larguras. O botão de reticências (Ellipsis-v) abre um menu com "Adicionar usuário" e o grupo "Ordenar", com Nome, Email e Localização. Escolher uma coluna equivale a clicar no cabeçalho dela: primeiro ascendente, depois descendente e, na terceira vez, ascendente. Abaixo de 768 px, a linha de rótulo de cada cartão mostra dois triângulos (para cima e para baixo) na mesma linha do rótulo, alinhados à direita, com a direção ativa destacada. Os triângulos não são interativos e recebem `aria-hidden="true"`. As palavras de cada rótulo são unidas por U+00A0. A linha de rótulo usa `display: flex` com `justify-content: space-between`. |
| D2 | Itens por página: 10, 50 e 100. Padrão: 10. |
| D3 | A busca cobre Nome, Email e Localização. O campo `id` é excluído. Valores numéricos e de data/hora são convertidos em texto antes da comparação. Campos ocultos não são pesquisados. |
| D4 | Termos separados por espaço são independentes e combinados com OR. Texto entre aspas é uma frase única, por exemplo `"Rio de Janeiro"`. Cada termo aceito vira um chip: botão pequeno com um "x" à esquerda que remove o termo. Trechos correspondentes são destacados com `<mark>` nas células. A comparação não diferencia maiúsculas de minúsculas nem acentos. |
| D5 | Ciclo de ordenação: ascendente, descendente, ascendente. Após o primeiro clique não existe estado "sem ordenação". |
| D6 | Campos ordenáveis: Nome, Email e Localização. Foto e Ações não são ordenáveis. A comparação usa `Intl.Collator("pt-BR", { numeric: true, sensitivity: "base" })`. Empates são desfeitos pelo `id`. |
| D7 | O botão externo "Novo usuário" (`#new-user-button`) permanece. A mesma ação "Adicionar usuário" também fica no menu Ellipsis-v. |
| D8 | O contador mostra somente o total filtrado, no formato "1-10 de N itens". Sem resultados, mostra "Nenhum item". |
| D9 | Mensagem de busca sem resultado: "Nenhum usuário encontrado para a busca informada." |
| R1 | Limite de 500 itens. O filtro roda sobre a lista completa da API. O limite de 500 aplica-se depois da filtragem. Quando o total filtrado passa de 500, o contador mostra o conjunto exibido ("1-10 de 500 itens") e um banner mostra "Exibindo 500 de N usuários encontrados. Refine sua busca aplicando filtros.", em que N é o total filtrado real. A paginação percorre a lista limitada. |
| R2 | Carregamento com spinner somente em CSS, sem SVG nem imagem. Enquanto `api/users` é buscada e a tabela é renderizada, a região exibe o texto visível "Carregando usuários" em elemento com `role="status"` e `aria-live="polite"`, e o contêiner da tabela tem `aria-busy="true"`. Com `prefers-reduced-motion: reduce`, o spinner não gira e usa pulsação lenta de opacidade. |
| Ícones | Lupa e reticências são SVG inline originais, desenhados com primitivas `circle` e `line`, sem cópia de nenhum conjunto de ícones. As setas da paginação reutilizam `chevron-left.svg` e `chevron-right.svg` vendorizados em `webapp/frontend/assets/vendor/fontawesome-5.11.2/solid/`. Não há downloads nem novas dependências. |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Requisitos normativos

| ID | Requisito | Origem |
|---|---|---|
| REQ-01 | O campo de busca deve pesquisar Nome, Email e Localização. O `id` e os campos ocultos não devem ser pesquisados. Valores numéricos e de data/hora devem ser convertidos em texto antes da comparação. | D3 |
| REQ-02 | Termos separados por espaço devem ser independentes e combinados com OR. Texto entre aspas deve ser tratado como uma frase única. | D4 |
| REQ-03 | Cada termo aceito deve aparecer como chip com botão "x" à esquerda, que remove o termo. Ao remover um chip, o foco deve voltar ao campo de busca. | D4, P5 |
| REQ-04 | Trechos correspondentes devem ser destacados com `<mark>` nas células. A comparação deve ignorar maiúsculas, minúsculas e acentos. O destaque deve ser montado com nós de texto, nunca com `innerHTML`. | D4 |
| REQ-05 | Nome, Email e Localização devem ser ordenáveis. Foto e Ações não devem ser ordenáveis. Cada acionamento de ordenação deve seguir o ciclo ascendente, descendente, ascendente, sem voltar a "sem ordenação". | D5, D6 |
| REQ-06 | A comparação deve usar `Intl.Collator("pt-BR", { numeric: true, sensitivity: "base" })`. Empates devem ser desfeitos pelo `id` em ordem crescente, em qualquer direção. | D6 |
| REQ-07 | O menu Ellipsis-v deve existir em todas as larguras e conter "Adicionar usuário" e o grupo "Ordenar" com Nome, Email e Localização. Escape deve fechar o menu e devolver o foco ao botão que o abriu. Lupa e reticências devem ser SVG inline originais. | D1, D7, Ícones, Desvio d |
| REQ-08 | Deve existir um único estado de ordenação, compartilhado por cabeçalhos, menu e triângulos dos cartões. Cabeçalhos devem expor `aria-sort`. A coluna ativa deve ser marcada visualmente e por estado ARIA no menu. | D1, P3 |
| REQ-09 | A paginação deve oferecer 10, 50 e 100 itens por página, com padrão 10. O contador deve mostrar somente o total filtrado. Sem resultados, o contador deve mostrar "Nenhum item" e a busca deve mostrar a mensagem de D9. As setas devem usar os chevrons vendorizados. | D2, D8, D9, Ícones |
| REQ-10 | Em largura de 768 px ou mais, a tabela deve usar a grade da fonte com rolagem horizontal contida no contêiner da tabela. Abaixo de 768 px, a tabela deve ser substituída por cartões com triângulos conforme D1. | Fonte (Responsividade), D1, Desvio a, Desvio b |
| REQ-11 | O limite de 500 itens deve ser aplicado após a filtragem, com contador e banner conforme R1. A paginação deve percorrer somente a lista limitada. | R1, Desvio c |
| REQ-12 | Enquanto `api/users` é buscada e a tabela é renderizada, deve existir spinner somente CSS com `role="status"`, `aria-live="polite"`, texto "Carregando usuários" e `aria-busy="true"` no contêiner da tabela. Com `prefers-reduced-motion: reduce`, o spinner não deve girar. | R2, Desvio e |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Critérios de aceitação

| ID | Critério verificável | Método | Requisito |
|---|---|---|---|
| AC-01 | `matchRow` encontra um termo presente em Nome, Email ou Localização. Um termo presente apenas no `id` ou em campo oculto não encontra a linha. `toSearchText` converte número e `Date` em texto pesquisável. | Teste unitário | REQ-01 |
| AC-02 | `parseSearchTerms('ana "Rio de Janeiro" silva')` retorna três termos, com `Rio de Janeiro` como termo único. Com dois termos aceitos, uma linha que contém apenas um deles aparece. | Teste unitário | REQ-02 |
| AC-03 | Cada termo aceito aparece como chip com "x" à esquerda do texto. Acionar o "x" remove o termo, refiltra a lista e move o foco para o campo de busca. | Teste de navegador (G5) | REQ-03 |
| AC-04 | Em célula com correspondência, o trecho casado fica dentro de `<mark>`. O termo "jose" destaca "José" e "RIO" destaca "rio". Intervalos sobrepostos viram um único `<mark>`. Nenhum valor de usuário é inserido com `innerHTML`. | Teste unitário de `findHighlightRanges` e inspeção do código (G4) | REQ-04 |
| AC-05 | Acionar o cabeçalho Nome três vezes produz ascendente, descendente e ascendente. Os cabeçalhos de Foto e Ações não contêm botão de ordenação. Nenhum acionamento volta a "sem ordenação". | Teste unitário de `cycleSort` e teste de navegador | REQ-05 |
| AC-06 | Com `sortRows` e o collator pt-BR, "Álvaro" vem antes de "Bruno", "Item 2" vem antes de "Item 10", e dois registros com o mesmo Nome aparecem em ordem crescente de `id` nas duas direções. | Teste unitário | REQ-06 |
| AC-07 | Em 375 px, 768 px e 1024 px, o botão de reticências é visível e abre um menu com "Adicionar usuário" e o grupo "Ordenar" com Nome, Email e Localização. Escape fecha o menu e devolve o foco ao botão. Lupa e reticências são `<svg>` inline com apenas `circle` e `line`, e nenhum arquivo SVG novo é adicionado. | Teste de navegador (G5) e inspeção do diff | REQ-07 |
| AC-08 | Após escolher Email no menu, o cabeçalho Email tem `aria-sort="ascending"`, Nome e Localização têm `aria-sort="none"`, o item Email do menu tem `aria-current="true"` e marcador visual, e, abaixo de 768 px, o triângulo ascendente do cartão Email fica destacado. | Teste de navegador (G5) | REQ-08 |
| AC-09 | O seletor "Exibir" oferece exatamente 10, 50 e 100, com 10 selecionado no carregamento. Com 120 registros filtrados e 10 por página, o seletor "Página" oferece 12 opções e o contador mostra "1-10 de 120 itens". Sem registros filtrados, o contador mostra "Nenhum item". | Teste unitário de `paginate` e `counterText` e teste de navegador | REQ-09 |
| AC-10 | Em 768 px e em 793.98 px, `document.documentElement.scrollWidth` não excede `clientWidth`. Abaixo de 768 px não há rolagem horizontal da página, e a tabela é substituída por cartões com triângulos somente em Nome, Email e Localização. | Teste de navegador (G5) | REQ-10 |
| AC-11 | Com 620 usuários correspondentes à busca, a lista exibida tem 500 itens, o contador da página 1 mostra "1-10 de 500 itens", o banner mostra "Exibindo 500 de 620 usuários encontrados. Refine sua busca aplicando filtros." e o seletor "Página" oferece 50 opções. Com 500 ou menos correspondências, o banner não aparece. | Teste unitário de `filterAndCap` e teste de navegador | REQ-11 |
| AC-12 | Durante a busca de `api/users`, o contêiner da tabela tem `aria-busy="true"` e o elemento `role="status"` com `aria-live="polite"` exibe "Carregando usuários". O spinner não contém `<img>` nem `<svg>`. Com `prefers-reduced-motion: reduce`, `getComputedStyle` não reporta a animação de rotação. | Teste de navegador com atraso de rede e inspeção de `styles.css` | REQ-12 |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Desvios do padrão

| ID | Desvio | Motivo |
|---|---|---|
| a | Abaixo de 768 px, cartões substituem a rolagem horizontal da fonte. | Decisão do usuário. |
| b | Dois triângulos (para cima e para baixo) em vez de uma única seta de ordenação. | Decisão do usuário. Mostra as duas direções e destaca a ativa. |
| c | Limite de 500 itens aplicado após a filtragem. | Limita a renderização no navegador sem reduzir a busca, que continua sobre a lista completa da API. |
| d | Menu de ordenação em todas as larguras, além do clique no cabeçalho. | Oferece ordenação por teclado e por toque em telas estreitas, onde o cabeçalho não aparece. |
| e | Spinner somente em CSS, sem SVG nem imagem. | Não adiciona asset nem dependência ao projeto. |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Premissas aceitas

Estas premissas valem até veto. P5, P6, P7 e P8 foram definidas neste contrato para completar o comportamento.

| ID | Premissa |
|---|---|
| P1 | Os triângulos dos cartões são não interativos. |
| P2 | O clique no cabeçalho em desktop mantém o comportamento atual, exceto pelo ciclo de D5. |
| P3 | O estado de ordenação é compartilhado por cabeçalho, menu e cartões. |
| P4 | O texto do contador sem resultados é "Nenhum item". |
| P5 | Ao remover um chip, o foco volta ao campo de busca. |
| P6 | Sem ordenação ativa, a ordem dos registros é a recebida de `api/users`. |
| P7 | Os termos são aceitos ao pressionar Enter no campo de busca. O texto é dividido por `parseSearchTerms`, cada termo vira um chip e o campo é limpo. Termo repetido não cria novo chip. |
| P8 | Ao mudar o seletor "Exibir", a página volta para 1. |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
