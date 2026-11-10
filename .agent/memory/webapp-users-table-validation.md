# Validação de navegador da tabela de usuários (G5)

Evidência do gate G5 do [plano da tabela de usuários](../plans/webapp-users-table.md), contra o [contrato](../contracts/webapp-users-table.md) (AC-03 a AC-12).

**Resultado geral: FAIL.** 1 defeito (D-01, severidade Média). As demais checagens passaram.

## Ambiente

| Item | Valor |
|---|---|
| Data | 2026-11-09 |
| Commit validado | 3b6aebc (tag gate/table-g4-controller) |
| Conferência do deploy | `app.js`, `table-model.mjs`, `styles.css` e `index.html` servidos têm o mesmo SHA-256 que no commit 3b6aebc |
| Host | rhel9host, Red Hat Enterprise Linux 9.8 (Plow) |
| URL | http://localhost:8080/webapp/index.html |
| Node.js | v24.21.0 |
| Automação | Playwright 1.65.0, externo ao projeto (pasta de sessão `g5-tools/`, sem dependência no repositório) |
| Navegador | Chromium 158.0.8127.18 (headless shell, cache do usuário). Playwright não reconheceu o RHEL e usou o build de fallback ubuntu24.04-x64 |
| Dados de teste | 520 usuários "Pessoa lote-g5 NNN" (`lote-g5-NNN@example.com`), "Zelia Teste G5" e "Adalberto Teste G5". Usado `example.com` porque a API recusa `.test` (422) |
| Limitação | Viewport do Playwright é inteiro: 793.98 px foi substituído por 793 px |
| Capturas e logs | `files/g5/` da sessão (fora do repositório) |

## Resultados

Valores medidos na execução 2. Método entre parênteses.

| ID | Verificação (método) | Viewport | Valor medido | Resultado | Captura |
|---|---|---|---|---|---|
| a | scrollWidth <= innerWidth; cartões abaixo de 768 px (DOM) | 375, 768, 793, 1024 | 375/375, 768/768, 793/793, 1024/1024; cartões só em 375 | PASS | a-layout-375x812.png, a-layout-768x1024.png, a-layout-793x1024.png, a-layout-1024x768.png |
| b | região ociosa (DOM) | 1024 | altura 0 px; texto vazio; spinner oculto | PASS | — |
| c | api/users atrasada 1500 ms (route) | 1024 | spinner visível; "Carregando usuários"; role=status; aria-live=polite; aria-busy true e depois false; img/svg 0 | PASS | c-spinner-loading-1024x768.png, c-loaded-1024x768.png |
| d | busca "Zelia" + Enter (teclado) | 1024 | 1 linha; "1-1 de 1 itens"; "Zelia Teste G5" presente | PASS | d-search-zelia-1024x768.png |
| d | botão X (clique) | 1024 | campo fechado; valor vazio; 0 chips; "1-10 de 500 itens"; 10 linhas | PASS | — |
| e | "lote-g5 zelia" (teclado) | 1024 | 2 chips; banner "Exibindo 500 de 521" (união 520 + 1); botão x antes do texto | PASS | e-chips-1024x768.png |
| e | "zelia adalberto" (teclado) | 1024 | 2 linhas; "1-2 de 2 itens" (união) | PASS | — |
| e | remover chip "lote-g5" (clique) | 1024 | 1 chip; "1-1 de 1 itens"; foco em #users-table-search-input | PASS | e-chip-removed-1024x768.png |
| f | <mark> após busca "Zelia" (DOM) | 1024 | 2 marks: "Zelia" em Nome e "zelia" em Email | PASS | f-highlight-1024x768.png |
| g | busca "lote-g5" (teclado) | 1024 | "1-10 de 500 itens"; banner visível com texto da AC-11 e N=520 | PASS | g-cap-banner-1024x768.png |
| g | Exibir 10/50/100 (seletor) | 1024 | páginas: 50 com 10 por página; 10 com 50; 5 com 100 | PASS | — |
| h | busca "zzz-nada-g5" (teclado) | 1024 | mensagem exata; contador "Nenhum item"; 0 linhas | PASS | h-empty-search-1024x768.png |
| i | clique 3x no cabeçalho Nome (clique) | 1024 | asc: Adalberto Teste G5; desc: Zelia Teste G5; asc: Adalberto. Páginas 1 e 2 (11-20) conferem com a ordem global | PASS | i-sort-header-1024x768.png |
| i | botões nos cabeçalhos (DOM) | 1024 | botões por th = [0,1,1,1,0] (só Nome, Email e Localização) | PASS | — |
| j | menu > Email (clique) | 1024 | aria-sort email=ascending, demais none; aria-current=true; menu fecha; foco no botão; 2º clique: descending | PASS | j-menu-active-email-1024x768.png |
| j | menu > Nome 3x (clique) | 375 | ascending, descending, ascending; classes is-ascending e is-descending | PASS | j-menu-sort-name-375x812.png |
| k | clique real em reticências com busca aberta (ponteiro) | 1024 | bloqueado: "intercepts pointer events" pelo botão X dentro de #users-table-search-field | FAIL | k-pointer-blocked-1024x768.png |
| k | Shift+Tab até reticências + Enter (teclado) | 1024 | campo fecha; valor vazio; 0 chips; "1-10 de 500 itens"; menu aberto | PASS | k-menu-after-search-keyboard-1024x768.png |
| l | Escape com foco num item do menu (teclado) | 375, 1024 | menu fecha; foco em #users-table-menu-button; aria-expanded=false | PASS | — |
| m | menu com 0 linhas, busca "zzz-nada-g5" (teclado) | 375 | retângulo [150,315,350,505] dentro da janela; sem recorte; scrollWidth 375 | PASS | m-menu-0-linha-375x812.png |
| m | menu com 1 linha, busca `"Zelia Teste G5"` (teclado) | 375 | retângulo [150,315,350,505]; sem recorte; scrollWidth 375 | PASS | m-menu-1-linha-375x812.png |
| m | 0 e 1 linha (teclado) | 768 | retângulo [511,283,711,473]; sem recorte; scrollWidth 768 | PASS | m-menu-0-linha-768x1024.png, m-menu-1-linha-768x1024.png |
| m | 0 e 1 linha (teclado) | 1024 | retângulo [767,283,967,473]; sem recorte; scrollWidth 1024 | PASS | m-menu-0-linha-1024x768.png, m-menu-1-linha-1024x768.png |
| n | Tab desde o início (teclado) | 1024 | ordem: lupa > reticências > Nome > Email > Localização; Enter na lupa abre a busca e foca o campo | PASS | n-keyboard-search-open-1024x768.png |
| o | prefers-reduced-motion (emulação) | 1024 | reduce: table-loading-pulse; no-preference: table-loading-rotate | PASS | — |
| p | Exibir 50, depois página 2 (seletor) | 1024 | "1-50 de 500 itens"; "51-100 de 500 itens"; 50 linhas; primeira "Pessoa lote-g5 049" | PASS | — |
| q | rótulos de cartão após ordenar por Nome (menu) | 375 | rótulo flex, space-between, aria-hidden=true, 0 botões; Nome is-ascending; cor ativa rgb(12, 50, 111) e inativa rgb(136, 136, 136) | PASS | q-card-triangles-375x812.png |

Erros de JavaScript na página (`pageerror`): 0 em todas as execuções.

Com 0 ou 1 linha, o menu é medido com a renderização segurada por script de teste (init script, sem alterar o app). Na UI, abrir o menu limpa a busca após dois frames. Portanto, o estado estável "0/1 linha com menu aberto" não é alcançável pela UI.

## Defeitos

| ID | Severidade | Check | Descrição | Retorno |
|---|---|---|---|---|
| D-01 | Média | k | Com o campo de busca aberto, `.table-search-field` (`position: absolute; inset: 0; z-index: 2`) cobre toda a `.top-bar`, inclusive o botão de reticências. Em 375, 768 e 1024 px, os 9 pontos de amostragem do botão caem no campo. O caminho "abrir o menu" da D4 funciona só por teclado ou após fechar a busca com X. | Gate G3 (CSS) ou decisão sobre D4 |

Execução 1 (`results-run1.json`): f e m falharam por erro do harness (comparação com maiúsculas e variável errada), e k foi interrompido pelo D-01 (timeout no clique). Corrigidos e repetidos na execução 2. Não houve outro defeito de aplicação.

## Limpeza

- Antes da execução 2: 524 registros (2 pré-existentes + 522 G5). Após: 2 (user1 e user2, intactos).
- Remoções: 522 `DELETE`, todas com status 204. Registros G5 restantes: 0 (`cleanup.log`).
- Execução 1 também limpa: 524 para 2 (`cleanup-run1.log`).

## Não verificado

- Cap com 620 registros (AC-11 do plano): usados 520 e união de 521. Não foi interceptada a API com 620 registros.
- 793.98 px exato (usado 793 px).
- Destaque com acentos (ex.: "jose" em "José"), busca por data e Localização: não testados no navegador. Cobertos apenas por testes unitários do G2, não executados aqui.
- Erro de rede em api/users (mensagem "Não foi possível carregar os usuários.").
- Só Chromium. Sem Firefox ou WebKit.
- Toque real (`hasTouch`) não testado. Teclado em 375 px não testado.
- Triângulos: alinhamento à direita checado por classes, cores e display, não por pixel.
- Troca de "Exibir" a partir da página 2 (P8) não testada.
- Testes unitários (AC-01, AC-02, AC-04 a AC-06) fora do escopo deste G5.

## Reexecução após correção D-01 (commit 83e17b4)

Reexecução dos checks a a u contra o commit 83e17b4 (tag `gate/table-d01-menu-access`), com os mesmos ids e viewports desta evidência. Os checks r, s, t e u são novos.

**Resultado geral: FAIL.** D-01 está resolvido. Há um defeito novo, D-02 (severidade Média, check t, 375 px). Os checks i e n ficam NOT RUN em 375 px por contrato.

| Item | Valor |
|---|---|
| Data | 2026-11-09 |
| Commit validado | 83e17b4 (tag gate/table-d01-menu-access). `styles.css` servido tem o MD5 do arquivo do repositório e contém `table-menu-anchor` |
| Host | rhel9host, Red Hat Enterprise Linux 9.8 |
| Ferramentas | Node.js v24.21.0; Playwright 1.65.0 (externo ao projeto, `g5-tools/`); Chromium 158.0.8127.18 headless, sem reinstalação |
| Dados | 522 registros G5: 520 "Pessoa lote-g5 NNN", "Zelia Teste G5" e "Adalberto Teste G5". `zelia.g5@example.test` retornou 422; usado `example.com`. Adalberto semeado como antes (e e i dependem dele) |
| Capturas e logs | `files/g5/rerun-83e17b4/` (fora do repositório): `seed.log`, `checks.log`, `results.json`, `cleanup.log`, `seeded-ids.txt` |

| ID | Verificação | Viewport (px) | Valor medido | Resultado | Captura |
|---|---|---|---|---|---|
| a | scrollWidth <= innerWidth; cartões abaixo de 768 px | 375, 768, 793, 1024 | 375/375 (cartões); 768/768, 793/793 e 1024/1024 (grade) | PASS | a-layout-375x812, -768x1024, -793x1024, -1024x768 (.png) |
| b | região ociosa sem texto e com altura 0 | 375, 768, 793, 1024 | altura 0 px; texto vazio; spinner oculto (4/4) | PASS | — |
| c | spinner com api/users atrasada 1500 ms | 375, 768, 793, 1024 | role=status; aria-live=polite; aria-busy true e depois false; img/svg 0 (4/4) | PASS | c-spinner-loading-1024x768.png, c-loaded-1024x768.png (último, 1024) |
| d | busca "Zelia" + Enter; X limpa e restaura | 375, 768, 793, 1024 | 1 linha, "1-1 de 1 itens"; após X: 0 chips, "1-10 de 500 itens", 10 linhas | PASS | d-search-zelia-1024x768.png (último, 1024) |
| e | "lote-g5 zelia" (2 chips); "zelia adalberto"; remover chip | 375, 768, 793, 1024 | banner "Exibindo 500 de 521"; 2 linhas "1-2 de 2 itens"; 1 chip, "1-1 de 1 itens", foco no campo | PASS | e-chips-1024x768.png, e-chip-removed-1024x768.png (último, 1024) |
| f | `<mark>` em "Zelia" | 375, 768, 793, 1024 | 2 marks: "Zelia" (Nome) e "zelia" (Email) | PASS | f-highlight-1024x768.png (último, 1024) |
| g | busca "lote-g5": contador e banner; Exibir 10/50/100 | 375, 768, 793, 1024 | "1-10 de 500 itens"; banner com N=520; páginas 50/10/5 | PASS | g-cap-banner-1024x768.png (último, 1024) |
| h | busca sem resultado | 375, 768, 793, 1024 | mensagem exata; "Nenhum item"; 0 linhas | PASS | h-empty-search-1024x768.png (último, 1024) |
| i | Nome três vezes pelo cabeçalho | 768, 793, 1024; 375 NOT RUN | ascending, descending, ascending; página 1 conforme API; botões por th [0,1,1,1,0]; 375: cabeçalhos ocultos | PASS / NOT RUN | i-sort-header-1024x768.png (último, 1024) |
| j | menu > Email; menu > Nome três vezes (375) | 375, 768, 793, 1024 | Email ascending, demais none, aria-current=true, menu fecha, foco no botão; Nome: asc, desc, asc | PASS | j-menu-active-email-1024x768.png (último, 1024); j-menu-sort-name-375x812.png |
| k | clique real nas reticências com busca aberta | 375, 768, 793, 1024 | menu abriu nas 4 larguras; sem interceptação | PASS | k-pointer-blocked-1024x768.png (último, 1024; mostra menu aberto) |
| l | Escape fecha o menu e devolve foco | 375, 768, 793, 1024 | menu fechado; foco #users-table-menu-button; aria-expanded=false | PASS | — |
| m | menu com 0 e 1 linha, clique real | 375, 768, 793, 1024 | retângulo [L,T,R,B]: 375 [150,315,350,505]; 768 [511,283,711,473]; 793 [536,283,736,473]; 1024 [767,283,967,473]; sem recorte; scrollWidth = innerWidth | PASS | m-search-/m-menu-{0,1}-linha-{375x812,768x1024,793x1024,1024x768}.png |
| n | Tab: lupa, reticências, cabeçalhos; Enter na lupa | 768, 793, 1024; 375 NOT RUN | ordem lupa@3 < reticências@4 < Nome@5 < Email@6 < Localização@7; Enter abre e foca o campo | PASS / NOT RUN | n-keyboard-search-open-1024x768.png |
| o | prefers-reduced-motion | 375, 768, 793, 1024 | reduce: table-loading-pulse; no-preference: table-loading-rotate | PASS | — |
| p | Exibir 50, depois página 2 | 375, 768, 793, 1024 | "1-50 de 500 itens"; "51-100 de 500 itens"; 50 linhas; primeira "Pessoa lote-g5 049" | PASS | — |
| q | triângulos em cartões; linha de rótulos oculta em tabela | 375, 768, 793, 1024 | 375: Nome is-ascending, cor ativa rgb(12, 50, 111), inativa rgb(136, 136, 136), 0 botões; 768 a 1024: display none (3/3) | PASS | q-card-triangles-375x812.png |
| r | ponteiro nas reticências com busca aberta ("Zelia" + Enter) | 375, 768, 1024 | antes: 1 chip, 1 linha; centro do botão em #circle (dentro do botão); depois: menu aberto, aria-expanded=true, campo fechado, valor vazio, 0 chips | PASS | r-ellipsis-pointer-{375x812,768x1024,1024x768}.png |
| s | termos longos: fechar, campo e chips | 375 | 4 chips; fechar 40.0 px; campo de texto 80.0 px (limites exatos); chips [105, 254] dentro de [9, 366]; estouro 0 px | PASS | s-long-chips-375x812.png |
| t | base dos chips não passa do topo de #users-table-body | 375 | base dos chips 415.4 px; topo do corpo 343.0 px; sobreposição 72.4 px | FAIL (D-02) | s-long-chips-375x812.png |
| u | menu por ponteiro com 0 e 1 linha: janela e recorte | 375, 768, 1024 | 375 com 0 linhas [150,315,350,505] fora do .table-card, dentro da janela; demais dentro do card; sem recorte | PASS | u-menu-{0,1}-linha-{375x812,768x1024,1024x768}.png |

| ID | Severidade | Check | Descrição | Retorno |
|---|---|---|---|---|
| D-01 | Média | k, r, u | Resolvido neste commit: reticências clicáveis com busca aberta em 375, 768, 793 e 1024 px. | — |
| D-02 | Média | t (375 px) | Quatro termos longos fazem os chips transbordar o campo nos dois sentidos: vão de 169 a 415.4 px, enquanto o campo fica em 263 a 323 px. Sobrepõem visualmente o botão "Novo usuário" (166 a 206 px; teste de ponto no centro não bloqueado) e 72.4 px do corpo da tabela (topo em 343 px). Sem perda de dados. | Gate G3 (CSS de `.table-search-field` e `.table-search-chips`); repetir G5 |

**Limpeza.** Antes: 524 registros (2 pré-existentes + 522 G5). Depois: 2 (user1 e user2, intactos). Remoções: 522 `DELETE`, todas com status 204. Registros G5 restantes: 0 (`cleanup.log`).

**Observações (não são defeitos).**

- u, 375 px, 0 linhas: o menu (base em 505 px) passa da borda do `.table-card`. Continua dentro da janela e sem recorte, então atende ao critério "ou a janela".
- Capturas com nome fixo (c, d, e, f, g, h, i, j, k, n) guardam a última execução (1024 px). As de 375, 768 e 793 px foram sobrescritas.
- Com o render segurado (m, u), a região de carregamento mostra "Carregando usuários" até o render liberar. É efeito do harness.
- Diagnóstico de D-02 executado após a limpeza, sem dados e somente leitura. Script removido.

**Não verificado.**

- Toque real (`hasTouch`), dispositivo físico, Firefox e WebKit.
- Cap de 620 resultados (AC-11): usados 520 e união de 521.
- 793.98 px exato: usado 793 px inteiro.
- Sobreposição de chips em 768 e 1024 px: t só em 375 px.
- Teclado em 375 px (i e n NOT RUN) e ordenação por teclado em cartões.
- Erro de rede em api/users, acentos, busca por data e por Localização.

## Reexecução após D-02 opção A (commit c153083)

Reexecução dos checks a a w contra o commit c153083 (tag `gate/table-d02-chips-layout`), com os ids e viewports da reexecução D-01. O check t anterior foi substituído por t1 a t4. Os checks v e w são novos.

**Resultado geral: FAIL.** Critérios de chips atendidos (t1 na parte visível, t2, s). Defeito novo D-03 (severidade Baixa, check t3, 375 px). t4 é informativo. i e n ficam NOT RUN em 375 px por contrato.

| Item | Valor |
|---|---|
| Data | 2026-11-09 |
| Commit validado | c153083 (tag gate/table-d02-chips-layout). HEAD confirmado. `styles.css`, `index.html` e `app.js` servidos têm o mesmo SHA-256 do repositório (16 primeiros caracteres). `styles.css` contém `table-search-chips` |
| Host | rhel9host, Red Hat Enterprise Linux 9.8 |
| URL | http://localhost:8080/webapp/index.html |
| Ferramentas | Node.js v24.21.0; Playwright 1.65.0 (externo ao projeto, `g5-tools/`); Chromium 158.0.8127.18 headless (lançamento confirmado) |
| Dados | 522 registros G5: 520 "Pessoa lote-g5 NNN" (`lote-g5-NNN@example.com`), "Zelia Teste G5" (`zelia.g5@example.com`) e "Adalberto Teste G5". `.test` retorna 422, por isso `example.com` |
| Evidência | `files/g5/rerun-c153083/` (fora do repositório): `seed.log`, `checks.log`, `results.json`, `cleanup.log`, `cleanup-run.log`, `seeded-ids.txt`, `diag-t3-375x812.log`, `diag-novo-usuario-375x812.log` e capturas |

| ID | Verificação | Viewport (px) | Valor medido | Resultado | Captura |
|---|---|---|---|---|---|
| a | scrollWidth <= innerWidth; cartões abaixo de 768 px | 375, 768, 793, 1024 | 375/375 cartões; 768/768, 793/793 e 1024/1024 grade | PASS | a-layout-{375x812,768x1024,793x1024,1024x768}.png |
| b | região ociosa com altura 0 | 375, 768, 793, 1024 | altura 0 px; texto vazio; spinner oculto (4/4) | PASS | — |
| c | spinner com api/users atrasada 1500 ms | 375, 768, 793, 1024 | role=status; aria-live=polite; aria-busy true e depois false; img/svg 0 (4/4) | PASS | c-spinner-loading-1024x768.png, c-loaded-1024x768.png (último) |
| d | busca "Zelia" + Enter; X limpa e restaura | 375, 768, 793, 1024 | 1 linha, "1-1 de 1 itens"; após X: 0 chips, "1-10 de 500 itens", 10 linhas | PASS | d-search-zelia-1024x768.png (último) |
| e | "lote-g5 zelia" (2 chips); "zelia adalberto"; remover chip | 375, 768, 793, 1024 | banner "Exibindo 500 de 521"; 2 linhas "1-2 de 2 itens"; 1 chip, "1-1 de 1 itens", foco no campo | PASS | e-chips-1024x768.png, e-chip-removed-1024x768.png (último) |
| f | `<mark>` em "Zelia" | 375, 768, 793, 1024 | 2 marks: "Zelia" (Nome) e "zelia" (Email) | PASS | f-highlight-1024x768.png (último) |
| g | busca "lote-g5": contador e banner; Exibir 10/50/100 | 375, 768, 793, 1024 | "1-10 de 500 itens"; banner com N=520; páginas 50/10/5 | PASS | g-cap-banner-1024x768.png (último) |
| h | busca sem resultado | 375, 768, 793, 1024 | mensagem exata; "Nenhum item"; 0 linhas | PASS | h-empty-search-1024x768.png (último) |
| i | Nome três vezes pelo cabeçalho | 768, 793, 1024; 375 NOT RUN | asc, desc, asc; página 1 conforme API; botões por th [0,1,1,1,0]. 375: cabeçalhos ocultos em cartões | PASS; NOT RUN | i-sort-header-1024x768.png (último) |
| j | menu > Email; menu > Nome três vezes | 375, 768, 793, 1024 | Email ascendente, aria-current, menu fecha, foco no botão; Nome asc, desc, asc (375) | PASS | j-menu-active-email-1024x768.png, j-menu-sort-name-375x812.png |
| k | clique real nas reticências com busca aberta | 375, 768, 793, 1024 | menu abriu nas 4 larguras | PASS | k-pointer-blocked-1024x768.png (nome herdado) |
| l | Escape com menu aberto | 375, 768, 793, 1024 | menu fecha; foco em #users-table-menu-button; aria-expanded=false | PASS | — |
| m | menu com 0 e 1 linha, clique real | 375, 768, 793, 1024 | retângulo [L,T,R,B]: 375 [150,315,350,505]; 768 [511,283,711,473]; 793 [536,283,736,473]; 1024 [767,283,967,473]; sem recorte | PASS | m-search-/m-menu-{0,1}-linha-{vp}.png |
| n | Tab: lupa, reticências, cabeçalhos; Enter na lupa | 768, 793, 1024; 375 NOT RUN | lupa@3 < reticências@4 < Nome@5 < Email@6 < Localização@7; Enter abre e foca o campo | PASS; NOT RUN | n-keyboard-search-open-1024x768.png (último) |
| o | prefers-reduced-motion | 375, 768, 793, 1024 | reduce: table-loading-pulse; no-preference: table-loading-rotate | PASS | — |
| p | Exibir 50; página 2 | 375, 768, 793, 1024 | "1-50 de 500 itens"; "51-100 de 500 itens"; 50 linhas; primeira "Pessoa lote-g5 049" | PASS | — |
| q | rótulos e triângulos | 375; 768, 793, 1024 | 375: Nome is-ascending, cor ativa rgb(12, 50, 111), inativa rgb(136, 136, 136), 0 botões; 768 a 1024: display none (3/3) | PASS | q-card-triangles-375x812.png |
| r | ponteiro nas reticências com busca aberta | 375, 768, 1024 | antes: 1 chip, centro no botão (#circle); depois: menu aberto, aria-expanded=true, campo fechado, valor vazio, 0 chips | PASS | r-ellipsis-pointer-{375x812,768x1024,1024x768}.png |
| s | 4 termos longos: fechar, campo, chips | 375 | fechar 40.0 px; campo de texto 237.0 px; chips [17.0, 302.0] em campo [9.0, 366.0]; estouro 0 px | PASS | s-long-chips-375x812.png |
| t1 | chips dentro do campo (tolerância 1 px) | 375 | parte visível (3 de 4 chips): estouro 0.0 px. Literal, com o chip rolado: 32.0 px (nota A) | PASS (visível); nota A | s-long-chips-375x812.png |
| t2 | área de chips rola após ~3 linhas | 375 | clientHeight 120 px; max-height 120px; overflow-y auto; scrollHeight 161 px; box-sizing border-box | PASS | s-long-chips-375x812.png |
| t3 | campo de texto e X na primeira linha (tolerância 2 px); X >= 40 px | 375 | topo do campo 266.5 px; topo do X 262.7 px; diferença 3.8 px; largura do X 40.0 px | FAIL (D-03) | s-long-chips-375x812.png |
| t4 | INFORMATIVO: sobreposição campo × corpo | 375 | base do campo 431.7 px; topo do corpo 343.0 px; sobreposição 88.7 px | INFO | s-long-chips-375x812.png |
| u | menu por ponteiro com 0 e 1 linha | 375, 768, 1024 | 375/0 linhas: [150,315,350,505], fora do .table-card e dentro da janela; demais dentro do card; sem recorte | PASS | u-menu-{0,1}-linha-{375x812,768x1024,1024x768}.png |
| v | foco por teclado: X, depois 1º remover chip; contorno não cortado | 375 | Tab 1 = X; Tab 2 = 1º remover; contorno solid 3px, offset 3px; margens esq/topo/dir/base 10.00 / 5.83 / 255.00 / 77.83 px; mínima 5.83 px | PASS | v-focus-chip-375x812.png |
| w | ordem de Tab = ordem visual: campo, X, 1º remover | 375, 768, 793, 1024 | Tab 1 = X; Tab 2 = 1º remover; X à direita do campo; chips abaixo do X (4/4) | PASS | w-focus-order-{375x812,768x1024,793x1024,1024x768}.png |

**Defeitos**

| ID | Severidade | Check | Descrição | Retorno |
|---|---|---|---|---|
| D-03 | Baixa | t3 (375 px) | Topo do campo de texto 3.8 px abaixo do topo do X (limite 2 px). Diagnóstico somente leitura, campo vazio: campo com 28.3 px de altura, X com 40 px; topos com diferença de 3.84 px; centros com 2.01 px. Sem impacto funcional. | Gate G3 (CSS de `.table-search-input` ou `.table-search-close`), ou decisão do dono do contrato sobre a tolerância |

- D-02 resolvido nos critérios de chips (t1 visível, t2, s). Botão "Novo usuário" termina em 205.7 px; campo começa em 262.7 px (sem sobreposição, diagnóstico somente leitura, 375 px). A sobreposição com o corpo (t4, 88.7 px) é informativa.
- Nota A (t1): o chip 4 fica rolado para fora da área visível, 32.0 px abaixo da base do campo. Não aparece na tela. Pelo critério literal ("todos os chips"), t1 seria FAIL. Decisão do dono do contrato.
- Totais: 104 PASS, 1 FAIL (t3), 1 INFO (t4), 2 NOT RUN (i e n em 375 px). `pageerror`: 0.
- Capturas com nome fixo (c, d, e, f, g, h, i, j, k, n) guardam a última execução (1024 px).

**Limpeza.** Antes: 524 registros (2 pré-existentes + 522 G5). Depois: 2 (user1 e user2). Remoções: 522 `DELETE`, todas com status 204. GET após a limpeza: `lote-g5` 0, `zelia` 0, `adalberto` 0 (`cleanup.log`).

**Não verificado.**

- Toque real (`hasTouch`), dispositivo físico, Firefox e WebKit.
- Cap de 620 resultados (AC-11): usados 520 e união de 521.
- 793.98 px exato: usado 793 px inteiro.
- Erro de rede em api/users, acentos, busca por data e por Localização.
- Teclado em 375 px para i e n (NOT RUN por contrato). v e w cobrem só o foco do X e dos chips em 375 px.
- Alinhamento dos chips e triângulos medido por classe, cor e display, não por pixel.

## G5 final (commit 9fc7ab2)

Reexecução dos checks a a w contra o commit 9fc7ab2 (tag `gate/table-d03-field-alignment`), em 375, 768, 793 e 1024 px. Os critérios de t1 a t4, u, v e w são os da rodada final. i e n a 375 px continuam NOT RUN por contrato.

**Resultado geral: FAIL.** D-03 resolvido (t3 PASS). Defeito D-04 (Baixa, t1 a 375 px). t2 falha pelo critério literal em 768, 793 e 1024 px, sem defeito de aplicação. t4 é informativo.

- Data: 2026-11-09. Commit: 9fc7ab2 (HEAD). `styles.css`, `index.html` e `app.js` servidos têm o mesmo SHA-256 do HEAD (16 primeiros caracteres). `styles.css` contém `margin-bottom: 0` em `.table-search-input`.
- Host: rhel9host, Red Hat Enterprise Linux 9.8. URL: http://localhost:8080/webapp/index.html
- Ferramentas: Node.js v24.21.0; Playwright 1.65.0 (externo, pasta `g5-tools/`); Chromium 158.0.8127.18 headless, lançamento confirmado.
- Dados: 2 pré-existentes (user1, id 6; user2, id 7). Semeados 522: 520 "Pessoa lote-g5 NNN" (`lote-g5-NNN@example.com`), "Zelia Teste G5" (`zelia.g5@example.com`) e "Adalberto Teste G5" (`adalberto.g5@example.com`). Adalberto não estava na lista da fase de semeadura; e e i dependem dele.
- Evidência: `files/g5/final-9fc7ab2/` (fora do repositório): `seed.log`, `checks.log`, `results.json`, `cleanup.log`, `cleanup-run.log`, `seeded-ids.txt` e capturas.
- Viewports da tabela: 4 = 375x812, 768x1024, 793x1024, 1024x768. Capturas com `{vp}` seguem esse rótulo.

| ID | Verificação | Viewports | Valor medido | Resultado | Captura |
|---|---|---|---|---|---|
| a | scrollWidth <= innerWidth; cartões abaixo de 768 px | 4 | 375/375, 768/768, 793/793, 1024/1024; cartões só em 375 | PASS | a-layout-{vp}.png |
| b | região ociosa com altura 0 | 4 | altura 0 px; texto vazio; spinner oculto | PASS | — |
| c | spinner com api/users atrasada 1500 ms | 4 | role=status; aria-live=polite; aria-busy true e depois false | PASS | c-spinner-loading-{vp}.png |
| d | busca "Zelia" + Enter; X limpa e restaura | 4 | 1 linha, "1-1 de 1 itens"; após X: 0 chips, "1-10 de 500 itens" | PASS | d-search-zelia-{vp}.png |
| e | "lote-g5 zelia" (2 chips); "zelia adalberto"; remover chip | 4 | banner "Exibindo 500 de 521"; 2 linhas; 1 chip, foco no campo | PASS | e-chips-{vp}.png |
| f | `<mark>` em "Zelia" | 4 | 2 marks: "Zelia" (Nome) e "zelia" (Email) | PASS | f-highlight-{vp}.png |
| g | busca "lote-g5": contador, banner; Exibir 10/50/100 | 4 | "1-10 de 500 itens"; banner N=520; páginas 50/10/5 | PASS | g-cap-banner-{vp}.png |
| h | busca sem resultado | 4 | mensagem exata; "Nenhum item"; 0 linhas | PASS | h-empty-search-{vp}.png |
| i | Nome três vezes pelo cabeçalho | 768, 793, 1024; 375 NOT RUN | asc, desc, asc; página 2 "11-20 de 500 itens"; botões por th [0,1,1,1,0] | PASS; NOT RUN | i-sort-header-{vp}.png |
| j | menu > Email; menu > Nome três vezes | 4 (Nome 3x em 375) | Email ascendente, aria-current; Nome asc, desc, asc | PASS | j-menu-active-email-{vp}.png; j-menu-sort-name-375x812.png |
| k | clique real nas reticências com busca aberta | 4 | menu abriu nas 4 larguras | PASS | k-pointer-blocked-{vp}.png |
| l | Escape com menu aberto | 4 | menu fecha; foco no botão; aria-expanded=false | PASS | — |
| m | menu com 0 e 1 linha (clique real) | 4 | 375 [150,315,350,505]; 768 [511,283,711,473]; 793 [536,283,736,473]; 1024 [767,283,967,473]; sem recorte | PASS | m-menu-{0,1}-linha-{vp}.png |
| n | Tab: lupa, reticências, cabeçalhos; Enter na lupa | 768, 793, 1024; 375 NOT RUN | lupa@3 < reticências@4 < Nome@5 < Email@6 < Localização@7; Enter abre e foca o campo | PASS; NOT RUN | n-keyboard-search-open-{vp}.png |
| o | prefers-reduced-motion | 4 | reduce: table-loading-pulse; no-preference: table-loading-rotate | PASS | — |
| p | Exibir 50; página 2 | 4 | "1-50 de 500 itens"; "51-100 de 500 itens"; 50 linhas | PASS | — |
| q | rótulos e triângulos | 4 | 375: Nome ativo, rgb(12, 50, 111), 0 botões; 768 a 1024: display none | PASS | q-card-triangles-375x812.png |
| r | ponteiro nas reticências com busca aberta | 375, 768, 1024 | menu abre; campo fecha; 0 chips; aria-expanded=true | PASS | r-ellipsis-pointer-{vp}.png |
| s | 4 termos longos: fechar, campo, chips | 4 | 375: fechar 40.0 px; campo 237.0 px; chips [17, 302] em [9, 366]; estouro 0 px | PASS | s-long-chips-{vp}.png |
| t1 | todos os chips (inclusive rolados) dentro do retângulo do campo (1 px) | 4 | 375: estouro máximo 32.0 px (visível 0.0 px); 768, 793, 1024: 0.0 px | FAIL (375); PASS (demais) | s-long-chips-{vp}.png |
| t2 | clientHeight ~120; max-height 120px; overflow-y auto; scrollHeight > clientHeight | 4 | 375: 120/161 px; 768: 120/120; 793: 120/120; 1024: 84/84 | PASS (375); FAIL literal (768, 793, 1024) | s-long-chips-{vp}.png |
| t3 | centro do campo = centro do X (1 px); topo do X = topo do campo (1 px) | 375 (demais NOT RUN) | 375: diferença de centro 0.01 px; topo do X menos topo do campo 0.00 px | PASS | s-long-chips-375x812.png |
| t4 | INFORMATIVO: base do campo × topo do corpo | 4 | 375: 88.7 px; 768 e 793: 20.7 px; 1024: 0.0 px | INFO | s-long-chips-{vp}.png |
| u | menu por ponteiro com 0 e 1 linha: janela e recorte | 375, 768, 1024 | 375/0 linhas [150,315,350,505] fora do .table-card, dentro da janela; demais dentro do card; sem recorte | PASS | u-menu-{0,1}-linha-{vp}.png |
| v | foco por teclado: X, depois 1º remover; contorno +6 px dentro do contêiner | 375 (demais NOT RUN) | Tab 1 = X; Tab 2 = 1º remover; margens esq/topo/dir/base 10.00 / 5.83 / 255.00 / 77.83 px | PASS | v-focus-chip-375x812.png |
| w | ordem de Tab: campo, X, 1º remover | 4 | Tab 1 = X; Tab 2 = 1º remover; X à direita do campo; chips abaixo do X | PASS | w-focus-order-{vp}.png |

Desvios de método: `checks.mjs`, `seed.mjs` e `cleanup.mjs` passaram a aceitar `G5_DIR`. Capturas de 1024 px levam o rótulo da largura real. t1, t2 e s rodam nas 4 larguras; t3 e v só em 375 px, como definido. Antes da semeadura, havia 0 registros G5.

| ID | Severidade | Check | Descrição | Retorno |
|---|---|---|---|---|
| D-04 | Baixa | t1 (375) | Quarto chip, rolado para fora da área visível, fica 32.0 px abaixo do retângulo do campo. Estouro visível: 0.0 px. Pelo critério literal, FAIL. | Decisão sobre o critério (área visível ou retângulo literal) ou ajuste no G3 |
| OBS-01 | Média (sugerida; fora do veredito) | t4 (375, 768, 793) | Com chips longos, o painel de busca cobre o topo do primeiro cartão (88.7 px a 375; 20.7 px a 768 e 793). Ver `s-long-chips-375x812.png` | Decisão de layout no G3 |

Não é defeito: t2 em 768, 793 e 1024 px falha porque o conteúdo cabe em 120 px e não há rolagem. Sugerido limitar t2 a 375 px no critério.

**Limpeza.** Antes: 524 registros (2 pré-existentes + 522 G5). Remoções: 522 `DELETE`, todas com status 204. Depois: 2 (user1 e user2, intactos). GET após a limpeza: `lote-g5` 0, `zelia` 0, `adalberto` 0. Os 522 IDs de `seeded-ids.txt` retornam 404.

**Não verificado.**

- Toque real, dispositivo físico, Firefox e WebKit.
- Cap de 620 resultados (AC-11): usados 520 e união de 521.
- 793.98 px exato: usado 793 px inteiro.
- Erro de rede em api/users, acentos, busca por data e Localização.
- Cabeçalhos e teclado em 375 px (i e n, NOT RUN); v e t3 fora de 375 px (NOT RUN por critério); u e r em 793 px (fora do critério).

**Veredito geral: FAIL.** Pendências: decidir D-04 (critério t1 ou ajuste de G3), escopo do critério t2 e a OBS-01 de layout. D-03 fechado.

## Revisão de critérios t1 e t2 (commit 9fc7ab2)

Reexecução somente de medição, sem seed nem delete. Data: 2026-11-09. Script: `g5-tools/recheck-9fc7ab2.mjs`. Evidência: `files/g5/recheck-9fc7ab2/` (fora do repositório): `results.json`, `recheck.log` e 4 capturas. HEAD 9fc7ab2; `styles.css` servido igual ao working tree e com `margin-bottom: 0`. Usuários antes e depois: 2 (GET). `pageerror`: 0.

Critérios corrigidos:
- t1: parte visível de cada chip = retângulo ∩ caixa de borda do contêiner de chips (recorte de rolagem). Estouro visível = máx(0, parte visível fora do retângulo do campo), em px. PASS se <= 1 px.
- t2: linhas = valores distintos de topo dos chips. Linhas <= 3: scrollHeight = clientHeight. Linhas > 3: scrollHeight > clientHeight e clientHeight ≈ 120 px.

Medição com 4 chips longos em cada largura:

| Viewport | Estouro visível (t1) | Linhas (topo / centro) | clientHeight | scrollHeight | max-height | t2 |
|---|---|---|---|---|---|---|
| 375x812 | 0.00 px (3 visíveis) | 4 / 4 | 120 | 223 | 120px | PASS (rolagem esperada) |
| 768x1024 | 0.00 px | 4 / 4 | 120 | 156 | 120px | PASS (rolagem esperada) |
| 793x1024 | 0.00 px | 4 / 4 | 120 | 156 | 120px | PASS (rolagem esperada) |
| 1024x768 | 0.00 px | 2 / 2 | 84 | 84 | 120px | PASS (sem rolagem) |

Estouro literal (retângulo bruto, só informativo): 93.75 px a 375; 27.00 px a 768 e 793; 0.00 px a 1024. Em 768 e 793 o chip 4 mostra cerca de 4 px na base da área.

t3 (informativo, 4 larguras): centro do campo × centro do X 0.01 px; topo do X menos topo do campo 0.00 px; topo do campo de texto 5.84 px abaixo do topo do X (campo 28.30 px, X 40 px; centralizado).

Vereditos:
- t1: PASS (4 larguras).
- t2: PASS (4 larguras).
- D-04: erro de critério, não defeito de produto. O chip rolado para fora fica recortado pelo contêiner (`overflow-y: auto`). A parte visível de todos os chips fica dentro do campo (0.00 px), e o contêiner está inteiro dentro do campo nas 4 larguras. O critério literal media geometria não renderizada, cujo valor muda conforme o chip rolado.

Não medido: estado rolado até o fim; visibilidade da barra de rolagem (não aparece na captura de 375 px); toque real; outros navegadores.

## Revisão 2 de t1 e t2 (commit 9fc7ab2)

Status: aguardando aprovação do dono para a troca de critério de t1 e t2; a validação literal da G5 final (FAIL, D-04) permanece registrada e não foi apagada.

Reexecução somente de medição, sem seed, POST, PUT ou DELETE. Data: 2026-11-09. Script: `g5-tools/recheck-9fc7ab2.mjs`, ferramenta descartável de validação, sem testes unitários; sai com código 1 se algum caso tiver `error` ou a contagem final for nula. Evidência desta rodada: `files/g5/recheck-9fc7ab2/run2/` (fora do repositório): `results.json`, `recheck.log`, 5 capturas. A pasta raiz `files/g5/recheck-9fc7ab2/` guarda a rodada da revisão 2 antes deste reparo (medidas idênticas a run2); `rev1/` guarda a rodada anterior à revisão 2, gerada por versão antiga do script (sem `criteria`, `terms`, `scrollTop` nem linha de navegador). HEAD 9fc7ab2; `styles.css` com `margin-bottom: 0`. Usuários antes e depois: 2 (GET). pageerror: 0. Navegador: Chromium 158.0.8127.18 (headless); Node v24.21.0.

Correção à seção anterior: o script não rola os chips (`scrollTop` = 0 em todas as medições). A diferença entre execuções vem dos termos, não da posição de rolagem.

Termos usados: 375x812, 768x1024, 793x1024 e 1024x768 com "lote-g5-termo-longo-numero-um", "zelia-teste-g5-nome-muito-comprido", "adalberto-termo-com-muitas-letras-para-quebrar" e "termo-quatro-sem-espaco-nenhum-x"; 375x812 com 3 termos, os três primeiros dessa lista.

Critérios como implementados:
- t1: parte visível de cada chip = retângulo ∩ caixa de borda do contêiner (recorte de rolagem; `getBoundingClientRect`). Estouro visível = máx(0; parte visível fora do retângulo do campo). PASS se <= 1 px, chips = termos enviados e contêiner dentro do campo. Bordas do contêiner: `borderTop` e `borderBottom` = 0, então a caixa de borda é igual à de padding.
- t2: linhas = valores distintos de topo dos chips (tolerância 1 px). Chips de alturas diferentes na mesma linha contariam como linhas distintas; nas 5 medições, linhas pelo centro coincidem com as do topo. Plano, G3, D-02, linha 148: "a área de chips rola após cerca de três linhas". Sem rolagem se linhas <= 3; com rolagem se linhas > 3. PASS se max-height = 120px, overflow-y = auto, chips = termos e estado de rolagem igual ao esperado (sem: scrollHeight = clientHeight; com: scrollHeight > clientHeight e clientHeight = 120 ± 2 px).
- Contêiner no campo: caixa de borda do contêiner dentro da caixa de borda do campo (1 px).
- t3 (informativo, sem veredito): centro do campo de texto × centro do X; topo do X × topo do campo.

| Caso | Termos | Linhas | clientHeight | scrollHeight | scrollTop | Estouro visível (t1) | Contêiner no campo | t2 | t1 |
|---|---|---|---|---|---|---|---|---|---|
| 375x812 | 4 | 4 | 120 | 223 | 0 | 0.00 px | sim | PASS (rola, esperado rolar) | PASS |
| 768x1024 | 4 | 4 | 120 | 156 | 0 | 0.00 px | sim | PASS (rola, esperado rolar) | PASS |
| 793x1024 | 4 | 4 | 120 | 156 | 0 | 0.00 px | sim | PASS (rola, esperado rolar) | PASS |
| 1024x768 | 4 | 2 | 84 | 84 | 0 | 0.00 px | sim | PASS (sem rolagem, esperado sem) | PASS |
| 375x812 | 3 | 3 | 120 | 170 | 0 | 0.00 px | sim | FAIL (esperado sem rolagem; medido com rolagem) | PASS |

Todas as medições: max-height 120px e overflow-y auto; chips = termos enviados; após fechar, chips 0 e usuários 2. Estouro literal (informativo): 93.75, 27.00, 27.00, 0.00 e 41.06 px.

t3 (info, sem veredito), 5 medições: centro input–X 0.01 px; topo do X – topo do campo 0.00 px; topo do X – topo do input −5.84 px.

Vereditos:
- t1 e contêiner dentro do campo: PASS nas 5 medições.
- t2: PASS em 4 casos; FAIL em 375x812 com 3 termos.
- Caso de 3 linhas (375x812): rola. Três linhas de 48.7 px somam 154.06 px; com 16 px de padding, scrollHeight = 170 contra o teto de 120 px. A 3ª linha fica com 6.6 px visíveis (430.67 − 424.05). Pela regra escrita (plano, linha 148), a área não deve rolar em três linhas: FAIL. Leitura alternativa ("rola só se o conteúdo passar de 120 px") daria PASS; não é a do plano e não foi adotada. Causa: o teto de 120 px vem de `webapp/frontend/styles.css`, linhas 465 e 466 (comentário: "três linhas de chips pequenos (32 px)"). Uma linha de chips longos mede 48.7 px (tops 318.67, 371.36, 424.05, 476.73); duas linhas cabem (117.4 px com padding) e a terceira não. A regra conta linhas de qualquer altura.

Em aberto (não decidido):
- OBS-01: painel de busca sobre o topo do primeiro cartão. Não remedido nesta revisão.
- Pergunta de produto: a 375 px, "rola após cerca de três linhas" e o teto de 120 px não cabem juntos com chips de duas linhas (3 linhas = 154.06 px). Opções: teto, regra de t2 ou layout dos chips. Não decidido; decisão do dono.

Não medido: rolagem até o fim; barra de rolagem visível; toque real; outros navegadores; 3 termos em outras larguras; override `G5_DIR` por env; saída 1 em caso de erro (caminho não exercitado).

## G5a (be84d8b)

Data: 2026-11-09. HEAD be84d8b, tag `gate/table-g5a-chip-breakpoint`. `styles.css` servido com sha256 igual ao de `/var/lib/webapp-src/be84d8b`. Health 200. Usuários: 524 antes da limpeza (`recheck-g5a.log`: antes=524, depois=524, pois a limpeza veio depois) e 2 após a limpeza (`cleanup.log`: count_after=2; base sem dados G5: user1 e user2). Navegador: Chromium 158.0.8127.18 (headless), Playwright 1.65.0. Evidência: `files/g5/g5a-be84d8b/` (fora do repositório). Scripts: `g5-tools/checks.mjs`, `g5-tools/recheck-g5a.mjs` (novo), `g5-tools/seed.mjs`, `g5-tools/cleanup.mjs`, `g5-tools/etapa-a-menu.mjs` (Etapa A), `g5-tools/ac10-fraction.mjs` (Etapa C).

Critérios de aceite (REQ-13 e REQ-14; o literal de D-04 não entra no aceite):
- t1: estouro visível de cada chip (parte do retângulo dentro do recorte do contêiner e fora do campo) <= 1 px; contêiner dentro do campo (tolerância 1 px).
- t2: linhas contadas pelo topo (tolerância 1 px). A área excede o teto quando scrollHeight é maior que clientHeight (o teto inclui o padding); nesse caso, clientHeight fica dentro de ±2 px do teto; senão, scrollHeight = clientHeight. `overflow-y: auto`.
- Teto: 172 px até 480 px; 120 px acima de 480 px (computado).
- Reflow: até 793.98 px, campo em fluxo, abaixo dos controles, sem interseção com corpo nem menu; a partir de 794 px, `position: absolute`.

Fonte única desta tabela: `recheck-g5a.json` (e `recheck-g5a.log`), gerado por `g5-tools/recheck-g5a.mjs`. Termos de cada linha: 4 termos longos = `lote-g5-termo-longo-numero-um`, `zelia-teste-g5-nome-muito-comprido`, `adalberto-termo-com-muitas-letras-para-quebrar`, `termo-quatro-sem-espaco-nenhum-x`; 375x812 (3 termos) = os três primeiros. A `results.json` da G5 final (`final-9fc7ab2`) e os itens de `checks.mjs` usam `LONG_CHIP_QUERY` (2 curtos e 2 longos: `lote-g5`, `zelia`, `lote-g5x-longtermo-com-muitas-letras-para-quebrar-linha`, `zelia-outro-termo-longo`). Não comparar esses valores com a tabela abaixo sem esse rótulo.

Medição (4 termos, exceto indicado):

| Caso | Linhas | clientHeight / scrollHeight | max-height | Estouro visível | position | ∩ menu (px²) | t1 · t2 · teto · reflow |
|---|---|---|---|---|---|---|---|
| 375x812 | 4 | 172 / 247 | 172px | 0.00 px | static | 0 | PASS · PASS · PASS · PASS |
| 375x812 (3 termos) | 3 | 172 / 194 | 172px | 0.00 px | static | 0 | PASS · PASS · PASS · PASS |
| 480x800 | 4 | 172 / 173 | 172px | 0.00 px | static | 0 | PASS · PASS · PASS · PASS |
| 481x800 | 4 | 120 / 173 | 120px | 0.00 px | static | 0 | PASS · PASS · PASS · PASS |
| 768x1024 | 4 | 120 / 156 | 120px | 0.00 px | static | 0 | PASS · PASS · PASS · PASS |
| 793x1024 | 4 | 120 / 156 | 120px | 0.00 px | static | 0 | PASS · PASS · PASS · PASS |
| 794x1024 | 4 | 120 / 156 | 120px | 0.00 px | absolute | 0 | PASS · PASS · PASS · PASS |
| 1023x768 | 2 | 84 / 84 | 120px | 0.00 px | absolute | 0 | PASS · PASS · PASS · PASS |
| 1024x768 | 2 | 84 / 84 | 120px | 0.00 px | absolute | 0 | PASS · PASS · PASS · PASS |

Nota: ∩ corpo não é medido nesta tabela. Com chips visíveis, rowCount é 0 e bodyOverlap é 0 por construção, então a coluna não prova sobreposição com cartões. O valor de corpo em 794 px é t4 = 20,7 px (subseção Larguras extras). ∩ menu é 0 por construção, porque o menu fica oculto nesta medição; a prova do estado alcançável está no item A desta seção.

Contêiner dentro do campo: contorno fora do campo 0.00 px em todos os casos. Estouro literal (informativo, sem aceite): 66.09 px (375x812), 13.41 px (375x812, 3 termos), 0 (480), 43.69 (481), 27.00 (768, 793, 794), 0 (1023, 1024).

Vereditos:
- t1: PASS (9 casos).
- t2: PASS (9 casos). Em 480x800, o conteúdo (173 px) passa 1 px do teto; clientHeight 172.
- Teto: PASS (172 px até 480 px; 120 px acima; `overflow-y: auto` em todos).
- Reflow: PASS. Até 793 px, campo `static` com topo igual à base dos controles (0.0 px). Em 794 px ou mais, `absolute`.
- AC-13, texto literal (375x812, 3 termos, `scrollHeight = clientHeight`): FAIL. A premissa de "cerca de 170 px" não se confirma: medido 194 px de scrollHeight, acima do clientHeight de 172 px (o teto inclui 8 px de padding em cima e embaixo, por CSS). Pela regra REQ-13 aplicada a esse conteúdo, t2 é PASS (rola com clientHeight 172). Decisão do dono (G5a, 1): AC-13 corrigido para o comportamento medido no contrato. Esta decisão não altera CSS.

Itens a–w (`checks.mjs`; totais: PASS 110, FAIL 4, NÃO EXECUTADO 5, INFO 4):
- PASS em todas as larguras aplicáveis: a, b, c, d, e, f, g, h, j, k, l, m, o, p, q, s, w.
- i: PASS em 768, 793 e 1024; NÃO EXECUTADO em 375 (cabeçalhos ocultos em cartões; ordenação em cartões coberta pelo menu, j, 375 px). n: PASS em 768, 793 e 1024; NÃO EXECUTADO em 375 (lupa e reticências são cobertas por d, k e r (ponteiro); Enter por teclado na lupa não medido).
- r e u: PASS em 375, 768 e 1024; v: PASS em 375 (escopo do script).
- t (sub-itens de s): t1 literal PASS ×4; t2 literal FAIL ×4 (375: 120 esperado, clientHeight 172 (teto computado), scrollHeight 194; results.json da G5 final mede clientHeight 120 e scrollHeight 161 sob outro conjunto de termos; 768 e 793: 120 px sem rolagem; 1024: 84 px sem rolagem). FAIL histórico, substituído por REQ-13. t3 PASS em 375 (centro 0.01 px; topo 0.00 px); NÃO EXECUTADO em 768/793/1024 (motivo: critério de t3 é informativo e foi definido só para 375). t4 INFO (sobreposição 0.0 px).

OBS-01 (busca aberta, campo × primeiro cartão): 0 px² em 375 e 768, sem termos (10 cartões) e com 1 termo "zelia" (375: campo 314.7–411.7 px, cartão em 440.0 px; 768: campo 282.6–379.6 px, cartão em 479.9 px). Com 4 termos não há cartão.

D-01 (375x812, 4 termos): as reticências recebem o clique com a busca aberta (hit em descendente do botão). O clique abre o menu e fecha a busca (chips 0). Itens Nome, Email e Adicionar usuário recebem o ponteiro; clique em Nome fecha o menu. PASS.

D-03 (informativo, 375x812): topo do X = topo do campo (Δ 0.00 px); centro do X e centro do campo de texto diferem 0.01 px; X 40 × 40 px; campo de texto 5.84 px abaixo do topo do X. D-02: campo 41.0 px (vazio) e 221.0 px (4 termos).

Limpeza: X fecha a busca em todos os casos (chips 0). `cleanup.mjs`: 522 removidos (204 em todos). GET final: 2 (ids 6 e 7). pageerror: 0 (checks e recheck).

Nota de método, reflow: a medição de reflow feita antes (rodada 1, `recheck-g5a-run1.*`) usou menu forçado e falhou (reflow FAIL). Essa geometria é diagnóstico e não é alcançável na UI: o menu fecha o painel de forma síncrona; a lista é renderizada após waitForRenderFrame. Sobreposição forçada: 38059 px² (375 e 480), 33800 (481–793), 24200 (794), 17000 (1023–1024). Essa rodada fica como histórico; a prova atual é a do item A (estado alcançável, interseção 0 px²). A aceitação do critério de sobreposição com o menu foi decidida pelo dono (G5a, decisão 4 do plano): a prova do estado alcançável é o critério.

Não medido: Firefox, WebKit, toque real, barra de rolagem visível, rolagem até o fim (scrollTop 0 em todas as medições), 3 termos fora de 375 px, sobreposição visual do menu com o campo (inalcançável).

Etapa A (D-01, opção B): prova do estado alcançável do menu. Script `g5-tools/etapa-a-menu.mjs`; saída `etapa-a-menu.json` e `etapa-a-menu.log`. Em cada largura: a lupa abre a busca (clique real); um chip "zelia" é criado com Enter; o texto "adal" fica no campo sem Enter. Caminho ponteiro: clique real nas reticências. Caminho teclado (contexto novo): o foco sai do campo (blur) e Tab avança a partir dele (X, remover chip, demais controles, depois `#new-user-button`, `#users-table-search-toggle` e `#users-table-menu-button`; 18 Tabs) e depois Enter. O estado "no mesmo instante" do clique é lido por listener de janela (fase de borbulhamento, após o handler do app), no mesmo despacho. Nenhum usuário criado.

- Resultado: PASS nas 8 larguras (375x812, 480x800, 481x800, 768x1024, 793x1024, 794x1024, 1023x768, 1024x768) para: lupa abre; busca fecha; valor do input vazio; chips 0; menu visível; hit test Nome, Email e Adicionar com alvo próprio ou descendente; interseção campo × menu 0 px²; teclado (alcança reticências, fecha busca, valor vazio, chips 0, menu visível).
- Antes do clique (busca aberta, 1 chip, texto "adal"): campo top/altura = 314.7/97.0 px (375, 480, 481); 282.6/97.0 (768, 793); 234.6/97.0 (794, 1023, 1024). Menu oculto, retângulo zero.
- Campo × `#users-table-body` com busca aberta e sem menu: 0 px² nas larguras medidas com 1 chip. Cartões intersectados: 0 de 10 (sem chip) e 0 de 1 (1 chip), em 375 e 480 e nas demais larguras medidas.
- No instante do clique, a lista ainda mostra a seleção anterior (`1-1 de 1 itens`, aria-busy=true); depois, `1-10 de 500 itens`, aria-busy=false.
- Capturas: `etapa-a-375x812-busca-aberta.png`, `etapa-a-375x812-menu-aberto.png`, `etapa-a-793x1024-busca-aberta.png`, `etapa-a-793x1024-menu-aberto.png`.

Etapa B: testes e arquivos.

- `node --test` em `webapp/frontend/tests/*.test.mjs`: 187 testes; 187 pass; 0 fail; 0 cancelados; duration_ms 506.09. Arquivo: `node-test.tap`.
- SHA256, servido (`http://localhost:8080/webapp/<arquivo>`) × stage (`/var/lib/webapp-src/be84d8b/webapp/frontend/<arquivo>`): iguais em `styles.css` (919b818290869d9baa3407ec48f872a17ac5c7076efc3886233ef5be71eafe43), `index.html` (cb6c2509465272ef843cbafb1dce7c0b8f2561fa8a29a31c63b061681609758f) e `app.js` (afaa147e7d0697552ef930f4ad3e2e82255a559136705abd7cf43b9a1642186d).

Etapa C: cobertura por largura e AC-10 em 793.98 px.

`checks.mjs` reexecutado com a mesma versão do repositório (`etapa-c-checks/checks.log`, `results.json`): PASS 110, FAIL 4, NÃO EXECUTADO 5, INFO 4; pageErrors 0. Itens s, t3 e t4:

| Largura | s | t3 | t4 |
|---|---|---|---|
| 375x812 | EXECUTADO, PASS | EXECUTADO, PASS (centro 0.01 px; topo 0.00 px) | EXECUTADO, INFO (0.0 px) |
| 480x800 | NÃO EXECUTADO (checks.mjs não cobre esta largura) | NÃO EXECUTADO (idem) | NÃO EXECUTADO (idem) |
| 481x800 | NÃO EXECUTADO (checks.mjs não cobre esta largura) | NÃO EXECUTADO (idem) | NÃO EXECUTADO (idem) |
| 768x1024 | EXECUTADO, PASS | NÃO EXECUTADO (critério de t3 é informativo e foi definido só para 375) | EXECUTADO, INFO (0.0 px) |
| 793x1024 | EXECUTADO, PASS | NÃO EXECUTADO (critério de t3 é informativo e foi definido só para 375) | EXECUTADO, INFO (0.0 px) |
| 794x1024 | NÃO EXECUTADO (checks.mjs não cobre esta largura) | NÃO EXECUTADO (idem) | NÃO EXECUTADO (idem) |
| 1023x768 | NÃO EXECUTADO (checks.mjs não cobre esta largura) | NÃO EXECUTADO (idem) | NÃO EXECUTADO (idem) |
| 1024x768 | EXECUTADO, PASS | NÃO EXECUTADO (critério de t3 é informativo e foi definido só para 375) | EXECUTADO, INFO (0.0 px) |

- t1 PASS nas 4 larguras cobertas (estouro 0.0 px).
- t2 com a regra literal de 120 px: FAIL nas 4 larguras cobertas. 375: clientHeight 161, scrollHeight 161, max-height 172 (LONG_CHIP_QUERY). 768 e 793: clientHeight 120 sem rolagem. 1024: clientHeight 84 sem rolagem. Critério literal, substituído por REQ-13 no aceite.
- AC-10 em 793.98 px. Playwright (viewport do contexto e `setViewportSize`) e CDP `Emulation.setDeviceMetricsOverride` recusam 793.98: "expected integer, got float 793.98" e "Invalid parameters". Nenhuma largura exata foi aplicada ao viewport; nada foi trocado por 793 ou 794.
- Método alternativo (`ac10-fraction.mjs`; iframe com `width: 793.98px` numa página 800x1024): largura CSS do iframe 793.96875; `window.innerWidth` 794; `(min-width: 793.98px)` true; `(max-width: 793.98px)` false; campo `position: absolute`; campo × corpo 0 px²; campo × menu 0 px².
- Controle do método (iframe de 793 px, não substitui 793.98): innerWidth 793; `(max-width: 793.98px)` true; campo `position: static`; topo do campo − base dos controles 0.00 px.
- Leitura factual: a 793.98 px medida por iframe, as media queries usam largura 794, e o campo fica em `absolute`. O critério escrito diz "em fluxo até 793.98 px". Divergência registrada. Decisão do dono (G5a, decisão 4 do plano): aceite da prova do estado alcançável. Largura fracionária de 793,98 px fica como limite residual: não é medível em viewport inteiro e é coberta por teste de CSS. Superado pela decisão 5 do plano: o reflow vale em todas as larguras.

Limpeza e estado final.

- `cleanup.mjs` (`etapa-c-checks/cleanup.log`): count_before=524; g5_records_before=522; 522 DELETE, todos HTTP 204; count_after=2; g5_records_after=0.
- GET final: 2 (user1, user2). Chips 0 ao fim de cada largura da Etapa A nos dois caminhos (ponteiro e teclado). Os contextos foram fechados; chips são estado de página, nada persistido.

Não medido (Etapas A–C): Firefox, WebKit, toque real, barra de rolagem visível, rolagem até o fim; 480, 481, 794 e 1023 nos itens de `checks.mjs`; AC-10 em 793.98 px no viewport do Playwright (float recusado); Enter por teclado na lupa; 3 termos fora de 375 px.

### Larguras extras (480, 481, 794, 1023 px): s, t3, t4

Data: 2026-11-10. HEAD be84d8b, tag `gate/table-g5a-chip-breakpoint`. `styles.css` servido com sha256 igual ao de `/var/lib/webapp-src/be84d8b` (919b8182...). `index.html` 200; health 200. Navegador: Chromium 158.0.8127.18 (headless); Playwright 1.65.0; Node v24.21.0.

Script novo: `g5-tools/extra-widths.mjs`. A lógica de s, t3 e t4 é a de `checkLongChips` em `checks.mjs`, copiada porque `checks.mjs` executa `main()` ao ser importado. Dados: `seed.mjs` antes e `cleanup.mjs` depois, ambos com `G5_DIR` apontando para a pasta de evidência. Termos: `LONG_CHIP_QUERY` (4 termos, chips criados com Enter). Busca fechada pelo X em cada largura.

Critérios: s é a definição de `checks.mjs` (4 chips; botão fechar >= 40 px; campo de texto >= 80 px; chips dentro do campo; sem estouro horizontal). t3 é INFO, com sinal: centro do X menos centro do campo de texto; topo do X menos topo do contêiner do campo de busca. t4 é INFO: base do campo menos topo do corpo, mínimo 0. Nenhum critério novo.

Evidência: `files/g5/g5a-be84d8b/extra-widths/` (fora do repositório): `extra-widths.json`, `extra-widths.log`, `seed.log`, `cleanup.log`, `users-before.json`, `users-after.json` e capturas `s-long-chips-{largura}.png`.

| Largura | s | t3 centro (px) | t3 topo (px) | t4 sobreposição (px) | X fecha; chips 0 |
|---|---|---|---|---|---|
| 480x800 | PASS (fechar 40.0; campo 302.0) | +0.01 | 0.00 | 0.0 (base 500.4; corpo 528.7) | PASS |
| 481x800 | PASS (fechar 40.0; campo 303.0) | +0.01 | 0.00 | 0.0 (base 483.7; corpo 512.0) | PASS |
| 794x1024 | PASS (fechar 40.0; campo 592.0) | +0.01 | 0.00 | 20.7 (base 403.6; corpo 382.9) | PASS |
| 1023x768 | PASS (fechar 40.0; campo 821.0) | +0.01 | 0.00 | 0.0 (base 367.6; corpo 382.9) | PASS |

Subitens de s (t1 e t2, INFO sem veredito): 480: estouro visível 0.00 px; 3 linhas; clientHeight 137 px; scrollHeight 137 px; max-height 172px; campo static. 481: estouro visível 0.00 px (literal 7.69 px); 3 linhas; 120/137 px; max-height 120px. 794: estouro visível 0.00 px; 3 linhas; 120/120 px; campo absolute. 1023: estouro visível 0.00 px; 2 linhas; 84/84 px; campo absolute.

NOT RUN: nenhum. s, t3 e t4 se aplicam às quatro larguras (busca, chips e X funcionam em todas). FAIL: nenhum. Erros de execução: nenhum. pageErrors: 0.

Observação INFO (não é veredito): em 794 px o campo é absoluto e, com 4 chips, cobre 20.7 px do topo do corpo (t4 da subseção). Em 768 e 793 px, a G5 final mediu 20.7 px antes do reflow; nesta rodada, 0.0 px. Com 4 chips, em 794, 1023 e 1024 px, o campo absoluto cobre caixas do cabeçalho (overlapControlsArea 26473, 35475 e 35514 px², sem separar título, lupa e reticências; fieldBelowControlsPx −48, em `recheck-g5a.json`). D-01 em 794 px ou mais foi medido só com 1 chip. Decisão do dono (decisão 5 do plano): reflow em todas as larguras; validação pós-correção pendente.

Usuários: antes da semeadura, 2 (id 6 `user1`; id 7 `user2`). `usuarios_antes_do_script` = 524 no log é a contagem após a semeadura de 522. Seed: 522 criados (`count_after_seed` 524). Limpeza: 522 DELETE, todos HTTP 204; `count_after` 2; `g5_records_after` 0. Depois: GET 2, ids 6 e 7, nomes e e-mails iguais aos de antes.

Não medido: Firefox, WebKit, toque real, barra de rolagem visível, rolagem até o fim, 3 termos nessas larguras, veredito de t1 e t2 (critério REQ-13 não reaplicado nesta rodada), largura 793.98 px.

