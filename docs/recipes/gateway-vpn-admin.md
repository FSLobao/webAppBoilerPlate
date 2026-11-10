<details id="top">
    <summary>Índice</summary>
    <!-- cspell:disable -->
    <ol>
        <li><a href="#1-objetivo-e-escopo">1. Objetivo e escopo</a></li>
        <li><a href="#2-acesso-e-pré-requisitos">2. Acesso e pré-requisitos</a></li>
        <li><a href="#3-cadastrar-usuário-e-emitir-credencial">3. Cadastrar usuário e emitir credencial</a></li>
        <li><a href="#4-inscrever-e-verificar-dispositivos">4. Inscrever e verificar dispositivos</a></li>
        <li><a href="#5-revogar-credenciais-e-dispositivos">5. Revogar credenciais e dispositivos</a></li>
        <li><a href="#6-acessar-o-headplane-e-verificar-o-serviço">6. Acessar o Headplane e verificar o serviço</a></li>
        <li><a href="#7-solucionar-problemas">7. Solucionar problemas</a></li>
        <li><a href="#8-fontes-oficiais">8. Fontes oficiais</a></li>
    </ol>
    <!-- cspell:enable -->
</details>

# Administração do Gateway VPN

## 1. Objetivo e escopo

Esta receita orienta operadores autorizados na administração do Headscale e do Headplane. Ela
cobre cadastro de usuários, emissão de credenciais para inscrição de clientes, consulta e
revogação de dispositivos e acesso à interface administrativa.

Um usuário Headscale não é uma conta Linux. Uma chave de pré-autorização permite inscrever um
dispositivo; não é a chave privada WireGuard. O cliente Tailscale gera a chave privada localmente.
Emita uma chave individual para cada dispositivo, com uso único e validade curta.

O cadastro e a inscrição não liberam automaticamente todos os serviços. Acesso a rotas, DNS e
portas depende da configuração e das aprovações do Gateway. Os comandos desta receita correspondem
ao Headscale v0.29.6 usado pela imagem atual. Confira a versão implantada antes de aplicar esta
receita após uma atualização.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 2. Acesso e pré-requisitos

Execute os comandos em Bash, no host Linux onde o container `gateway` está ativo. Use a mesma conta
que administra o Podman do Gateway:

- **Rootless:** execute como `<GATEWAY_USER>`.
- **Rootful:** execute como `root`.

Não use `sudo` para acessar um Gateway rootless: isso pode selecionar outro armazenamento Podman.
Consulte a [receita rootless](gateway-headscale-podman-rootless.md) ou a
[receita rootful](gateway-headscale-podman-rootfull.md) para confirmar a variante e o contexto.

Confirme que o container está saudável antes de emitir credenciais:

```bash
podman inspect --format '{{.State.Health.Status}}' gateway
```

O resultado esperado é `healthy`. Se o comando falhar ou retornar outro estado, pare e consulte os
logs e o procedimento de implantação da variante.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 3. Cadastrar usuário e emitir credencial

Confirme que o usuário ainda não existe e cadastre-o no Headscale:

```bash
podman exec gateway headscale users list
podman exec gateway headscale users create '<NOME_DO_USUÁRIO>'
podman exec gateway headscale users list
```

Anote o ID associado ao novo usuário. Use esse ID para emitir uma chave de inscrição individual:

```bash
HEADSCALE_USER_ID='<ID_DO_USUÁRIO>'
umask 077
AUTH_KEY_FILE="$(mktemp)"
trap 'rm -f -- "$AUTH_KEY_FILE"' EXIT
podman exec gateway headscale preauthkeys create \
  --user "$HEADSCALE_USER_ID" \
  --expiration 1h > "$AUTH_KEY_FILE" &&
  printf 'Credencial temporária salva em: %s\n' "$AUTH_KEY_FILE"
```

O arquivo temporário é criado com acesso restrito. O comando não exibe a chave no terminal nem a
coloca no histórico do shell. Execute-o em uma sessão Bash dedicada; o `trap` remove o arquivo
quando a sessão termina. Se a emissão falhar, não transfira o arquivo.

Importe o arquivo em um canal de segredos aprovado e entregue a credencial ao usuário por esse
canal. Não a envie por Git, tickets, mensagens comuns ou histórico do shell. Após a transferência,
remova a cópia local:

```bash
rm -f -- "$AUTH_KEY_FILE"
```

A chave expira em uma hora e não é reutilizável. Se o usuário precisar inscrever outro dispositivo,
emita outra chave para o mesmo ID. Nunca compartilhe a chave privada gerada pelo cliente.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 4. Inscrever e verificar dispositivos

Oriente o usuário a seguir a [receita do cliente VPN](gateway-vpn-client.md). Ela descreve a
configuração por sistema operacional, a confiança na CA, a inscrição com o arquivo de chave e os
testes de conectividade.

Depois da inscrição, confirme que o dispositivo aparece associado ao usuário esperado:

```bash
podman exec gateway headscale nodes list
```

Uma chave de pré-autorização permite inscrever o dispositivo, mas não aprova rotas anunciadas por
ele. Aprove somente a rota do Gateway prevista na receita da variante; não aprove rota default nem
rotas solicitadas sem autorização.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 5. Revogar credenciais e dispositivos

Liste as chaves de pré-autorização para localizar uma chave ainda não usada. Identifique-a pelo ID,
usuário e validade; não copie o segredo em relatórios:

```bash
podman exec gateway headscale preauthkeys list
```

Expire uma chave que não deve mais ser usada:

```bash
AUTH_KEY_ID='<ID_DA_CHAVE>'
podman exec gateway headscale preauthkeys expire --id "$AUTH_KEY_ID"
```

Para bloquear um dispositivo perdido ou comprometido, localize seu ID e expire o nó:

```bash
podman exec gateway headscale nodes list
NODE_ID='<ID_DO_NÓ>'
podman exec gateway headscale nodes expire --identifier "$NODE_ID"
```

A expiração mantém o registro do dispositivo e exige nova autenticação. Emita uma nova chave
somente depois de confirmar a identidade do usuário e a autorização do dispositivo. Para encerrar
uma conta inteira, siga o processo de desligamento aprovado; não use a exclusão de usuário para
revogar apenas um dispositivo.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 6. Acessar o Headplane e verificar o serviço

O Headplane é a interface de administração e deve ser acessado pela VPN em
`https://dev-gateway.dev.anatel/admin`, ou pelo endereço configurado no Gateway. A chave de API do
Headscale usada pelo operador é diferente da chave de inscrição do cliente. Gere uma chave com
validade limitada e transfira-a por um canal de segredos aprovado:

```bash
umask 077
HEADPLANE_API_KEY_FILE="$(mktemp)"
trap 'rm -f -- "$HEADPLANE_API_KEY_FILE"' EXIT
podman exec gateway headscale apikeys create --expiration 90d > "$HEADPLANE_API_KEY_FILE" &&
  printf 'Chave administrativa temporária salva em: %s\n' "$HEADPLANE_API_KEY_FILE"
```

Use uma sessão Bash dedicada. Importe a chave no fluxo de autenticação do Headplane sem exibi-la no
terminal e remova a cópia local depois da transferência:

```bash
rm -f -- "$HEADPLANE_API_KEY_FILE"
```

Confirme o estado e consulte os logs no contexto correto do Podman:

```bash
podman inspect --format '{{.State.Health.Status}}' gateway
podman logs --tail 100 gateway
```

Para a unidade do sistema, use `systemctl status gateway.service --no-pager` na variante rootful.
Na variante rootless, execute como `<GATEWAY_USER>` e use
`systemctl --user status gateway.service --no-pager`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 7. Solucionar problemas

| Sintoma | Verificação ou ação |
| --- | --- |
| Usuário não aparece no Headscale | Execute `users list` no mesmo contexto Podman do Gateway e confira o nome. |
| Cliente rejeita a chave | Confira `preauthkeys list` para uso e expiração; emita uma chave nova de uso único. |
| Dispositivo não aparece | Confirme que o cliente alcança o FQDN Headscale em TCP 443 e siga a receita do cliente VPN. |
| Dispositivo conecta, mas não acessa o serviço | Confira o nó, a rota do Gateway aprovada, o DNS e a porta liberada; não amplie rotas sem autorização. |
| Headplane não abre | Confirme que o cliente está na VPN, o endereço configurado está correto e o container está `healthy`. |

Se um teste falhar, preserve a saída de erro sem incluir chaves ou outros segredos. Consulte os
logs do Gateway e o procedimento da variante antes de alterar rede, firewall, TLS ou regras de
acesso.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 8. Fontes oficiais

- [Headscale v0.29.6 — gerenciamento de usuários](https://github.com/juanfont/headscale/blob/v0.29.6/cmd/headscale/cli/users.go)
- [Headscale v0.29.6 — chaves de pré-autorização](https://github.com/juanfont/headscale/blob/v0.29.6/cmd/headscale/cli/preauthkeys.go)
- [Headscale v0.29.6 — gerenciamento de nós e rotas](https://github.com/juanfont/headscale/blob/v0.29.6/cmd/headscale/cli/nodes.go)
- [Tailscale — chaves de autenticação](https://tailscale.com/docs/features/access-control/auth-keys)
- [Receita rootless do Gateway](gateway-headscale-podman-rootless.md)
- [Receita rootful do Gateway](gateway-headscale-podman-rootfull.md)
- [Receita do cliente VPN](gateway-vpn-client.md)

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
