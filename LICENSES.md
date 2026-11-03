<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#código-do-projeto">Código do projeto</a></li>
        <li><a href="#frontend">Frontend</a></li>
        <li><a href="#marcas">Marcas</a></li>
        <li><a href="#dependências-de-execução-do-backend">Dependências de execução do backend</a></li>
        <li><a href="#dependências-diretas-de-desenvolvimento">Dependências diretas de desenvolvimento</a></li>
        <li><a href="#imagens-de-contêiner-e-gateway">Imagens de contêiner e gateway</a></li>
        <li><a href="#como-manter">Como manter</a></li>
    </ol>
</details>

# Licenças e atribuições de <NOME DA APLICAÇÃO>

O projeto é distribuído sob GPL-3.0; consulte [LICENSE.md](LICENSE.md).
Titular do projeto: `<TITULAR DO PROJETO>`.

## Código do projeto

| Componente | Versão | Uso no projeto | Licença | Texto da licença (hyperlink) | Observação |
| --- | --- | --- | --- | --- | --- |
| Código do projeto | 0.1.0 | Backend, frontend e configurações próprias | GPL-3.0 | [LICENSE.md](LICENSE.md) | Titular: `<TITULAR DO PROJETO>`. |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="./docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Frontend

| Componente | Versão | Uso no projeto | Licença | Texto da licença (hyperlink) | Observação |
| --- | --- | --- | --- | --- | --- |
| govbr-core CSS | 3.7.0 | Estilos e componentes da interface | MIT | [MIT](https://gitlab.com/govbr-ds/bibliotecas/javascript/govbr-ds-core/-/raw/v3.7.0/LICENSE) | SERPRO; [release oficial npm](https://registry.npmjs.org/@govbr-ds/core/-/core-3.7.0.tgz). |
| Flatpickr | ^4.6.9 (faixa declarada) | Estilização do calendário via `core.min.css` | MIT | [LICENSE oficial](https://github.com/flatpickr/flatpickr/blob/master/LICENSE.md) | Declarado como ^4.6.9 no package.json do pacote @govbr-ds/core 3.7.0 (npm). Copyright (c) 2017 Gregory Petrosyan. |
| Rawline | Não declarada no pacote | Fontes da interface, pesos 400, 600 e 700 | SIL OFL 1.1 | [SIL OFL 1.1](https://openfontlicense.org/open-font-license-official-text/) | [Pacote oficial SERPRO](https://serprodrive.serpro.gov.br/s/dLZJm9soLLiPzzg/download). Copyright (c) 2016, Henrique Ibaldo (hi@ibaldo.co), with Reserved Font Name RAWLINE. Copyright (c) 2010 - 2013, Matt McInerney, Pablo Impallari e Rodrigo Fuenzalida, with Reserved Font Name RALEWAY. |
| Font Awesome Free | 5.11.2 | Ícones SVG da interface | SVG: CC BY 4.0. Fontes e código do pacote não são distribuídos. | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode) | Ícones Font Awesome Free 5.11.2, de Dave Gandy e colaboradores, sob CC BY 4.0; cores de apresentação ajustadas. [Font Awesome](https://fontawesome.com/); [release npm 5.11.2](https://registry.npmjs.org/@fortawesome/fontawesome-free/-/fontawesome-free-5.11.2.tgz). |
| Ilustrações GOV.BR | 1.0.0 | Estado vazio | CC0 1.0 | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/legalcode) | Somente `webapp/frontend/assets/govbr/illustrations/empty-space/png/1x/00.png` é usada; [repositório oficial de assets GOV.BR](https://gitlab.com/govbr-ds/bibliotecas/govbr-ds-assets-de-design). |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="./docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Marcas

| Componente | Versão | Uso no projeto | Licença | Texto da licença (hyperlink) | Observação |
| --- | --- | --- | --- | --- | --- |
| Logotipo da Anatel | — | Identidade visual no rodapé | Marca; não é licença de software | Não se aplica | Uso interno autorizado pelo responsável do projeto; arquivo `webapp/frontend/assets/brand/Anatel_Logo.svg` (origem: `docs/images/Anatel_Logo.svg`). |
| Logotipo gov.br | — | Identidade visual no rodapé | Marca; não é licença de software | Não se aplica | Uso interno autorizado pelo responsável do projeto; arquivo `webapp/frontend/assets/brand/Gov.br_logo.svg` (origem: `docs/images/Gov.br_logo.svg`). Consulte o manual da marca gov.br vigente. |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="./docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Dependências de execução do backend

A imagem do backend é montada com `uv sync --no-dev`. Esta tabela cobre dependências de runtime distribuídas na imagem, diretas e transitivas. Versões conforme `uv.lock` e dependências declaradas em `webapp/backend/pyproject.toml`.

| Componente | Versão | Uso no projeto | Licença | Texto da licença (hyperlink) | Observação |
| --- | --- | --- | --- | --- | --- |
| fastapi | 0.162.0 | API | MIT | [LICENSE oficial](https://github.com/fastapi/fastapi/blob/master/LICENSE) |  |
| uvicorn | 0.54.0 | Servidor ASGI | BSD-3-Clause | [LICENSE.md oficial](https://github.com/Kludex/uvicorn/blob/master/LICENSE.md) |  |
| email-validator | 2.3.0 | Validação de e-mail | Unlicense | [LICENSE oficial](https://github.com/JoshData/python-email-validator/blob/master/LICENSE) |  |
| psycopg | 3.3.6 | Driver PostgreSQL | LGPL-3.0 | [LICENSE.txt oficial](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt) |  |
| psycopg-binary | 3.3.6 | Extra binário do driver PostgreSQL | LGPL-3.0 | [LICENSE.txt oficial](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt) |  |
| psycopg-pool | 3.3.3 | Pool de conexões PostgreSQL | LGPL-3.0 | [LICENSE.txt oficial](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt) |  |
| python-multipart | 0.0.33 | Uploads multipart | Apache-2.0 | [LICENSE.txt oficial](https://github.com/Kludex/python-multipart/blob/main/LICENSE.txt) |  |
| annotated-doc | 0.0.5 | Dependência transitiva de runtime Linux | MIT | [LICENSE oficial](https://github.com/fastapi/annotated-doc/blob/main/LICENSE) |  |
| annotated-types | 0.8.0 | Dependência transitiva de runtime Linux | MIT | [LICENSE oficial](https://github.com/annotated-types/annotated-types/blob/main/LICENSE) |  |
| anyio | 4.15.1 | Dependência transitiva de runtime Linux | MIT | [LICENSE oficial](https://github.com/agronholm/anyio/blob/master/LICENSE) |  |
| click | 8.5.0 | Dependência transitiva de runtime Linux | BSD-3-Clause | [LICENSE.txt oficial](https://github.com/pallets/click/blob/main/LICENSE.txt) |  |
| dnspython | 2.9.1 | Dependência transitiva de runtime Linux | ISC | [LICENSE oficial](https://github.com/rthalley/dnspython/blob/main/LICENSE) |  |
| h11 | 0.16.0 | Dependência transitiva de runtime Linux | MIT | [LICENSE.txt oficial](https://github.com/python-hyper/h11/blob/master/LICENSE.txt) |  |
| idna | 3.20 | Dependência transitiva de runtime Linux | BSD-3-Clause | [LICENSE.md oficial](https://github.com/kjd/idna/blob/master/LICENSE.md) |  |
| opentelemetry-api | 1.45.2 | Dependência transitiva de runtime Linux | Apache-2.0 | [LICENSE oficial](https://github.com/open-telemetry/opentelemetry-python/blob/main/LICENSE) |  |
| pydantic | 2.14.2 | Dependência transitiva de runtime Linux | MIT | [LICENSE oficial](https://github.com/pydantic/pydantic/blob/main/LICENSE) |  |
| pydantic-core | 2.50.2 | Dependência transitiva de runtime Linux | MIT | [LICENSE oficial](https://github.com/pydantic/pydantic-core/blob/main/LICENSE) |  |
| starlette | 1.10.0 | Dependência transitiva de runtime Linux | BSD-3-Clause | [LICENSE.md oficial](https://github.com/Kludex/starlette/blob/main/LICENSE.md) |  |
| typing-extensions | 4.16.0 | Dependência transitiva de runtime Linux | PSF-2.0 | [LICENSE oficial](https://github.com/python/typing_extensions/blob/main/LICENSE) |  |
| typing-inspection | 0.4.4 | Dependência transitiva de runtime Linux | MIT | [LICENSE oficial](https://github.com/pydantic/typing-inspection/blob/main/LICENSE) |  |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="./docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Dependências diretas de desenvolvimento

Dependências diretas de desenvolvimento declaradas no grupo `dev` do `pyproject.toml` da raiz do repositório, não distribuídas na imagem do backend (--no-dev). As dependências transitivas não estão listadas.

| Componente | Versão | Uso no projeto | Licença | Texto da licença (hyperlink) | Observação |
| --- | --- | --- | --- | --- | --- |
| httpx | 0.28.1 | Testes; não distribuído na imagem (`--no-dev`) | BSD-3-Clause | [LICENSE.md oficial](https://github.com/encode/httpx/blob/master/LICENSE.md) |  |
| pytest | 9.2.0 | Testes; não distribuído na imagem (`--no-dev`) | MIT | [LICENSE oficial](https://github.com/pytest-dev/pytest/blob/main/LICENSE) |  |
| ruff | 0.17.3 | Lint; não distribuído na imagem (`--no-dev`) | MIT | [LICENSE oficial](https://github.com/astral-sh/ruff/blob/main/LICENSE) |  |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="./docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Imagens de contêiner e gateway

| Componente | Versão | Uso no projeto | Licença | Texto da licença (hyperlink) | Observação |
| --- | --- | --- | --- | --- | --- |
| postgres | 18-trixie | Banco de dados em `deploy/webapp/kube/webapp-db.yaml` | PostgreSQL License | [Licença PostgreSQL](https://www.postgresql.org/about/licence/) |  |
| nginx | 1.28-alpine | Proxy em `deploy/webapp/kube/app-proxy.yaml` | BSD-2-Clause | [LICENSE oficial](https://github.com/nginx/nginx/blob/master/LICENSE) | Imagem do app-proxy. |
| python | 3.13-slim-trixie | Runtime em `webapp/Containerfile` | PSF-2.0 | [LICENSE oficial](https://github.com/python/cpython/blob/main/LICENSE) |  |
| uv | 0.9-python3.13-trixie-slim | Build em `webapp/Containerfile` | MIT OR Apache-2.0 | [LICENSE-MIT](https://github.com/astral-sh/uv/blob/main/LICENSE-MIT); [LICENSE-APACHE](https://github.com/astral-sh/uv/blob/main/LICENSE-APACHE) |  |
| Node.js | Conforme imagem headplane 0.8.2 | Runtime copiado para `/nodejs` em `deploy/gateway/v1/Containerfile` | MIT e licenças de componentes incluídos | [LICENSE oficial](https://github.com/nodejs/node/blob/main/LICENSE) | Origem: imagem headplane 0.8.2. |
| debian | trixie-slim | Base do gateway em `deploy/gateway/v1/Containerfile` | Licenças por pacote | [Licenças Debian](https://www.debian.org/legal/licenses/) | A licença depende de cada pacote incluído. Código-fonte disponível pelo snapshot Debian `20261020T213255Z`, definido em `DEBIAN_SNAPSHOT`; [snapshot.debian.org](https://snapshot.debian.org/). |
| bash | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | GPL-3.0-or-later | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| coreutils | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | GPL-3.0-or-later | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| iptables | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | GPL-2.0-only; GPL-2.0-or-later | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| iproute2 | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | GPL-2.0-only | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| conntrack | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | GPL-2.0-or-later | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| util-linux | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | GPL-2.0-or-later; LGPL-2.1-or-later; BSD; MIT; ISC | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| libstdc++6 | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | GPL-3.0-or-later WITH GCC-exception-3.1 | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| nginx-light | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Proxy do gateway, pacote Debian | BSD-2-Clause; MIT; GPL-2.0-or-later; domínio público | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| tailscale | 1.104.2 | Binários `tailscale` e `tailscaled` no gateway | BSD-3-Clause | [LICENSE oficial](https://github.com/tailscale/tailscale/blob/main/LICENSE) | Origem dos binários tailscale e tailscaled, por COPY --from=tailscale em deploy/gateway/v1/Containerfile. |
| headplane | 0.8.2 | Interface de administração do gateway | MIT | [LICENSE oficial](https://github.com/tale/headplane/blob/main/LICENSE) |  |
| headscale | 0.29.6 | Binário do gateway, conforme `deploy/gateway/v1/Containerfile` | BSD-3-Clause | [LICENSE oficial](https://github.com/juanfont/headscale/blob/main/LICENSE) |  |
| tcpdump | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | BSD-3-Clause; BSD-4-Clause | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| passwd | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | BSD-3-Clause; GPL-1.0-only; GPL-2.0-or-later | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |
| ca-certificates | Resolvida pelo snapshot DEBIAN_SNAPSHOT | Pacote Debian do gateway | GPL-2.0-or-later; MPL-2.0 | [Licenças Debian](https://www.debian.org/legal/licenses/) |  |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="./docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Como manter

- Atualize esta tabela quando uma dependência mudar.
- Confira as versões em `uv.lock` e nos Containerfiles.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="./docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
