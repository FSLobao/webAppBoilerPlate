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
`gateway-vpn`, cujo CIDR é definido pelas variáveis de ambiente do deployment do Gateway
(`10.100.0.0/24` é somente um exemplo); a variante rootful implementada e mantida usa a rede padrão
`podman`. Os IPs dos pods da webapp são atribuídos dinamicamente pelo Podman. A aplicação de
exemplo é uma SPA CRUD de usuários com nome, email, localização e imagem de perfil. Ela usa
FastAPI, PostgreSQL 18 e um NGINX compartilhado publicado na porta 8080 do host.

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

Em RHEL 9, na raiz do checkout, use `--sysctl-only` para preparar somente o sysctl:

```bash
sudo deploy/scripts/prepare-rootless-host.sh --sysctl-only
```

Esse modo configura e aplica `net.ipv4.ip_unprivileged_port_start=443`. Não inspeciona nem altera
SELinux ou firewall, e seu sucesso não confirma que o host atende aos requisitos de implantação.

`--check` continua sendo uma verificação ampla e somente leitura; não é uma verificação exclusiva
do sysctl:

```bash
sudo deploy/scripts/prepare-rootless-host.sh --check
```

Sem argumentos, o script mantém a aplicação ampla legada: configura o sysctl, desativa
`firewalld` e `nftables` quando instalados e define `SELINUX=disabled` em `/etc/selinux/config`.
Use essa forma somente quando essas alterações amplas forem intencionais. O código de saída `3`
indica que é necessário reiniciar o host antes de continuar.

### Etapa 2 — Implantar com a conta de operação rootless

Siga a receita do Gateway rootless. Execute com a conta dedicada que controla Podman
rootless e as unidades de usuário; `podman_user` é um exemplo. Obtenha o repositório nessa
conta e, a partir de uma sessão com user bus ativo, execute:

```bash
"${HOME}/webAppBoilerPlate/deploy/scripts/deploy-webapp-rootless.sh" \
  --source "${HOME}/webAppBoilerPlate"
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
| Alvo rootless | `deploy/scripts/prepare-rootless-host.sh` | Preparação do sysctl com `--sysctl-only`; sem argumentos, mantém a aplicação ampla legada |
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
- [Receita de monitoramento Podman rootless com Prometheus e Grafana](docs/recipes/podman-rootless-prometheus-grafana.md)
- [Receita de administração do Gateway VPN](docs/recipes/gateway-vpn-admin.md)
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
