<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#objetivo">Objetivo</a></li>
        <li><a href="#pré-requisitos">Pré-requisitos</a></li>
        <li><a href="#implantar">Implantar</a></li>
        <li><a href="#verificar">Verificar</a></li>
        <li><a href="#operar">Operar</a></li>
        <li><a href="#desenvolver">Desenvolver</a></li>
        <li><a href="#solução-de-problemas">Solução de problemas</a></li>
    </ol>
</details>

# Receita: aplicação web CRUD de usuários

## Objetivo

Esta receita implanta a SPA de cadastro de usuários em um host Podman rootful.
O desenho e as decisões estão no [plano](../plans/webapp-crud.md).

Ao final, o host atende:

- SPA em `http://localhost:8080/webapp/index.html`;
- API em `http://localhost:8080/webapp/api/` e documentação OpenAPI em `http://localhost:8080/webapp/api/docs`;
- imagens de perfil em `http://localhost:8080/webapp/files/<nome>`, servidas pelo NGINX.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Pré-requisitos

- Linux com systemd e Podman 5 com Quadlet. Validado em RHEL 9.8 com Podman 5.8.2.
- Execução como `root`.
- Rede padrão `podman` com DNS habilitado. Confira com `podman network inspect podman --format '{{.DNSEnabled}}'`.
- SELinux `Disabled`, conforme o [contrato de arquitetura](../contracts/ARCHITECTURE.md).
- Porta TCP 8080 livre no host.
- Acesso às imagens `docker.io/library/postgres:18-trixie`, `docker.io/library/nginx:1.28-alpine`, `docker.io/library/python:3.13-slim-trixie` e `ghcr.io/astral-sh/uv:0.9-python3.13-trixie-slim`.
- `curl` e `jq` para o teste ponta a ponta.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Implantar

> [!WARNING]
> O deploy reinicia a aplicação e o proxy, causando indisponibilidade temporária.
> Os secrets e os volumes guardam o estado da aplicação. Não apague `/etc/webapp/secrets/`
> com o volume `webapp-db-data` presente. O script recusa continuar nesse caso, porque
> as senhas novas não corresponderiam ao banco.

Na raiz do repositório, execute:

```bash
sudo deploy/scripts/deploy-webapp.sh
```

O script é idempotente. Ele executa, nesta ordem:

1. verifica `root`, comandos, SELinux e DNS da rede `podman`;
2. constrói a imagem `localhost/webapp:0.1.0`;
3. cria os secrets ausentes em `/etc/webapp/secrets/` sem sobrescrever os existentes;
4. instala YAML, SQL de inicialização, configuração NGINX e unidades `.kube`;
5. cria o volume `webapp-images` com dono `10001`;
6. executa `systemctl daemon-reload`, inicia `webapp-db.service` e reinicia `webapp.service` e `app-proxy.service`;
7. espera até 90 s pelo health da API pelo NGINX.

Para reaplicar apenas a configuração sem reconstruir a imagem, use `--no-build`.
Alterações no frontend e seus assets só aparecem após reconstruir a imagem;
`--no-build` mantém a imagem anterior.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Verificar

> [!WARNING]
> O teste a seguir cria, altera e exclui um usuário e uma imagem no ambiente indicado.
> Use um ambiente de teste. A limpeza é tentada em falhas, mas uma interrupção ou erro
> de rede pode deixar o registro e a imagem temporários para remoção manual.

Execute o teste ponta a ponta:

```bash
deploy/scripts/smoke-test-webapp.sh
```

Resultado esperado: linhas `ok <status> <url>` e, ao final, `Smoke test passed`.
O teste cria um usuário, valida email duplicado (`409`) e dados inválidos (`422`), envia uma imagem, baixa a imagem pelo NGINX, rejeita um arquivo que não é imagem (`415`) e remove tudo ao final.

Para testar outro host, informe a URL base:

```bash
deploy/scripts/smoke-test-webapp.sh http://<host>:8080/webapp
```

Depois, abra `http://localhost:8080/webapp/index.html` no navegador.
Crie, edite e exclua um usuário pelos botões Editar e Excluir de cada linha (à direita da tabela acima de 767,98 px e no rodapé de cada cartão até 767,98 px).
O corte de 767,98 px é uma decisão local do app, compartilhada com a passagem da tabela
para cartões; não é um breakpoint oficial do Design System.
No desktop, a navegação inicia fechada. O botão de ícone **Navegação** abre o menu;
seu nome acessível é **Navegação**. No desktop, o hamburger é idempotente e nunca fecha:
fechado abre, recolhido expande e aberto permanece aberto em cliques repetidos.
Use **Fechar** para fechar o menu. Escape fecha o painel desktop somente quando o evento
vem dele e devolve o foco ao hamburger. No estreito, o hamburger abre o menu modal,
o controle de recolher fica oculto e Escape fecha somente a navegação.
Use **Ir para o conteúdo principal** para pular a navegação.
Em telas com largura de até 767,98 px, cada linha vira um cartão com Email e Localização rotulados e
ações Editar e Excluir visíveis. Textos longos quebram sem rolagem horizontal.
Não há atalhos globais adicionais.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Operar

| Tarefa | Comando |
|---|---|
| Estado das unidades | `systemctl status webapp-db.service webapp.service app-proxy.service` |
| Logs da API | `journalctl -u webapp.service -f` ou `podman logs -f webapp-api` |
| Logs do NGINX | `podman logs -f app-proxy-nginx` |
| Logs do PostgreSQL | `podman logs -f webapp-db-postgres` |
| Reiniciar a aplicação | `systemctl restart webapp.service` |
| Testar a configuração NGINX | `podman exec app-proxy-nginx nginx -t` |
| Abrir `psql` | `podman exec -it webapp-db-postgres psql -U webapp_owner -d db_webapp` |

O NGINX resolve `webapp.dns.podman` a cada 10 s.
Por isso, reiniciar o pod `webapp` não exige reiniciar o `app-proxy`.

Os dados ficam nos volumes `webapp-db-data` e `webapp-images`.
Reiniciar ou recriar os pods não apaga dados.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Desenvolver

O backend é um workspace uv. Na raiz do repositório:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Os testes unitários usam um repositório falso e não precisam de banco.
O frontend em `webapp/frontend/` não tem etapa de build. Os testes de navegação,
mensagens e foco usam o `node:test` integrado. O ambiente testado é Linux, Bash 5.1.8
(shell com expansão de glob) e Node.js v24.21.0, verificado por `node --version`.
Essa é uma versão testada, não uma versão mínima declarada. Na raiz do repositório:

```bash
node --test webapp/frontend/tests/dialog-accessibility.test.mjs webapp/frontend/tests/navigation.test.mjs
node --check webapp/frontend/app.js &&
  node --check webapp/frontend/navigation.mjs &&
  node --check webapp/frontend/dialog-accessibility.mjs &&
  node --check webapp/frontend/tests/dialog-accessibility.test.mjs &&
  node --check webapp/frontend/tests/navigation.test.mjs
```

O CSS Core 3.7.0, Rawline, ícones e a ilustração são locais. As origens, licenças e
atribuições estão no [índice de licenças de componentes](../../LICENSES.md); os detalhes
de atualização estão na [referência GOV.BR](./govbr-design-system.md#recursos-incluídos-no-frontend).
Os diálogos nativos mantêm foco e erros dentro da janela durante as operações.
Depois de alterar backend ou frontend, execute o deploy novamente para reconstruir a imagem.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Solução de problemas

| Sintoma | Causa provável | Ação |
|---|---|---|
| Upload retorna `500` com `PermissionError` | volume `webapp-images` sem dono `10001` | faça backup das imagens, remova o volume com os pods parados e execute o deploy |
| `502 Bad Gateway` em `/webapp/` | pod `webapp` parado ou iniciando | `systemctl status webapp.service` e `podman logs webapp-api` |
| Health falha com erro de autenticação no banco | secrets diferentes dos usados na criação do volume | restaure os secrets originais |
| Mudança em SQL de init sem efeito | scripts de init rodam só com volume vazio | aplique a mudança com `psql` ou recrie o volume em ambiente descartável |
| `413 Request Entity Too Large` | imagem acima de 6 MiB no NGINX | envie imagem de até 5 MiB |

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
