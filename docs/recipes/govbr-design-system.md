<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#objetivo-e-escopo">Objetivo e escopo</a></li>
        <li><a href="#fundamentos-visuais">Fundamentos visuais</a></li>
        <li><a href="#diagramação-e-componentes">Diagramação e componentes</a></li>
        <li><a href="#recursos-para-reuso">Recursos para reuso</a></li>
        <li><a href="#licenças-imagens-e-marcas">Licenças, imagens e marcas</a></li>
        <li><a href="#acessibilidade-e-validação">Acessibilidade e validação</a></li>
    </ol>
</details>

# Design System GOV.BR: referências para webapps

## Objetivo e escopo

Esta referência orienta pessoas desenvolvedoras e revisoras na aplicação do
[Design System GOV.BR](https://www.gov.br/ds/home).
As [instruções para agentes](../../.github/instructions/govbrDesignSystemGuide.instructions.md)
definem o fluxo de trabalho do repositório. As regras oficiais abaixo têm suas fontes vinculadas;
as recomendações locais estão identificadas como decisões deste projeto.

A aplicação de usuários usa CSS e assets locais do Design System, além das ilustrações copiadas.
O frontend permanece estático, sem build, conforme o [plano da aplicação](../plans/webapp-crud.md).
A aparência GOV.BR não comprova acessibilidade, certificação, vínculo oficial ou conformidade jurídica.
Os responsáveis pelo serviço devem confirmar as obrigações institucionais aplicáveis.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Fundamentos visuais

A [diretriz oficial de grid](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/fundamentos-visuais/grid/grid.md)
define as seguintes faixas, em pixels CSS:

| Largura da viewport | Breakpoint inicial | Colunas | Gutter | Margens |
| --- | --- | --- | --- | --- |
| 0 a 575 px | 0 px | 4 | 16 px | 8 px |
| 576 a 991 px | 576 px | 8 | 24 px | 40 px |
| 992 a 1279 px | 992 px | 8 | 24 px | 40 px |
| 1280 a 1599 px | 1280 px | 12 | 24 px | 40 px |
| 1600 px ou mais | 1600 px | 12 | 40 px | 40 px |

Use os utilitários da release escolhida; os breakpoints de outro framework não são substitutos.
A [diretriz de espaçamento](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/fundamentos-visuais/espacamento/espacamento.md)
usa incrementos de 8 px para layout e de 4 px para ajustes de textos e ícones.
Exemplos: `--spacing-scale-base` = 8 px, `--spacing-scale-2x` = 16 px,
`--spacing-scale-3x` = 24 px e `--spacing-scale-half` = 4 px.

A [tipografia oficial](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/fundamentos-visuais/tipografia/tipografia.md)
referencia Rawline, tamanho-base de 14 px e peso
regular 400, com escala relativa.
Consulte `--font-family-base`, `--font-size-scale-base`, `--font-size-scale-up-01`,
`--font-weight-regular` e `--font-weight-semi-bold` no CSS da release.
O tamanho-base não significa que todo texto deva ter 14 px.

A [diretriz de cores](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/fundamentos-visuais/cores/cores.md)
documenta `--pure-0` = `#fff`, `--gray-80` = `#333333` e
`--blue-warm-vivid-70` = `#1351B4`.
Para estados, referencia `--green-cool-vivid-50`, `--yellow-vivid-20` e `--red-vivid-50`.
**Recomendação local:** reutilize os tokens e confira o contraste na composição real;
associe texto ou outros indicadores aos estados comunicados por cor.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Diagramação e componentes

O [template Base](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/padroes/design/base/base.md)
define cabeçalho, conteúdo e rodapé como regiões obrigatórias **nesse modelo**;
breadcrumb e menu são opcionais. A [diretriz Header](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/header/header.md)
trata o logo como opcional. O uso dos logotipos segue o manual aplicável e a autorização
do responsável do projeto; a origem e as condições estão em [LICENSES.md](../../LICENSES.md).

| Integração | Reuso | Orientação local |
| --- | --- | --- |
| Core: `@govbr-ds/core` | HTML, CSS e JavaScript; classes `.br-button`, `.br-input`, `.br-table`, `.br-header`, `.br-footer` | CSS 3.7.0 incorporado no frontend estático |
| Web Components: `@govbr-ds/webcomponents` | Custom Elements, como `<br-button>`; integração com HTML/JS e frameworks | Avaliar compatibilidade e versão antes de adotar |
| Core com Web Components | Utilitários externos de grid, cores e espaçamento | Conferir carregamento e dependências de ambas as releases |

A [orientação oficial de desenvolvimento](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-site-content/como-comecar/fluxo-dev/fluxo-dev.md)
recomenda Web Components para projetos modernos, mas também admite Core e hospedagem própria.
O [guia HTML/JavaScript](https://govbr-ds.gitlab.io/bibliotecas/wbc/govbr-ds-wbc/docs/frameworks/javascript/)
documenta o loader dos Web Components; `<br-button>` não é a classe `.br-button` do Core.

O [distributivo Core 3.7.0](https://registry.npmjs.org/@govbr-ds/core/-/core-3.7.0.tgz)
contém `.container-lg`, `.row`, `.col-4`, `.col-sm-8` e `.col-lg-12`.
Use a anatomia, os atributos, os estados e a inicialização do
[catálogo de componentes](https://www.gov.br/ds/components/visao-geral), não apenas suas classes CSS.
Priorize os componentes necessários ao fluxo: navegação, formulários, tabelas,
paginação, mensagens e diálogos. Componentes interativos exigem a configuração documentada para a release.

A tela de usuários segue as referências de
[header](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/header/header.md),
[menu](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/menu/menu.md),
[footer](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/footer/footer.md),
[button](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/button/button.md),
[input](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/input/input.md),
[table](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/table/table.md) e
[modal](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/modal/modal.md).
No desktop, a navegação aberta usa `<aside>` como landmark complementar não modal;
ela não usa `<dialog>`. Em viewports de até 767,98 px, o mesmo `.menu-container`
é transferido para um `<dialog>` modal. Há uma única lista de links nos dois modos.
O corte de 767,98 px é uma decisão local do app, alinhada ao ponto em que a tabela
passa ao modo de cartões; não é um breakpoint oficial do Design System.
O CSS local substitui o `display: none` inicial de `.br-menu .menu-container`
do Core 3.7.0, sem editar o arquivo distribuído. O dialog usa a classe local
`.is-modal`, sem `.active` do Core, que fixa o container e posiciona o scrim.

No desktop, o painel inicia fechado. Ao abrir, começa expandido e pode ser recolhido
pelo botão **Modo compacto**.
Os rótulos ficam visualmente ocultos nesse modo, mas continuam disponíveis a leitores
de tela. O controle mantém o nome acessível **Modo compacto**, com `aria-pressed` e
tooltip que indica ativar ou desativar o modo. No desktop, o hamburger é idempotente:
fechado abre, recolhido expande e aberto permanece aberto em cliques repetidos; ele não
fecha o painel. O botão **Fechar** fecha. No estreito, o hamburger abre a navegação modal
com scrim e o botão de recolher fica oculto.
Os destinos continuam links dentro de landmarks `<nav>` com nomes distintos, e o
hamburger mantém o nome acessível **Navegação**. `aria-expanded` e `aria-controls`
acompanham o wrapper ativo. Escape fecha o painel desktop apenas quando o evento vem
do painel e restaura foco ao hamburger. No estreito, Escape, o scrim ou **Fechar**
fecham somente a navegação e retornam foco ao hamburger quando não há outro diálogo
aberto.

Política local de redimensionamento: ao passar de desktop para estreito com a navegação
aberta, foco fora do menu fecha a navegação sem mover foco; foco dentro do menu converte
a navegação em modal e preserva o item focado. A navegação modal não abre sobre um modal
CRUD já aberto; a navegação fecha sem focar o hamburger e o CRUD permanece aberto.
Ao passar de estreito para desktop com a navegação modal aberta, foco disponível fora
do menu permanece no alvo anterior. Se o alvo era `body`, nulo ou deixou de ser focável,
o hamburger recebe foco; a aplicação não chama `focus()` em `body`. Um modal CRUD aberto
e seu foco permanecem.

O rodapé exibe os logotipos da Anatel e do gov.br, com uso
interno autorizado pelo responsável do projeto. Os arquivos estão em
webapp/frontend/assets/brand/ e a origem está em [LICENSES.md](../../LICENSES.md).

O cabeçalho usa `.br-header.compact` do Core 3.7.0. A regra define
`--header-padding: var(--header-padding-small)`; `.br-header` define
`--header-padding-small: var(--spacing-scale-base)` (8 px) e aplica
`padding: var(--header-padding) 0`. O seletor
`.br-header .header-menu .header-title` usa `--header-title-size`: tamanho-base
(14 px) abaixo de 576 px, `--font-size-scale-up-01` (16,8 px) a partir de 576 px
e `--font-size-scale-up-02` (20,16 px) a partir de 1280 px. A documentação oficial
do [Header](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/header/header.md)
recomenda ajustar o título aos breakpoints; a escala de tamanhos consta na
[Tipografia oficial](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/fundamentos-visuais/tipografia/tipografia.md),
e os valores acima são definidos pelos seletores e tokens do CSS Core 3.7.0. O CSS
local, por decisão do app, exibe o subtítulo a partir de 576 px e o oculta abaixo
desse limite. O hamburger usa
`.br-button.circle`. Na release Core 3.7.0, a regra
`.br-button` define `--button-medium: 40px`,
`--button-size: var(--button-medium)` e `height: var(--button-size)`; a regra
`.br-button.circle` define `width: var(--button-size)`. Assim, o hamburger tem
dimensões declaradas de 40 × 40 px na densidade padrão. Consulte a página oficial de
[Button](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/button/button.md)
e valide a renderização na aplicação.

O [footer oficial](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/componentes/footer/footer.md)
descreve, para alta densidade, padding vertical de 8 px e largura mínima de 102 px
para o logo. O rodapé local usa
`padding: var(--spacing-scale-base) 0`, equivalente a 8 px verticais no Core
3.7.0. Os wrappers dos logos usam `padding: 0 var(--spacing-scale-half)`,
equivalente a 4 px horizontais e 0 px verticais. O app escolhe altura de `3em`
e largura automática para ambos os logos. Os SVGs declaram atributos `width` e
`height`, que estabelecem sua proporção intrínseca; sua renderização no navegador
ainda não foi verificada. Não há atributo `viewBox`.
Para estimar dimensões, assumindo condicionalmente `font-size` herdado de 14 px
(não verificado como valor computado), `3em` corresponde, por cálculo, a 42 px de
altura; nesse cenário, as larguras estimadas são 42 px para Anatel (atributos
`width="600"` e `height="600"`) e 117 px para gov.br (atributos `width="495"` e
`height="178"`). São estimativas aritméticas condicionais;
não há estilos computados nem medidas feitas em navegador. Nesse cenário, Anatel
fica abaixo do mínimo oficial de 102 px. Essa altura de `3em` é decisão do produto,
não requisito oficial.
O texto central usa `line-height: 3`, sem altura fixa; links podem quebrar
naturalmente em telas estreitas.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Recursos para reuso

A [configuração pública do portal](https://www.gov.br/ds/assets/config.json) anuncia Core **3.7.0**.
Esse valor identifica a versão declarada pelo portal, não a versão mais recente disponível.
Os links abaixo identificam as fontes dos recursos e alternativas para consulta.

| Recurso | Link | Uso e cuidado |
| --- | --- | --- |
| CSS Core versionado | [core.min.css 3.7.0](https://cdn.jsdelivr.net/npm/@govbr-ds/core@3.7.0/dist/core.min.css) | A aplicação usa uma cópia local da mesma release |
| JavaScript Core versionado | [core.min.js 3.7.0](https://cdn.jsdelivr.net/npm/@govbr-ds/core@3.7.0/dist/core.min.js) | Seguir inicialização e dependências da release |
| Pacote completo Core | [core-3.7.0.tgz](https://registry.npmjs.org/@govbr-ds/core/-/core-3.7.0.tgz) | Inclui `dist/core.min.css`, `dist/core.min.js`, `dist/core-init.js` e `LICENSE` |
| Código e releases Core | [GitLab oficial](https://gitlab.com/govbr-ds/bibliotecas/javascript/govbr-ds-core) | Auditar a versão escolhida |
| Web Components | [Documentação](https://govbr-ds.gitlab.io/bibliotecas/wbc/govbr-ds-wbc/) e [código](https://gitlab.com/govbr-ds/bibliotecas/wbc/govbr-ds-wbc) | Selecionar versão compatível; não misturar exemplos de releases |
| Rawline: arquivos para hospedagem própria | [ZIP oficial](https://serprodrive.serpro.gov.br/s/dLZJm9soLLiPzzg/download) | Inclui `fonts/rawline/css/rawline.css`, fontes e SIL OFL 1.1 |
| Rawline: CSS remoto | [rawline.css](https://cdngovbr-ds.estaleiro.serpro.gov.br/design-system/fonts/rawline/css/rawline.css) | URL sem versão fixa; dependência externa se incorporada |
| Ícones do exemplo Core | [Font Awesome 5.11.2](https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.11.2/css/all.min.css) | Versão documentada no exemplo Core, com licença própria |
| Diagramação | [Template Base](https://www.gov.br/ds/templates/base) | Modelo estrutural de página |
| Modelos de telas e UIKits | [Catálogo de assets](https://www.gov.br/ds/downloads/assets) | Modelos Base, CRUD, dashboard, sessão e erro |
| Ilustrações oficiais locais | [PNG 1x copiados](../../webapp/frontend/assets/govbr/illustrations/) | 248 imagens do pacote oficial 1.0.0; versões 2x/3x não copiadas |
| Pacote de ilustrações | [Download de 174,8 MB](https://serprodrive.serpro.gov.br/s/kqcLeMZ5tQiNxrR/download) | Licença confirmada pela política oficial de design abaixo; ZIP sem licença própria |
| Pincéis de ilustração | [Pacote de 2,8 MB](https://serprodrive.serpro.gov.br/s/fqpQbTmtmpPM6r4/download) | Contém pincel Adobe Illustrator, não imagens prontas |
| Identidade institucional complementar | [Manual da marca do Governo Federal, Secom](https://www.gov.br/secom/pt-br/acompanhe-a-secom/central-de-conteudo/guias-e-manuais/uso-da-marca-do-governo-federal) | Não confundir com identidade GOV.BR ou logo do serviço |

### Recursos incluídos no frontend

| Recurso local | Origem e licença |
| --- | --- |
| [Core CSS 3.7.0](../../webapp/frontend/assets/vendor/govbr-core-3.7.0/core.min.css) | [Pacote oficial 3.7.0](https://registry.npmjs.org/@govbr-ds/core/-/core-3.7.0.tgz); [MIT](../../webapp/frontend/assets/vendor/govbr-core-3.7.0/LICENSE), copyright SERPRO |
| [Rawline 400, 600 e 700](../../webapp/frontend/assets/vendor/rawline/) | [ZIP oficial](https://serprodrive.serpro.gov.br/s/dLZJm9soLLiPzzg/download); [SIL OFL 1.1](../../webapp/frontend/assets/vendor/rawline/LICENSE.txt) |
| [Ícones SVG Font Awesome Free 5.11.2](../../webapp/frontend/assets/vendor/fontawesome-5.11.2/solid/) | [Distribuição 5.11.2](https://registry.npmjs.org/@fortawesome/fontawesome-free/-/fontawesome-free-5.11.2.tgz); [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) para SVGs |
| [Ilustração de estado vazio](../../webapp/frontend/assets/govbr/illustrations/empty-space/png/1x/00.png) | Pacote GOV.BR de ilustrações 1.0.0; CC0 1.0 conforme a política descrita abaixo |
| [Logotipo da Anatel](../../webapp/frontend/assets/brand/Anatel_Logo.svg) | Origem: [docs/images/Anatel_Logo.svg](../../docs/images/Anatel_Logo.svg); uso interno autorizado pelo responsável do projeto; [LICENSES.md](../../LICENSES.md) |
| [Logotipo gov.br](../../webapp/frontend/assets/brand/Gov.br_logo.svg) | Origem: [docs/images/Gov.br_logo.svg](../../docs/images/Gov.br_logo.svg); uso interno autorizado pelo responsável do projeto; [LICENSES.md](../../LICENSES.md) |

Os ícones Font Awesome Free são de Dave Gandy e colaboradores. Os demais SVGs locais são
`bars.svg`, `file-alt.svg`, `handshake.svg`, `pen.svg`, `plus.svg`,
`question-circle.svg`, `times.svg`, `trash-alt.svg` e `users.svg`.
O CSS local ajusta a cor de apresentação de alguns ícones. A atribuição obrigatória sob
CC BY 4.0 está em [LICENSES.md](../../LICENSES.md), acessível pelo link **Termos** no
rodapé e no menu.
Fontes, CSS, ícones e ilustrações são servidos localmente; o navegador não precisa
acessar CDN para executar a interface.

Para atualizar um recurso, obtenha a release oficial aprovada, confira dependências,
licenças e anatomia dos componentes, substitua os arquivos selecionados e seus avisos,
e execute os testes da [receita CRUD](./webapp-crud.md#desenvolver).
Reconstrua a imagem para publicar a alteração. Para reverter, restaure a versão
anterior dos arquivos e reconstrua a imagem novamente.

O [guia CDN dos Web Components](https://govbr-ds.gitlab.io/bibliotecas/wbc/govbr-ds-wbc/docs/guias-essenciais/cdn/)
recomenda jsDelivr e alerta sobre `@latest`, embora mostre intervalos de major.
**Recomendação local:** fixe uma versão completa; prefira arquivos locais auditados
quando for necessário preservar a entrega estática sem dependências externas.
Mantenha CSS de ajustes separado do distributivo oficial.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Licenças, imagens e marcas

A licença do projeto é GPL-3.0; seu texto integral está em [LICENSE.md](../../LICENSE.md).
O índice das licenças de componentes está em [LICENSES.md](../../LICENSES.md).

A [política oficial de licenças](https://govbr-ds.gitlab.io/tools/govbr-ds-wiki/git-gitlab/guias/licencas/)
define CC0 1.0 Universal para projetos de design e documentação, e MIT para software.
O [repositório oficial de assets de design](https://gitlab.com/govbr-ds/bibliotecas/govbr-ds-assets-de-design)
inclui a pasta `ilustracoes/` e o arquivo [LICENSE-CC0](https://gitlab.com/govbr-ds/bibliotecas/govbr-ds-assets-de-design/-/raw/main/LICENSE-CC0).
O catálogo oficial lista o [pacote de ilustrações 1.0.0](https://www.gov.br/ds/assets/config.json);
seus PNGs 1x foram copiados para [webapp/frontend/assets/govbr/illustrations/](../../webapp/frontend/assets/govbr/illustrations/).
O ZIP não contém licença própria; a política e o repositório oficial confirmam o licenciamento CC0 dos assets de design.
CC0 permite copiar, modificar e redistribuir; não concede direitos de marca, imagem, privacidade ou endosso.

A [licença MIT do Core 3.7.0](https://gitlab.com/govbr-ds/bibliotecas/javascript/govbr-ds-core/-/raw/v3.7.0/LICENSE)
exige conservar os avisos de copyright e permissão.
Licença aberta do Design System não libera automaticamente qualquer conteúdo hospedado ou vinculado por domínio `gov.br`;
recursos externos podem ter titulares e termos próprios.

O ZIP oficial Rawline contém `fonts/rawline/SIL Open Font License.txt`,
com SIL OFL 1.1 e nomes reservados RALEWAY e RAWLINE.
A [licença Font Awesome 5.11.2](https://raw.githubusercontent.com/FortAwesome/Font-Awesome/5.11.2/LICENSE.txt)
distingue ícones SVG/JS sob CC BY 4.0, fontes sob SIL OFL 1.1 e demais arquivos de código sob MIT.
Marcas pertencem aos respectivos titulares; a licença não implica endosso.

**Recomendação local:** registre origem, autoria, licença, atribuição e permissões de cada imagem.
Preserve proporções, áreas de proteção e condições do manual aplicável às marcas.
Use texto alternativo informativo ou `alt=""` para imagens decorativas.
Use as ilustrações locais licenciadas em CC0; mantenha como links os assets com direitos não confirmados.
Não foi confirmado um banco fotográfico genérico com autorização ampla de reutilização.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Acessibilidade e validação

A [diretriz de acessibilidade DS](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds/ds/acessibilidade/acessibilidade.md)
requer avaliação humana além de verificações automáticas.
O [guia HTML DS](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-site-content/guias/acessibilidade-html/acessibilidade-html.md)
vincula [eMAG](https://emag.governoeletronico.gov.br/) e [WCAG 2.1](https://www.w3.org/TR/WCAG21/).
Consulte também o [guia WAI-ARIA](https://www.gov.br/ds/guias/wai-aria).
A diretriz de cores referencia contraste AA de 4,5:1 para texto normal e 3:1 para texto grande.

Checklist local para cada implementação ou alteração:

- [ ] Fontes, versões completas, licenças e atribuições registradas.
- [ ] Grid verificada imediatamente antes e depois de 576, 992, 1280 e 1600 px, sem perder conteúdo ou controles.
- [ ] Anatomia, atributos, estados e inicialização conferidos na documentação de cada componente.
- [ ] Fluxos operáveis por teclado, com foco visível e ordem coerente; diálogos com gestão adequada de foco.
- [ ] Campos com nomes acessíveis, rótulos e erros associados; mensagens de estado compreensíveis.
- [ ] Contraste, ampliação, reflow e leitura por tecnologia assistiva avaliados na página real.
- [ ] CSS, JavaScript, fontes e imagens resolvem sob `/webapp/`, sem erros ou dependências externas inadvertidas.
- [ ] Contratos da API, validação, autenticação e autorização preservados.
- [ ] Nenhuma alegação de vínculo oficial ou certificação baseada somente na aparência.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
