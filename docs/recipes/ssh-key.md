<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#1-objetivo">Objetivo</a></li>
        <li><a href="#2-pré-requisitos">Pré-requisitos</a></li>
        <li><a href="#3-gerar-a-chave-no-cliente">Gerar a chave no cliente</a></li>
        <li><a href="#4-instalar-a-chave-no-destino">Instalar a chave no destino</a></li>
        <li><a href="#5-configurar-o-cliente-ssh">Configurar o cliente SSH</a></li>
        <li><a href="#6-conectar-e-verificar">Conectar e verificar</a></li>
        <li><a href="#7-solucionar-problemas">Solucionar problemas</a></li>
        <li><a href="#8-fontes-oficiais">Fontes oficiais</a></li>
    </ol>
</details>

# Chaves SSH de acesso ao Gateway e aos containers

Procedimento para desenvolvedores com clientes Windows 11, macOS ou Linux e para os
administradores que instalam as chaves no host. Use-o para acessar por SSH o próprio Gateway
ou qualquer container de aplicação que exponha SSH, inclusive pelo VS Code Remote - SSH.
Estas chaves autenticam o serviço SSH; elas não substituem a autenticação da VPN nem chaves
de aplicação.

## 1. Objetivo

Gere uma chave Ed25519 individual no computador cliente, instale somente a chave pública no
arquivo `authorized_keys` do destino e confirme o acesso. A chave privada permanece no
cliente e nunca é compartilhada, conforme a
[seção 11.3 da arquitetura](../contracts/ARCHITECTURE.md#113-credenciais-dos-destinos).

Os destinos usam os seguintes arquivos no host Gateway:

| Destino | Arquivo de chaves públicas no host | Observação |
| --- | --- | --- |
| Gateway | `/etc/gateway/authorized_keys` | Acesso SSH administrativo ao Gateway. |
| Container de aplicação | `/etc/gateway/application-keys/<container>/authorized_keys` | Caminho padrão; o caminho efetivo é configurável no JSON do deployment. Montado somente leitura em `/home/<account>/.ssh/authorized_keys` no container. |

Use uma chave por destino ou por finalidade. Assim, é possível revogar um acesso sem afetar
os demais.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 2. Pré-requisitos

- Cliente com Windows 11 e PowerShell, macOS e Terminal, ou Linux com Bash.
- Cliente OpenSSH instalado no computador cliente, incluindo `ssh-keygen` e `ssh`.
- Para containers de aplicação: VPN ativa com o cliente Tailscale inscrito no Headscale do
  Gateway, conforme a [seção 11 da arquitetura](../contracts/ARCHITECTURE.md).
- Nome DNS ou endereço do destino, conta SSH autorizada e porta SSH configurada.
- Sessão administrativa no host Gateway, com permissão para executar `sudo`, `nano` e
  `ssh-keygen`. Essa sessão é necessária apenas para instalar a chave pública.

Os comandos de geração usam a pasta pessoal do cliente e não dependem de uma pasta de
trabalho específica. No host Gateway, execute os comandos em um shell Bash com `sudo`.

No PowerShell, confirme que o cliente OpenSSH está disponível:

```powershell
Get-Command ssh, ssh-keygen
```

No Terminal do macOS ou no Bash do Linux, confirme que os comandos estão disponíveis:

```bash
command -v ssh && command -v ssh-keygen
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

## 3. Gerar a chave no cliente

Os comandos usam os seguintes marcadores; substitua-os antes de executar:

| Marcador | Substituir por | Exemplo |
| --- | --- | --- |
| `<destino>` | Nome curto do Gateway ou do container, usado no nome do arquivo da chave. | `gateway`, `app-api` |
| `<usuario>` | Seu identificador, gravado como comentário da chave pública. | `fulano` |

Escolha apenas o procedimento do sistema operacional do cliente. Ao solicitar uma frase
secreta, use uma frase forte ou pressione Enter para não definir uma. Se o arquivo de chave
já existir, não o sobrescreva: escolha outro nome ou faça uma cópia segura antes.

### Windows 11

No PowerShell, crie a pasta SSH, gere a chave e copie a chave pública:

```powershell
New-Item -ItemType Directory -Force "$HOME\.ssh" | Out-Null
ssh-keygen -t ed25519 -a 64 -f "$HOME\.ssh\<destino>_ed25519" -C "<usuario>@<destino>"
Get-Content "$HOME\.ssh\<destino>_ed25519.pub" | Set-Clipboard
```

### macOS

No Terminal, crie a pasta SSH, restrinja as permissões, gere a chave e copie a chave pública:

```bash
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
ssh-keygen -t ed25519 -a 64 -f "$HOME/.ssh/<destino>_ed25519" -C "<usuario>@<destino>"
pbcopy < "$HOME/.ssh/<destino>_ed25519.pub"
```

### Linux

No Bash, crie a pasta SSH, restrinja as permissões e gere a chave:

```bash
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
ssh-keygen -t ed25519 -a 64 -f "$HOME/.ssh/<destino>_ed25519" -C "<usuario>@<destino>"
```

Copie a chave pública com o utilitário de área de transferência disponível: `wl-copy` no
Wayland ou `xclip` no X11.

```bash
wl-copy < "$HOME/.ssh/<destino>_ed25519.pub"
xclip -selection clipboard < "$HOME/.ssh/<destino>_ed25519.pub"
```

Se nenhum desses utilitários estiver instalado, exiba a chave pública e copie sua única
linha:

```bash
cat "$HOME/.ssh/<destino>_ed25519.pub"
```

Em todos os sistemas, envie ao administrador somente o conteúdo do arquivo `.pub`. Nunca
copie nem envie o arquivo `<destino>_ed25519` sem a extensão `.pub`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 4. Instalar a chave no destino

No host Gateway, use a sessão administrativa existente. Defina o arquivo de chaves do
destino conforme a tabela da [seção 1](#1-objetivo). Para um container, use o caminho
configurado no JSON do deployment, se ele diferir do padrão.

```bash
KEYS_FILE=/etc/gateway/authorized_keys                                  # Gateway
KEYS_FILE=/etc/gateway/application-keys/<container>/authorized_keys     # container
```

Execute somente a linha do destino desejado. Caso o arquivo não exista, crie-o com dono
`root:root` e modo `0600`:

```bash
sudo install -d -o root -g root -m 0700 "$(dirname "$KEYS_FILE")"
sudo install -o root -g root -m 0600 /dev/null "$KEYS_FILE"
```

Execute o segundo comando somente se o arquivo ainda não existir, pois ele esvazia um
arquivo existente.

Edite o arquivo, adicione a chave pública recebida em uma nova linha e confira o resultado:

```bash
sudo nano "$KEYS_FILE"
sudo ssh-keygen -lf "$KEYS_FILE"
```

Confirme que `ssh-keygen` exibe a impressão digital da chave Ed25519 adicionada, com o
comentário `<usuario>@<destino>`. O arquivo deve continuar com dono `root:root` e modo
`0600`. Não remova chaves de outros usuários.

O `sshd` lê o arquivo a cada autenticação, portanto não é necessário reiniciar o Gateway nem
o container. Para revogar um acesso, remova a linha correspondente do mesmo arquivo.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 5. Configurar o cliente SSH

Opcionalmente, registre o destino no arquivo de configuração do cliente. O VS Code
Remote - SSH lê esse mesmo arquivo e passa a listar o destino pelo nome em `Host`.

| Sistema | Arquivo de configuração |
| --- | --- |
| Windows 11 | `$HOME\.ssh\config` |
| macOS e Linux | `~/.ssh/config` |

Adicione um bloco por destino, substituindo os marcadores. O exemplo usa a porta `2222`;
use a porta configurada para o destino.

```text
Host <destino>
    HostName <nome-dns-ou-endereco>
    User <conta>
    Port 2222
    IdentityFile ~/.ssh/<destino>_ed25519
    IdentitiesOnly yes
```

`IdentitiesOnly yes` faz o cliente oferecer apenas a chave indicada, evitando falhas por
excesso de tentativas quando existem várias chaves.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 6. Conectar e verificar

Para containers de aplicação, ative a VPN antes de conectar. Se configurou o cliente na
[seção 5](#5-configurar-o-cliente-ssh), conecte pelo nome do bloco `Host`:

```bash
ssh <destino>
```

Sem o arquivo de configuração, informe chave, porta, conta e endereço. No Windows
PowerShell:

```powershell
ssh -i "$HOME\.ssh\<destino>_ed25519" -p 2222 <conta>@<nome-dns-ou-endereco>
```

No Terminal do macOS ou no Bash do Linux:

```bash
ssh -i "$HOME/.ssh/<destino>_ed25519" -p 2222 <conta>@<nome-dns-ou-endereco>
```

Antes de aceitar uma nova chave de host, compare sua impressão digital com a fornecida pelo
administrador. Após a autenticação, o cliente abre uma sessão SSH com a conta informada.

No VS Code, execute o comando **Remote-SSH: Connect to Host...** e escolha o nome do bloco
`Host`.

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

- Se `Get-Command` ou `command -v` não encontrar OpenSSH, instale o cliente OpenSSH
  compatível com o sistema operacional e repita a verificação.
- Se a conexão retornar `Permission denied (publickey)`, confirme a conta, o caminho da
  chave privada, a porta e se a linha pública completa está no arquivo de chaves do destino
  correto. Execute `ssh -v` para ver qual chave o cliente oferece.
- Se um container não aceitar uma chave recém-adicionada, confirme no JSON do deployment o
  caminho do arquivo montado. Editores que substituem o arquivo em vez de alterá-lo podem
  desfazer a montagem de arquivo; nesse caso, recrie o container.
- Se a conexão expirar ou for recusada, confirme a VPN, o nome DNS, a porta e o acesso de
  rede com o administrador do Gateway.
- Se `ssh-keygen -lf "$KEYS_FILE"` não exibir uma impressão digital válida, confirme que o
  arquivo contém uma linha pública completa por chave.
- No macOS ou Linux, se o cliente recusar a chave privada por permissões abertas, execute
  `chmod 600 "$HOME/.ssh/<destino>_ed25519"`.

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

- [OpenBSD: manual do `ssh-keygen`](https://man.openbsd.org/ssh-keygen)
- [OpenBSD: manual do `ssh`](https://man.openbsd.org/ssh)
- [OpenBSD: manual do `ssh_config`](https://man.openbsd.org/ssh_config)
- [Microsoft: instalar o OpenSSH no Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)
- [VS Code: desenvolvimento remoto com SSH](https://code.visualstudio.com/docs/remote/ssh)

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
