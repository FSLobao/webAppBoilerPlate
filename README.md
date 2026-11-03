<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#visão-geral">Visão geral</a></li>
        <li><a href="#início-rápido">Início rápido</a></li>
        <li><a href="#estrutura">Estrutura</a></li>
        <li><a href="#documentação">Documentação</a></li>
    </ol>
</details>

# webAppBoilerPlate

## Visão geral

Boilerplate de aplicação web em containers Podman, gerenciados por Quadlet na rede padrão `podman`.
A aplicação de exemplo é uma SPA CRUD de usuários com nome, email, localização e imagem de perfil.
Ela usa FastAPI, PostgreSQL 18 e um NGINX compartilhado publicado na porta 8080 do host.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Início rápido

Em um host Linux com Podman 5, como `root`:

```bash
sudo deploy/scripts/deploy-webapp.sh
deploy/scripts/smoke-test-webapp.sh
```

Depois, abra `http://localhost:8080/webapp/index.html`.
A documentação da API fica em `http://localhost:8080/webapp/api/docs`.

Para desenvolver o backend:

```bash
uv sync
uv run ruff check .
uv run pytest
```

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `webapp/backend/` | API FastAPI (`webapp_api`) e testes |
| `webapp/frontend/` | SPA estática sem etapa de build |
| `webapp/database/init/` | schema e papel da API no PostgreSQL |
| `webapp/Containerfile` | imagem da aplicação |
| `deploy/webapp/kube/` | pods em YAML Kubernetes para `podman kube play` |
| `deploy/webapp/quadlet/` | unidades `.kube` do Quadlet |
| `deploy/webapp/nginx/` | configuração do NGINX compartilhado |
| `deploy/scripts/` | scripts de deploy e testes |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Documentação

- [Contrato de arquitetura](docs/contracts/ARCHITECTURE.md)
- [Plano da aplicação CRUD](docs/plans/webapp-crud.md)
- [Receita de implantação e operação](docs/recipes/webapp-crud.md)
- [Referências e reuso do Design System GOV.BR](docs/recipes/govbr-design-system.md)
- [Instruções GOV.BR para agentes de frontend](.github/instructions/govbrDesignSystemGuide.instructions.md)

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
