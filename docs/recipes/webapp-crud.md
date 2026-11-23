<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#objetivo">Objetivo</a></li>
        <li><a href="#pré-requisitos">Pré-requisitos</a></li>
        <li><a href="#implantar">Implantar</a></li>
        <li><a href="#atualizar">Atualizar</a></li>
        <li><a href="#alternativa-legada-rootful">Alternativa legada rootful</a></li>
        <li><a href="#verificar">Verificar</a></li>
        <li><a href="#operar">Operar</a></li>
        <li><a href="#desenvolver">Desenvolver</a></li>
        <li><a href="#solução-de-problemas">Solução de problemas</a></li>
    </ol>
</details>

# Receita: aplicação web CRUD de usuários

## Objetivo

Esta receita implanta a SPA de cadastro de usuários em um host Podman rootless.
O fluxo padrão usa a conta de operação rootless e suas unidades Quadlet de usuário.
`podman_user` é um exemplo de nome para essa conta.

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

- Linux com systemd e Podman 5 com Quadlet.
- Conta não root dedicada ao Podman rootless, com ranges em `/etc/subuid` e `/etc/subgid`
  e linger habilitado. `podman_user` é um exemplo válido; o UID pode variar.
- Sessão rootless com Podman, user bus e `systemctl --user` funcionais.
- Rede rootless `gateway-vpn` com DNS e ao menos uma subnet IPv4 habilitados. O CIDR efetivo
  vem das variáveis do deploy do Gateway; `10.100.0.0/24` é um exemplo.
- Preparação do host conforme a [receita rootless do Gateway](gateway-headscale-podman-rootless.md).
- SELinux `Disabled`.
- Porta TCP 8080 livre no host.
- Chave pública SSH Ed25519 do operador para acesso de desenvolvimento aos containers.
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
> Os secrets em `~/.local/share/webapp/secrets/` e os volumes guardam o estado da aplicação.
> Não apague os secrets com o volume `webapp-db-data` presente. O script recusa continuar
> nesse caso, porque as senhas novas não corresponderiam ao banco.

Execute os passos desta seção com a conta que controla o Podman rootless e as unidades de
usuário. O exemplo usa `podman_user`; substitua-a pela conta adotada no host.

Instale somente a chave pública SSH no arquivo compartilhado pela stack:

```bash
"${HOME}/webAppBoilerPlate/deploy/scripts/install-webapp-ssh-key.sh" \
  --public-key-file "${HOME}/.ssh/webapp_ed25519.pub"
```

O destino rootless padrão é `~/.local/share/webapp/secrets/authorized_keys`. O script preserva
chaves existentes e não duplica a mesma chave. Esta stack de desenvolvimento monta o mesmo
arquivo somente para leitura nos três containers e permite login SSH somente como `root` por
chave pública. Não reutilize esse perfil em produção.

Na conta dedicada, obtenha uma cópia versionada do repositório na pasta home:

```bash
git clone https://github.com/FSLobao/webAppBoilerPlate.git "${HOME}/webAppBoilerPlate"
```

Em uma sessão de login dessa mesma conta, com user bus ativo, execute o script:

```bash
"${HOME}/webAppBoilerPlate/deploy/scripts/deploy-webapp-rootless.sh" \
  --source "${HOME}/webAppBoilerPlate"
```

Não execute o script com `sudo`. Ele identifica o usuário executor e armazena configurações,
secrets, volumes e unidades no escopo rootless dessa conta.

O script é idempotente. Ele executa, nesta ordem:

1. verifica o usuário executor, comandos, user bus, linger, DNS e subnet existente em `gateway-vpn`;
2. atualiza as imagens-base e constrói as três imagens locais com `sshd`;
3. cria os secrets ausentes em `~/.local/share/webapp/secrets/` sem sobrescrever os existentes;
4. instala YAML, SQL de inicialização, configuração NGINX e unidades Quadlet de usuário;
5. cria os volumes `webapp-db-data` e `webapp-images`;
6. executa `systemctl --user daemon-reload` e inicia ou reinicia as três unidades;
7. espera até 90 s pelo health da API pelo NGINX.

O Podman atribui endereços IPv4 dinamicamente aos pods. O deploy configura apenas aliases DNS
estáveis; não derive nem fixe IPs dos serviços da webapp no script.

Os listeners SSH usam TCP 22 dentro de `gateway-vpn`, sem publicação de porta no host:

| Destino | Comando SSH |
| --- | --- |
| API | `ssh -i ~/.ssh/webapp_ed25519 root@webapp.dev.anatel` |
| PostgreSQL | `ssh -i ~/.ssh/webapp_ed25519 root@webapp-db.dev.anatel` |
| NGINX | `ssh -i ~/.ssh/webapp_ed25519 root@app-proxy.dev.anatel` |

Os containers continuam não expondo SSH fora da VPN. A autenticação SSH é independente da
inscrição do dispositivo no Headscale.

Para reaplicar apenas a configuração sem reconstruir a imagem, acrescente `--no-build`.
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

## Atualizar

Execute a atualização com a mesma conta usada na implantação. O script não executa `git pull`;
ele aplica somente o conteúdo do checkout informado por `--source`.

Atualize o checkout quando quiser incorporar alterações versionadas no repositório. Isso inclui
mudanças no frontend, backend, dependências, Containerfiles, scripts, YAML, SQL, NGINX, Quadlet
ou documentação operacional:

```bash
cd "${HOME}/webAppBoilerPlate"
git pull --ff-only
```

Não execute `git pull` quando o checkout local já contém a revisão desejada ou quando pretende
implantar intencionalmente alterações locais não versionadas. `git pull` também não é necessário
para substituir apenas a chave SSH ou outro secret externo ao repositório.

Reconstrua as imagens e reaplique a configuração:

```bash
"${HOME}/webAppBoilerPlate/deploy/scripts/deploy-webapp-rootless.sh" \
  --source "${HOME}/webAppBoilerPlate"
```

O script preserva `webapp-db-data`, `webapp-images`, as senhas existentes e
`authorized_keys`. Ele reinicia a API e o proxy; o PostgreSQL reinicia somente quando seu YAML
ou unidade Quadlet mudou, ou quando existe um marcador de reinício pendente.

Use `--no-build` somente para reaplicar configuração quando nenhum Containerfile, frontend,
backend, dependência ou entrypoint mudou:

```bash
"${HOME}/webAppBoilerPlate/deploy/scripts/deploy-webapp-rootless.sh" \
  --source "${HOME}/webAppBoilerPlate" \
  --no-build
```

Depois, confirme unidades, containers e health:

```bash
systemctl --user status webapp-db.service webapp.service app-proxy.service --no-pager
podman ps --pod
curl -fsS http://localhost:8080/webapp/api/health
```

Na alternativa rootful, atualize o checkout na conta que administra o repositório e reaplique:

```bash
sudo deploy/scripts/deploy-webapp.sh
```

Para a variante rootful, use `sudo deploy/scripts/deploy-webapp.sh --no-build` somente com as
mesmas restrições descritas acima.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Alternativa legada rootful

> [!WARNING]
> Esta variante usa Podman rootful e não deve operar no mesmo host que o deploy rootless.
> Ela usa a rede `podman`, unidades systemd globais e secrets em `/etc/webapp/secrets/`.

Use esta alternativa somente em host Linux com Podman 5, rede padrão `podman` com DNS
habilitado e SELinux `Disabled`.

Na raiz do repositório, execute como administrador:

```bash
sudo deploy/scripts/install-webapp-ssh-key.sh \
  --public-key-file /caminho/para/webapp_ed25519.pub
sudo deploy/scripts/deploy-webapp.sh
```

Na variante rootful, o arquivo compartilhado é `/etc/webapp/secrets/authorized_keys`.

O script rootful é idempotente. Ele escreve configuração em `/etc`, instala unidades em
`/etc/containers/systemd` e usa `systemctl` global. Para manter a imagem existente, use:

```bash
sudo deploy/scripts/deploy-webapp.sh --no-build
```

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

### Tabela de usuários

A tabela da tela principal funciona assim. Os desvios em relação ao padrão GOV.BR estão em [Desvios da tabela de usuários](./govbr-design-system.md#desvios-da-tabela-de-usuários).

| Recurso | Comportamento |
| --- | --- |
| Busca | A lupa do cabeçalho da tabela abre o campo de busca. A busca cobre Nome, Email e Localização. O campo `id` não é pesquisado. A comparação ignora maiúsculas, minúsculas e acentos. Com o campo aberto, ele ocupa uma linha própria abaixo dos controles do cabeçalho, em todas as larguras. |
| Termos | Cada palavra separada por espaço é um termo, e os termos são combinados com OR. Texto entre aspas é uma frase única, por exemplo `"Rio de Janeiro"`. Pressione Enter para aceitar os termos digitados. O campo é limpo, e termo repetido não cria novo chip. |
| Chips | Cada termo aceito vira um chip com o botão "×" à esquerda do texto. O nome acessível do botão começa com "Remover", seguido do termo, por exemplo "Remover ana". Remover um chip devolve o foco ao campo de busca. Os trechos encontrados são destacados nas células. A área de chips rola na vertical: altura máxima de 172 px em larguras de até 480 px, e de 120 px acima disso. |
| Fechar a busca | Fechar pela lupa, pelo botão "Fechar busca" ou ao abrir o menu limpa termos, chips e texto, e restaura a lista completa. |
| Ordenação | Clicar no cabeçalho de Nome, Email ou Localização segue o ciclo ascendente, descendente, ascendente. A partir de 768 px, o cabeçalho ativo fica destacado e o estado é informado por `aria-sort`; o sentido da ordenação não aparece visualmente nos cabeçalhos. Foto e Ações não são ordenáveis. |
| Menu de reticências | O botão de reticências, rotulado "Mais opções da tabela", abre o menu com "Adicionar usuário" e o grupo "Ordenar", com Nome, Email e Localização. Escolher uma coluna equivale a clicar no cabeçalho dela. A coluna ativa fica marcada. |
| Cartões | Abaixo de 768 px, cada rótulo de Nome, Email e Localização tem dois triângulos à direita, com a direção ativa destacada. Os triângulos não são interativos; para ordenar nos cartões, use o menu de reticências. |
| Novo usuário | O botão Novo usuário fica fora da tabela, e a mesma ação está no menu de reticências. |
| Paginação | Exibe 10, 50 ou 100 itens por página, com padrão 10. Em "Exibir", escolha o tamanho; em "Página", escolha a página em uma lista; use os botões de anterior e próxima. |
| Contador | Mostra o intervalo e o total exibido, por exemplo "1-10 de 25 itens". Sem resultados, mostra "Nenhum item". |
| Limite de 500 | O limite aplica-se depois da filtragem. Com mais de 500 resultados filtrados, o contador mostra o conjunto exibido (por exemplo, "1-10 de 500 itens" na página 1), um banner informa o total real, e a paginação percorre somente os 500 exibidos. |
| Sem resultados | Quando a busca não encontra usuários, é exibida a mensagem "Nenhum usuário encontrado para a busca informada." |
| Carregamento | Enquanto a lista é buscada, a região mostra "Carregando usuários" com spinner em CSS e o contêiner da tabela fica com `aria-busy="true"`. Com redução de movimento ativa, o spinner não gira e pulsa de opacidade. |

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

Execute os comandos desta seção com a mesma conta usada no deploy, em sessão rootless com
user bus ativo. No exemplo, essa conta é `podman_user`.

| Tarefa | Comando |
|---|---|
| Estado das unidades | `systemctl --user status webapp-db.service webapp.service app-proxy.service` |
| Logs da API | `journalctl --user -u webapp.service -f` ou `podman logs -f webapp-api` |
| Logs do NGINX | `podman logs -f app-proxy-nginx` |
| Logs do PostgreSQL | `podman logs -f webapp-db-postgres` |
| Reiniciar a aplicação | `systemctl --user restart webapp.service` |
| Testar a configuração NGINX | `podman exec app-proxy-nginx nginx -t` |

### Inspecionar o banco de dados

O banco `db_webapp` possui dois papéis de login:

| Papel | Uso | Permissões |
| --- | --- | --- |
| `webapp_owner` | Superusuário criado pela imagem PostgreSQL como `POSTGRES_USER`; administração, diagnóstico e DDL. | Controle total do banco. |
| `webapp_api` | Papel da API FastAPI. | `CONNECT`, uso do schema `webapp` e `SELECT`, `INSERT`, `UPDATE`, `DELETE` em `webapp.TB_USUARIO`; sem DDL. |

As senhas são secrets externos ao Git. Na implantação rootless, ficam em
`~/.local/share/webapp/secrets/`; na rootful, ficam em `/etc/webapp/secrets/`.

| Arquivo no host | Papel correspondente | Montagem no container |
| --- | --- | --- |
| `postgres-password` | `webapp_owner` | `webapp-db-postgres:/run/secrets/postgres-password` |
| `db-init-api-password` | `webapp_api` durante a inicialização | `webapp-db-postgres:/run/secrets/api-db-password` |
| `api-db-password` | `webapp_api` durante a execução da API | `webapp-api:/run/secrets/api-db-password` |

`db-init-api-password` e `api-db-password` contêm o mesmo valor e são cópias com proprietários
diferentes para atender aos UIDs dos containers. Não copie, versione, registre em logs ou publique
o conteúdo desses arquivos. Não recrie os secrets quando `webapp-db-data` já existe.

Para inspeção administrativa a partir do host rootless, use o socket local do container:

```bash
podman exec -it webapp-db-postgres \
  psql -U webapp_owner -d db_webapp
```

Para validar a perspectiva e os privilégios do papel da API:

```bash
podman exec -it webapp-db-postgres \
  psql -U webapp_api -d db_webapp
```

Dentro da sessão, consultas seguras de leitura incluem:

```sql
\conninfo
\du
\dn+
\dt+ webapp.*
SELECT * FROM webapp.TB_USUARIO ORDER BY ID_USUARIO;
```

Para acessar diretamente pela VPN, conecte primeiro por SSH ao container PostgreSQL e use o secret
montado localmente, sem exibir a senha:

```bash
ssh -i ~/.ssh/webapp_ed25519 root@webapp-db.dev.anatel
PGPASSWORD="$(cat /run/secrets/postgres-password)" \
  psql -h 127.0.0.1 -U webapp_owner -d db_webapp
```

Use `webapp_owner` apenas para diagnóstico ou manutenção autorizada. Para reproduzir o acesso da
API pela VPN, use `webapp_api` e leia a senha de `/run/secrets/api-db-password` no container
PostgreSQL:

```bash
PGPASSWORD="$(cat /run/secrets/api-db-password)" \
  psql -h 127.0.0.1 -U webapp_api -d db_webapp
```

O primeiro exemplo remoto usa TCP e autentica a senha; os exemplos `podman exec` usam o socket
local. Faça backup antes de executar DDL ou operações destrutivas.

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

Resultado esperado:

- `uv sync`: termina com código `0` depois de sincronizar as dependências.
- `uv run ruff check .`: termina com código `0` sem apontar violações.
- `uv run ruff format --check .`: termina com código `0` sem apontar arquivos que precisam de
  formatação.
- `uv run pytest`: termina com código `0`, sem falhas ou erros. A quantidade de testes depende
  do conjunto presente no checkout.

Os testes unitários usam um repositório falso e não precisam de banco.
O frontend em `webapp/frontend/` não tem etapa de build. Os testes de navegação,
mensagens, foco e tabela usam o `node:test` integrado.

Execute os comandos a seguir com Bash, na raiz do repositório:

```bash
node --test webapp/frontend/tests/*.test.mjs
node --check webapp/frontend/app.js &&
  node --check webapp/frontend/table-model.mjs &&
  node --check webapp/frontend/navigation.mjs &&
  node --check webapp/frontend/dialog-accessibility.mjs &&
  node --check webapp/frontend/tests/dialog-accessibility.test.mjs &&
  node --check webapp/frontend/tests/navigation.test.mjs &&
  node --check webapp/frontend/tests/helpers/css-scanner.mjs &&
  node --check webapp/frontend/tests/css-scanner.test.mjs
```

Resultado esperado: `node --test` termina com código `0` e sem falhas; o resumo informa os
resultados de todos os testes em `webapp/frontend/tests/`, sem contagem presumida. `node --check` termina com código `0`
sem erros de sintaxe e sem saída, nos módulos listados acima.

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
| `502 Bad Gateway` em `/webapp/` | pod `webapp` parado ou iniciando | `systemctl --user status webapp.service` e `podman logs webapp-api` |
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
