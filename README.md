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

### Alternativa rootless

**Experimental, test-only e somente para laboratório.** Exige a rede `gateway-vpn` (`10.90.0.0/24`, DNS ativo) da receita rootless.

O comando rootful acima continua sendo o padrão. Como `root`, na raiz do checkout, crie `<DIR>` com
`mkdir -p <DIR>`, extraia `git archive HEAD | tar -x -C <DIR>` e ajuste a propriedade com
`chown -R podman_user:podman_user <DIR>`.
Depois, execute como `podman_user`:

```bash
deploy/scripts/deploy-webapp-rootless.sh --source <DIR>
```

Consulte a [receita do Gateway rootless](docs/recipes/gateway-headscale-podman-rootless.md).

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
