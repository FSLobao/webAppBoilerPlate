<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#1-objetivo">Objetivo</a></li>
        <li><a href="#2-pré-requisitos">Pré-requisitos</a></li>
        <li><a href="#3-gerar-a-chave-no-cliente">Gerar a chave no cliente</a></li>
        <li><a href="#4-instalar-a-chave-no-gateway">Instalar a chave no Gateway</a></li>
        <li><a href="#5-conectar-e-verificar">Conectar e verificar</a></li>
        <li><a href="#6-solucionar-problemas">Solucionar problemas</a></li>
        <li><a href="#7-fontes-oficiais">Fontes oficiais</a></li>
    </ol>
</details>

# Chave SSH de acesso ao Gateway

Procedimento para administradores do Gateway e usuários Windows 11, macOS ou Linux.
Use-o quando a verificação indicar que `/etc/gateway/authorized_keys` não existe ou está
vazio. Esta chave permite acesso SSH ao Gateway; ela não é uma chave SSH TUN nem uma chave
de aplicação.

## 1. Objetivo

Gere uma chave Ed25519 no computador cliente, instale somente a chave pública no Gateway e
confirme o acesso pela porta SSH configurada. Mantenha a chave privada no cliente.

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
- Sessão administrativa existente no host Gateway, com permissão para editar
  `/etc/gateway/authorized_keys` e executar `sudo`; `sudoedit` e `ssh-keygen` disponíveis.
- Nome ou endereço do Gateway, conta SSH autorizada e porta SSH configurada.
- Acesso à rede necessária para alcançar o host Gateway.

Os comandos de geração usam a pasta pessoal do cliente e não dependem de uma pasta de
trabalho específica. No Gateway, execute os comandos em um shell Bash com `sudo`.

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

Escolha apenas o procedimento do sistema operacional do cliente. Ao solicitar uma frase
secreta, use uma frase forte ou pressione Enter para não definir uma. Se o arquivo de chave
já existir, não o sobrescreva: escolha outro nome ou faça uma cópia segura antes.

### Windows 11

No PowerShell, crie a pasta SSH, gere a chave e copie a chave pública:

```powershell
New-Item -ItemType Directory -Force "$HOME\.ssh" | Out-Null
ssh-keygen -t ed25519 -a 64 -f "$HOME\.ssh\gateway_ed25519" -C "gateway-login"
Get-Content "$HOME\.ssh\gateway_ed25519.pub" | Set-Clipboard
```

### macOS

No Terminal, crie a pasta SSH, restrinja as permissões, gere a chave e copie a chave pública:

```bash
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
ssh-keygen -t ed25519 -a 64 -f "$HOME/.ssh/gateway_ed25519" -C "gateway-login"
pbcopy < "$HOME/.ssh/gateway_ed25519.pub"
```

### Linux

No Bash, crie a pasta SSH, restrinja as permissões e gere a chave:

```bash
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
ssh-keygen -t ed25519 -a 64 -f "$HOME/.ssh/gateway_ed25519" -C "gateway-login"
```

Se `wl-copy` estiver instalado, copie a chave pública no Wayland:

```bash
wl-copy < "$HOME/.ssh/gateway_ed25519.pub"
```

Se `xclip` estiver instalado, copie a chave pública no X11:

```bash
xclip -selection clipboard < "$HOME/.ssh/gateway_ed25519.pub"
```

Se nenhum comando de área de transferência estiver disponível, exiba a chave pública e
copie sua única linha:

```bash
cat "$HOME/.ssh/gateway_ed25519.pub"
```

Em todos os sistemas, copie somente o conteúdo do arquivo `.pub`. Nunca copie nem envie o
arquivo `gateway_ed25519` sem a extensão `.pub`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 4. Instalar a chave no Gateway

No host Gateway, use a sessão administrativa existente. Crie o arquivo, abra-o para edição
e acrescente a linha pública copiada. Preserve todas as linhas existentes:

```bash
sudo install -d -o root -g root -m 0700 /etc/gateway
sudo touch /etc/gateway/authorized_keys
sudoedit /etc/gateway/authorized_keys
sudo chown root:root /etc/gateway/authorized_keys
sudo chmod 0600 /etc/gateway/authorized_keys
sudo ssh-keygen -lf /etc/gateway/authorized_keys
```

Confirme que `ssh-keygen` exibe a impressão digital da chave Ed25519 adicionada. O arquivo
deve pertencer a `root:root` e ter modo `0600`. Não remova chaves de outros usuários.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 5. Conectar e verificar

No cliente, substitua `gateway-host` pelo nome ou endereço do Gateway. Use a porta
configurada; o exemplo usa `2222`.

No Windows PowerShell:

```powershell
ssh -i "$HOME\.ssh\gateway_ed25519" -p 2222 developer@gateway-host
```

No Terminal do macOS ou no Bash do Linux:

```bash
ssh -i "$HOME/.ssh/gateway_ed25519" -p 2222 developer@gateway-host
```

Antes de aceitar uma nova chave de host, compare sua impressão digital com a fornecida pelo
administrador. Após a autenticação, o cliente abre uma sessão SSH com a conta `developer`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 6. Solucionar problemas

- Se `Get-Command` ou `command -v` não encontrar OpenSSH, instale o cliente OpenSSH
  compatível com o sistema operacional e repita a verificação.
- Se a conexão retornar `Permission denied (publickey)`, confirme o usuário, o caminho da
  chave privada, a porta e se a linha pública completa está em
  `/etc/gateway/authorized_keys`.
- Se a conexão expirar ou recusar a conexão, confirme o endereço, a porta e o acesso de rede
  com o administrador do Gateway.
- Se `ssh-keygen -lf /etc/gateway/authorized_keys` não exibir uma impressão digital válida,
  confirme que o arquivo contém uma linha pública completa por chave.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 7. Fontes oficiais

- [OpenBSD: manual do `ssh-keygen`](https://man.openbsd.org/ssh-keygen)
- [OpenBSD: manual do `ssh`](https://man.openbsd.org/ssh)
- [Microsoft: instalar o OpenSSH no Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
