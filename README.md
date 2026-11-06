<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#visão-geral">Visão geral</a></li>
        <li><a href="#início-rápido">Início rápido</a></li>
        <li><a href="#estrutura">Estrutura</a></li>
        <li><a href="#mapa-das-variantes">Mapa das variantes</a></li>
        <li><a href="#documentação">Documentação</a></li>
        <li><a href="#desenvolvimento-assistido-por-agentes">Desenvolvimento assistido por agentes</a></li>
    </ol>
</details>

# webAppBoilerPlate

## Visão geral

Boilerplate de aplicação web em containers Podman. O alvo é rootless, com Quadlet na rede
`gateway-vpn` (`10.90.0.0/24`); a variante rootful implementada e mantida usa a rede padrão
`podman`. A aplicação de exemplo é uma SPA CRUD de usuários com nome, email, localização e imagem
de perfil. Ela usa FastAPI, PostgreSQL 18 e um NGINX compartilhado publicado na porta 8080 do host.

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

O alvo de implantação tem duas etapas. Consulte a [receita rootless do Gateway](docs/recipes/gateway-headscale-podman-rootless.md)
para pré-requisitos, configuração da conta e passos completos.

### Etapa 1 — Preparar o host (root)

Em RHEL 9, na raiz do checkout, execute uma vez por host. Primeiro confira o estado; aplique a
preparação somente após revisar o resultado:

```bash
sudo deploy/scripts/prepare-rootless-host.sh --check
```

```bash
sudo deploy/scripts/prepare-rootless-host.sh
```

O script configura `net.ipv4.ip_unprivileged_port_start=443`, desativa `firewalld` e `nftables`
quando instalados e define `SELINUX=disabled` em `/etc/selinux/config`. O código de saída `3`
indica que é necessário reiniciar o host antes de continuar.

### Etapa 2 — Implantar como `podman_user` (rootless)

Siga a receita do Gateway rootless. Para a webapp, como `root`, prepare `<DIR>` com `mkdir -p <DIR>`,
extraia `git archive HEAD | tar -x -C <DIR>` e ajuste a propriedade com
`chown -R podman_user:podman_user <DIR>`. Depois, execute como `podman_user`:

```bash
deploy/scripts/deploy-webapp-rootless.sh --source <DIR>
```

Depois, abra `http://localhost:8080/webapp/index.html`.
A documentação da API fica em `http://localhost:8080/webapp/api/docs`.

### Alternativa rootful (implementada, mantida)

Em um host Linux com Podman 5, como `root`:

```bash
sudo deploy/scripts/deploy-webapp.sh
deploy/scripts/smoke-test-webapp.sh
```

O fluxo rootful usa a rede padrão `podman` e permanece disponível como alternativa.

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

## Mapa das variantes

| Variante | Caminho | Papel |
| --- | --- | --- |
| Alternativa rootful | `deploy/gateway/v1/**` (exceto o `Containerfile`, compartilhado abaixo) | Arquivos da variante rootful implementada e mantida |
| Alternativa rootful | `deploy/scripts/deploy-webapp.sh` | Deploy da webapp rootful |
| Alternativa rootful | `deploy/scripts/enroll-gateway.sh` | Inscrição prevista para a variante rootful; integração rootless permanece pendente |
| Alternativa rootful | `deploy/webapp/**` (exceto os YAML de `kube/`, compartilhados abaixo) | Quadlet e configuração do deploy rootful |
| Alternativa rootful | `docs/recipes/gateway-headscale-podman-rootfull.md` | Receita rootful implementada e mantida |
| Alvo rootless | `deploy/scripts/prepare-rootless-host.sh` | Etapa 1 rootful de preparação do host para o alvo rootless |
| Alvo rootless | `deploy/scripts/deploy-webapp-rootless.sh` | Deploy rootless da webapp |
| Alvo rootless | `docs/recipes/gateway-headscale-podman-rootless.md` | Receita do Gateway rootless |
| Compartilhado | `webapp/**` | Código-fonte da aplicação |
| Compartilhado | `deploy/webapp/kube/*.yaml` | YAML usado pelas duas variantes e lido pelo script rootless |
| Compartilhado | `webapp/Containerfile` | Imagem da webapp |
| Compartilhado | `deploy/gateway/v1/Containerfile` | Imagem do Gateway usada pelas duas variantes |

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

- [Receita de implantação e operação](docs/recipes/webapp-crud.md)
- [Receita do Gateway rootless](docs/recipes/gateway-headscale-podman-rootless.md)
- [Receita do cliente VPN](docs/recipes/gateway-vpn-client.md)
- [Referências e reuso do Design System GOV.BR](docs/recipes/govbr-design-system.md)

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Desenvolvimento assistido por agentes

O diretório [`.agent/`](.agent/) reúne contratos, planos e memória interna de desenvolvimento.
O diretório [`.github/`](.github/) reúne papéis de agentes, instruções e skills do repositório.
Consulte esses materiais ao usar agentes neste projeto; use `docs/` para procedimentos destinados
a pessoas desenvolvedoras e operadoras.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
