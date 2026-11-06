<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#configuração-do-host-etapa-1-root">Configuração do host (etapa 1, root)</a></li>
        <li><a href="#1-objetivo-status-e-limites">Objetivo, status e limites</a></li>
        <li><a href="#2-inventário">Inventário</a></li>
        <li><a href="#3-pré-requisitos-e-descoberta">Pré-requisitos e descoberta</a></li>
        <li><a href="#4-preparar-a-conta-rootless-root">Preparar a conta rootless (root)</a></li>
        <li><a href="#5-prova-de-conceito-descartável">Prova de conceito descartável</a></li>
        <li><a href="#6-preparar-configurações">Preparar configurações</a></li>
        <li><a href="#7-rede-rootless-e-rota-de-retorno">Rede rootless e rota de retorno</a></li>
        <li><a href="#8-instalar-unidades-e-iniciar">Instalar unidades e iniciar</a></li>
        <li><a href="#9-inscrever-o-gateway-e-acessar-o-headplane">Inscrever o Gateway e acessar o Headplane</a></li>
        <li><a href="#10-testes-funcionais-e-gates">Testes funcionais e gates</a></li>
        <li><a href="#11-rollback-e-limpeza">Rollback e limpeza</a></li>
        <li><a href="#12-fontes-oficiais">Fontes oficiais</a></li>
    </ol>
</details>

# Gateway VPN com Headscale, Headplane e Tailscale — alvo rootless

> **Alvo rootless.** A alternativa rootful está implementada e mantida na [receita rootful](gateway-headscale-podman-rootfull.md).

## Configuração do host (etapa 1, root)

Execute como `root`, uma vez por host, a partir da raiz do repositório. Confira primeiro o plano;
aplique a preparação somente depois de revisar a saída:

```bash
sudo deploy/scripts/prepare-rootless-host.sh --check
```

```bash
sudo deploy/scripts/prepare-rootless-host.sh
```

O script instala `net.ipv4.ip_unprivileged_port_start=443` em
`/etc/sysctl.d/90-rootless-ports.conf` e aplica o valor. Assim, qualquer usuário não privilegiado
pode vincular portas TCP/UDP 443 a 1023; portas abaixo de 443 continuam privilegiadas. Este sysctl
global é o mecanismo aprovado.

O mesmo script desativa `firewalld` e `nftables` quando presentes e define `SELINUX=disabled` em
`/etc/selinux/config`. Isso altera o firewall e a política do host. O código de saída `3` indica
que é necessário reiniciar; conclua o reboot antes da etapa rootless.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 1. Objetivo, status e limites

Esta receita descreve uma instalação **nova** do Gateway como usuário local dedicado `<GATEWAY_USER>` com Podman rootless, Quadlet e a bridge exclusiva `gateway-vpn`. Sugestão de conta: `podman_user`. Use Bash a partir da raiz do repositório, com as ferramentas indicadas em cada etapa.

| Placeholder | Descrição | Como obter | Exemplo |
| --- | --- | --- | --- |
| `<GATEWAY_USER>` | Conta local dedicada ao Podman rootless | Defina a conta aprovada e use o mesmo valor em `GATEWAY_USER` | `podman_user` |
| `<GATEWAY_HOME>` | Caminho absoluto da home da conta | Leia o sexto campo de `getent passwd "$GATEWAY_USER"` | `/home/podman_user` |
| `SUBUID_RANGE`, `SUBGID_RANGE` | Faixas exclusivas alocadas à conta | Inspecione `/etc/subuid` e `/etc/subgid`; escolha intervalos sem sobreposição | `200000-265535` |
| `<ROOTLESS_SUBNET>` | Subnet dedicada da bridge rootless | Planeje sem sobreposição com rotas, LAN, VPN e redes corporativas | `10.90.0.0/24` |
| `<ROOTLESS_BRIDGE_IP>` | Gateway da bridge e resolver Aardvark | Escolha dentro de `<ROOTLESS_SUBNET>` e confirme com `podman network inspect` | `10.90.0.1` |
| `<ROOTLESS_BRIDGE_IFACE>` | Interface da bridge dentro da namespace rootless | `podman unshare --rootless-netns /usr/sbin/ip -4 addr` | `podman1` |
| `<GATEWAY_IP>` | IP estático do container Gateway | Escolha livre dentro de `<ROOTLESS_SUBNET>`, diferente do bridge | `10.90.0.2` |
| `<VPN_PREFIX>` | Prefixo VPN anunciado e usado na rota de retorno | Defina dentro do prefixo Headscale e sem sobreposição | `100.96.0.0/24` |
| `<HEADSCALE_FQDN>` | FQDN público do endpoint Headscale | Obtenha da infraestrutura e valide DNS/TLS | `headscale.dev.anatel` |
| `<GATEWAY_LAN_IP>` | Endereço LAN do host Gateway usado para verificar o acesso Headplane pela LAN | Obtenha do operador | — |
| `<APP_ALIAS>` | Alias DNS do container de aplicação | Leia `NetworkAlias` ou configuração da aplicação | `webapp.dev.anatel` |
| `<AUTH_KEY_FILE>` | Arquivo local, fora do repositório, para a chave de re-inscrição do cliente | Receba por canal seguro e remova após o uso | `/home/ana/.config/tailscale/auth-key` |
| `<TLS_STAGE>` | Diretório seguro com certificado e chave entregues à conta | Combine com a infraestrutura; use caminho absoluto legível pela conta | `/home/podman_user/tls-stage` |
| `<ID_DO_USUÁRIO>` | ID do usuário Headscale | Consulte a saída de `podman exec gateway headscale users list` | ID retornado pela listagem |
| `<ID_DO_NÓ>` | ID do nó Tailscale registrado | Execute `podman exec gateway headscale nodes list` | ID retornado pela listagem |

A variante mantém Headscale, Headplane, `tailscaled` e NGINX no container Debian `gateway`. O anúncio usa `--snat-subnet-routes=false` e deve preservar o IP VPN original visto pela aplicação. O Gateway anuncia somente `<ROOTLESS_SUBNET>`; não anuncie rota default nem use o Gateway como exit node.

| Tema | Alternativa rootful (implementada, mantida) | Alvo rootless |
| --- | --- | --- |
| Conta de execução | Serviço do sistema e Podman rootful | Conta local dedicada `<GATEWAY_USER>` e Podman rootless |
| Quadlet | `/etc/containers/systemd/`, `systemctl` do sistema | `~/.config/containers/systemd/`, `systemctl --user` |
| Rede anunciada | Rede padrão rootful `podman` | Bridge rootless dedicada `gateway-vpn` |
| Rota de retorno | Serviço de host na namespace de rede do host | Rota dentro de `podman unshare --rootless-netns` |
| HTTPS | TCP 443 publicado diretamente pelo container | TCP 443 publicado diretamente no host pelo `rootlessport` |
| Armazenamento | Store rootful e volumes do rootful | Store e volumes independentes do usuário rootless |
| Referência e suporte | Alternativa rootful mantida | Alvo rootless; sem suporte Portainer rootless e sem migração de dados |

```mermaid
flowchart LR
    client[Cliente VPN] -->|tráfego VPN| tailscale[Tailscale no Gateway<br/>tailscale0]
    tailscale -->|sem SNAT| bridge[Bridge rootless gateway-vpn]
    bridge --> app[Container da aplicação]
    app --> bridge
    bridge --> route["Namespace rootless<br/>rota &lt;VPN_PREFIX&gt; via &lt;GATEWAY_IP&gt;<br/>dev &lt;ROOTLESS_BRIDGE_IFACE&gt;"]
    route --> tailscale
```

A bridge existe na namespace de rede rootless e não é diretamente alcançável pela namespace de rede do host. Não publique DNS TCP/UDP 53 no host; os clientes VPN consultam o Aardvark pelo split DNS e pela rota anunciada. O tráfego de retorno ao cliente depende da rota instalada nessa namespace. Todos os containers de aplicação que precisem ser anunciados devem entrar na mesma bridge e usar aliases DNS nela.

Mantenha a [alternativa rootful](gateway-headscale-podman-rootfull.md) e seus volumes. Não execute as duas variantes no mesmo host nem anuncie rotas iguais ou sobrepostas. O store rootless é separado; não migre volumes rootful. Portainer não é oficialmente suportado nesta topologia rootless.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 2. Inventário

| Arquivo | Uso nesta variante | Adaptação ou limite |
| --- | --- | --- |
| [Containerfile](../../deploy/gateway/v1/Containerfile), [entrypoint.sh](../../deploy/gateway/v1/entrypoint.sh), [healthcheck.sh](../../deploy/gateway/v1/healthcheck.sh) | Reutilizados | A imagem mantém processos e healthcheck existentes; build e execução usam Podman do usuário. |
| [headscale.yaml](../../deploy/gateway/v1/config/headscale.yaml) | Copiado e adaptado | Trocar `192.0.2.53` pelo `<ROOTLESS_BRIDGE_IP>` do Aardvark e ajustar endpoint/prefixo. |
| [headplane.yaml](../../deploy/gateway/v1/config/headplane.yaml) | Candidato, validado e instalado | `prepare-headplane-candidate.sh` cria segredo inicial em modo `0444`; ajuste permissões depois da validação. |
| [nginx.conf](../../deploy/gateway/v1/config/nginx.conf) | Copiado e adaptado | Ajustar FQDN e prefixo permitido; validar o endereço de origem que NGINX realmente recebe. |
| [gateway.container](../../deploy/gateway/v1/quadlet/gateway.container) | Copiado para o diretório Quadlet do usuário | Trocar dependências rootful, rede, publicação de porta e caminhos bind. Manter TUN, `NET_ADMIN` e `ip_forward`. |
| [gateway-vpn-return-route.service](../../deploy/gateway/v1/host/gateway-vpn-return-route.service) e [env.example](../../deploy/gateway/v1/host/gateway-vpn-return-route.env.example) | **Não usados** | Configuram uma rota na namespace rootful do host; não controlam a namespace rootless. |
| [prepare-headplane-candidate.sh](../../deploy/scripts/prepare-headplane-candidate.sh) | Reutilizado como `<GATEWAY_USER>` | Usa `openssl`; cria diretório `0700`, config `0600` e segredo `0444`. |
| [validate-headplane-config.sh](../../deploy/scripts/validate-headplane-config.sh) | Reutilizado como `<GATEWAY_USER>` | Chama `podman run`, `podman healthcheck` e remove o container de validação. Usa o store rootless da sessão atual; não valida as permissões finais dos bind mounts. |
| [enroll-gateway.sh](../../deploy/scripts/enroll-gateway.sh) | Reutilizado com argumentos explícitos | Inspeciona a rede Podman visível ao usuário, exige exatamente um CIDR IPv4, anuncia essa rede com `--snat-subnet-routes=false` e apaga o arquivo da auth key. |
| [install-file.sh](../../deploy/scripts/install-file.sh) | **Não usado nesta variante** | Sempre chama `chown`; sem root só serve se proprietário/grupo forem permitidos para o próprio usuário, não para mapear UID interno. Como root, pode criar arquivos com proprietário incompatível. Use instalação/cópia curta como o usuário. |
| [Receita TLS](gateway-tls.md) | Referência para certificado | O procedimento existente gera material em caminhos controlados pelo host; a infraestrutura deve entregar os arquivos à conta rootless por canal seguro, sem afrouxar a chave privada. |

Interfaces reais dos scripts: `prepare-headplane-candidate.sh [candidate_dir] [template_file]` usa como template padrão `deploy/gateway/v1/config/headplane.yaml` e, sem diretório, cria staging em `/tmp`; cria config `0600` e segredo de 32 hex `0444`. `validate-headplane-config.sh <candidate_config> <candidate_secret> [containerfile_or_image]` usa o Containerfile versionado como padrão, roda container de rede `none`, tenta healthcheck por até 20 segundos e remove o container; remove também imagem que baixou somente quando a validação falha. `enroll-gateway.sh <headscale_fqdn> [container_name] [network_name] [authkey_path]` assume `gateway`, `podman` e `/run/tailscale-auth/authkey` quando omitidos; esta receita passa `gateway` e `gateway-vpn` explicitamente. `install-file.sh <source_path|-> <target_path> <mode> <owner> <group>` ajusta proprietário/grupo com `chown`, aplica modo, recusa destino existente e faz rename atômico; sem root, `chown` só pode manter um proprietário/grupo permitido para o usuário atual, não mapear UID interno. Executar como root não atende ao modelo de arquivos pertencentes à conta rootless.

`prepare-headplane-candidate.sh` é reutilizável sem root, mas seu segredo `0444` não atende à política de permissões finais. Valide primeiro; depois copie, restrinja e aplique o mapeamento de UID interno descrito na seção 6. `validate-headplane-config.sh` usa o `podman` encontrado no `PATH`; não o execute com `sudo`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 3. Pré-requisitos e descoberta

Faça primeiro as inspeções de leitura. Não altere redes, sysctls, firewall, SELinux, unidades nem imagens nesta etapa. Obtenha da equipe de infraestrutura o CIDR atual da rede rootful `podman`; não use `sudo podman` nesta receita nem confunda esse valor com a rede `podman` do store rootless.

**Gate G0 — bloqueante, somente leitura.** Depois da preparação de conta na seção 4, entre como `<GATEWAY_USER>` em uma sessão real (`machinectl shell <GATEWAY_USER>@` ou SSH) e execute as verificações abaixo. `sudo -u` sozinho não fornece a sessão D-Bus de usuário nem `XDG_RUNTIME_DIR`.

```bash
podman --version
podman info --format '{{.Host.Security.Rootless}}'
podman info --format '{{.Host.CgroupsVersion}}'
```

```bash
printf 'runtime=%s\n' "$XDG_RUNTIME_DIR"
test -S "$XDG_RUNTIME_DIR/bus"
```

Exija `true`, cgroups `v2`, `XDG_RUNTIME_DIR` definido e socket `bus` presente. Confirme faixas subuid/subgid para o usuário, `newuidmap`, `newgidmap`, `pasta`, Netavark e Aardvark DNS; use `podman info --debug`, `command -v` e os nomes de pacote disponíveis no RHEL para confirmar caminhos e instalação. Confirme também:

```bash
command -v newuidmap
command -v newgidmap
command -v pasta
```

```bash
rpm -q netavark aardvark-dns passt
getenforce
test -c /dev/net/tun
```

```bash
loginctl show-user "$(id -un)" -p Linger
findmnt -no FSTYPE,OPTIONS -T "$HOME"
grep -E "^$(id -un):[0-9]+:[0-9]+$" /etc/subuid /etc/subgid
```

Exija SELinux `Disabled`, dispositivo `/dev/net/tun` presente, `Linger=yes`, ranges subuid/subgid, e home em disco local. A home não pode estar em NFS nem montada com `noexec` ou `nodev`. `rpm -q` pode usar nomes de pacote diferentes no repositório RHEL; confirme os executáveis efetivos em vez de ignorar ausência de Netavark/Aardvark/pasta.

Registre, sem alterar, rotas do host, LAN/corporativas, prefixo VPN e CIDR da alternativa rootful `podman`. O alvo rootless usa `gateway-vpn` (`10.90.0.0/24`), resolver `10.90.0.1`, Gateway `10.90.0.2` e prefixo Headscale `100.96.0.0/24`; confirme que não há sobreposição. A publicação do endpoint é TCP 443 direto no host.

**Critério G0:** todas as verificações e os dados de rede estão disponíveis e não se sobrepõem. **Se falhar: pare.** Não tente contornar SELinux, user namespaces, home remota ou falta de dependências nesta receita.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 4. Preparar a conta rootless (root)

Execute esta preparação como `root` ou entre com `sudo -i`. Reserve ranges subuid e subgid livres, sem sobrepor as ranges já alocadas em `/etc/subuid` e `/etc/subgid`. Não use os valores de exemplo de outra conta.

Use conta de serviço local exclusiva. Se a conta já existir, confirme finalidade, home local e ranges antes de reutilizá-la; não execute `useradd` nem `usermod` para uma conta existente sem validar cada alteração. Confirme que a home fica em disco local não NFS, sem `noexec`/`nodev`; não mova o armazenamento rootless para NFS.

Substitua os valores indicados antes de executar:

```bash
GATEWAY_USER=podman_user
SUBUID_RANGE='INICIO-FIM_LIVRES'
SUBGID_RANGE='INICIO-FIM_LIVRES'
```

Inspecione ranges existentes para a conta e todas as faixas alocadas antes de criar a conta ou chamar `usermod`:

```bash
sudo awk -F: -v user="$GATEWAY_USER" '$1 == user { print FILENAME ":" $0 }' /etc/subuid /etc/subgid
sudo awk -F: '{ print FILENAME ":" $0 }' /etc/subuid /etc/subgid
```

Se a conta não existir, crie-a:

```bash
useradd --create-home --home-dir "/home/$GATEWAY_USER" --shell /bin/bash "$GATEWAY_USER"
```

Gere uma senha inicial aleatória para a conta dedicada. Execute na raiz do repositório, confirme que `.env` é ignorado e que ainda não existe. O arquivo fica em modo `0600`; não imprima nem passe a senha em argumentos.

```bash
git check-ignore -q .env || { printf ".env precisa estar ignorado pelo Git.\n" >&2; exit 1; }
test ! -e .env || { printf ".env já existe; preserve-o e resolva manualmente.\n" >&2; exit 1; }
umask 077
GWVPN_INITIAL_PASSWORD=$(openssl rand -hex 32)
printf "GWVPN_INITIAL_PASSWORD=%s\n" "$GWVPN_INITIAL_PASSWORD" > .env
if ! printf "%s:%s\n" "$GATEWAY_USER" "$GWVPN_INITIAL_PASSWORD" | chpasswd; then
  rm -- .env
  unset GWVPN_INITIAL_PASSWORD
  exit 1
fi
unset GWVPN_INITIAL_PASSWORD
```

Este .env contém credencial inicial; remova-o ou mova-o depois de armazenar a credencial.

Se houver qualquer faixa da conta em `/etc/subuid` ou `/etc/subgid`, pule `usermod` e confirme que ambas as alocações existentes são adequadas; se faltar uma faixa, pare e planeje uma alteração aprovada separada. Somente se nenhum arquivo já contiver faixa para a conta, compare os intervalos propostos com todas as faixas listadas e confirme que não há sobreposição antes de atribuí-los. Ative linger para a conta:

```bash
sudo usermod --add-subuids "$SUBUID_RANGE" --add-subgids "$SUBGID_RANGE" "$GATEWAY_USER"
```

```bash
sudo loginctl enable-linger "$GATEWAY_USER"
```

A publicação rootless usa TCP 443 diretamente no host. O sysctl global da etapa 1 permite o bind por `rootlessport`; não configure encaminhamento de TCP 443 para 8443.

Depois da preparação, como `root`, abra uma sessão de `<GATEWAY_USER>`:

```bash
su - "$GATEWAY_USER"
```

Na sessão do usuário, defina o runtime e confirme o user bus:

```bash
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
test -S "$XDG_RUNTIME_DIR/bus" || { printf "User bus indisponível.\n" >&2; exit 1; }
```

Se `su` não fornecer o user bus, saia da sessão e use `machinectl shell <GATEWAY_USER>@`; repita a definição e a confirmação. SSH também serve. Daqui em diante execute **tudo** como `<GATEWAY_USER>`, sem `sudo`: build, scripts, Podman, Quadlet, configurações, rede, logs e testes. Se o checkout estiver sob uma home privada e inacessível, não amplie permissões da home; use cópia temporária dos arquivos necessários em diretório acessível à conta rootless. Quadlet rootless é gerenciado por `systemctl --user` e não aceita `User=` para trocar a conta do container; o manager já executa como o usuário dedicado.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 5. Prova de conceito descartável

Execute como `<GATEWAY_USER>` na sessão real e na raiz do repositório. Use a rede `gateway-vpn` planejada na seção 3 e criada nesta seção 5; não conecte containers de produção durante a prova. As imagens dos probes e a imagem gateway podem ser baixadas/construídas no store rootless.

Crie a bridge com DNS habilitado por padrão e informe subnet/gateway escolhidos. Confirme o resultado efetivo; não prossiga se DNS estiver desabilitado:

```bash
podman network create --driver bridge --subnet '<ROOTLESS_SUBNET>' --gateway '<ROOTLESS_BRIDGE_IP>' gateway-vpn
podman network inspect gateway-vpn
```

**Gate G1 — crítico, bloqueante.** Exija `dns_enabled: true`. Inicie dois containers de probe, um alias por container, e execute as consultas a partir de ambos:

```bash
podman run -d --name g1-probe-a --network gateway-vpn --network-alias g1-a.dev.anatel docker.io/library/busybox:1.36 sleep 300
podman run -d --name g1-probe-b --network gateway-vpn --network-alias g1-b.dev.anatel docker.io/library/busybox:1.36 sleep 300
podman inspect --format "{{range \$k,\$v := .NetworkSettings.Networks}}{{\$v.IPAddress}}{{end}}" g1-probe-a
podman inspect --format "{{range \$k,\$v := .NetworkSettings.Networks}}{{\$v.IPAddress}}{{end}}" g1-probe-b
podman exec g1-probe-a nslookup g1-a.dev.anatel
podman exec g1-probe-a nslookup g1-b.dev.anatel
podman exec g1-probe-a nslookup dev-gateway.dev.anatel
podman exec g1-probe-b nslookup g1-a.dev.anatel
podman exec g1-probe-b nslookup g1-b.dev.anatel
podman exec g1-probe-b nslookup dev-gateway.dev.anatel
```

**Critério G1:** cada alias resolve para o IP do seu container pela bridge rootless. Compare os resultados de `nslookup` com os IPs exibidos por `podman inspect`. **Se falhar: pare** e não instale Gateway nem anuncie a rede.

**Gate G2 — crítico, bloqueante.** Com a bridge ativa, primeiro confira o encaminhamento IPv4 na namespace rootless:

```bash
podman unshare --rootless-netns /usr/sbin/sysctl net.ipv4.ip_forward
```

**Critério:** a saída deve ser `net.ipv4.ip_forward = 1`. Se o valor for `0`, ajuste somente a namespace rootless e confirme novamente:

```bash
podman unshare --rootless-netns /usr/sbin/sysctl -w net.ipv4.ip_forward=1
podman unshare --rootless-netns /usr/sbin/sysctl net.ipv4.ip_forward
```

Esse ajuste não altera o sysctl global do host. **Se o comando falhar ou o valor continuar diferente de `1`: pare.**

Descubra a interface e a rota na mesma namespace; use `replace` para tornar a instalação idempotente:

```bash
podman unshare --rootless-netns /usr/sbin/ip -4 addr
podman unshare --rootless-netns /usr/sbin/ip -4 route
```

```bash
podman unshare --rootless-netns /usr/sbin/ip -4 route replace "<VPN_PREFIX>" via "<GATEWAY_IP>" dev "<ROOTLESS_BRIDGE_IFACE>"
podman unshare --rootless-netns /usr/sbin/ip -4 route show "<VPN_PREFIX>"
```

**Critério G2:** rota aparece com o next hop e interface esperados. A comprovação completa exige também reiniciar `gateway.service` após instalar o drop-in na seção 7 e confirmar que a rota reaparece; até esse teste, G2 permanece aberto. `replace` torna a operação repetível. **Se a instalação ou reaplicação falhar: pare.**

O `Sysctl=net.ipv4.ip_forward=1` do container configura encaminhamento dentro do container. O drop-in da seção 7 também configura `net.ipv4.ip_forward=1` na namespace rootless; nenhum dos dois altera o sysctl global do host.

**Gate G3 — crítico, bloqueante.** Construa a imagem existente sem iniciar seus serviços e teste TUN, `NET_ADMIN` e `ip_forward` em container descartável rootless:

```bash
podman build --tag localhost/gateway:1.0.0 --file deploy/gateway/v1/Containerfile deploy/gateway/v1
```

```bash
podman run --rm --network gateway-vpn --cap-add NET_ADMIN \
  --device /dev/net/tun:/dev/net/tun --sysctl net.ipv4.ip_forward=1 \
  --entrypoint /bin/bash localhost/gateway:1.0.0 -ec 'test -c /dev/net/tun; /usr/sbin/ip tuntap add dev tun-poc mode tun; /usr/sbin/ip link del dev tun-poc; test "$(cat /proc/sys/net/ipv4/ip_forward)" = 1'
```

**Critério G3:** comando retorna `0`, abre/remove interface TUN e lê `ip_forward=1`. **Se falhar: pare.** Não use `--privileged`, socket Podman nem `--tun=userspace-networking` como substituto.

Remova apenas os probes depois dos gates. Mantenha a rede para a instalação, mas remova/recrie-a se os parâmetros precisarem mudar:

```bash
podman rm -f g1-probe-a g1-probe-b
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

## 6. Preparar configurações

Mantenha configurações, TLS e secrets em `$HOME/.config/gateway-vpn`, de propriedade de `<GATEWAY_USER>`. Use diretórios `0700` e arquivos `0600` quando possível. Não versione secrets nem chaves privadas. Confirme que os destinos ainda não existem antes de instalar; esta receita é para instalação nova.

```bash
mkdir -p "$HOME/.config/gateway-vpn/tls" "$HOME/.config/gateway-vpn/secrets/tailscale"
chmod 0700 "$HOME/.config/gateway-vpn" "$HOME/.config/gateway-vpn/tls" "$HOME/.config/gateway-vpn/secrets" "$HOME/.config/gateway-vpn/secrets/tailscale"
```

Prepare o candidato Headplane com o script existente, como `<GATEWAY_USER>`:

```bash
headplane_candidate_dir=$(deploy/scripts/prepare-headplane-candidate.sh)
headplane_candidate_config="$headplane_candidate_dir/headplane.yaml"
headplane_candidate_secret="$headplane_candidate_dir/headplane-cookie-secret"
```

Edite somente `headplane_candidate_config`: defina `headscale.public_url` como `https://<HEADSCALE_FQDN>` e mantenha `server.base_url` como `https://dev-gateway.dev.anatel`. Confirme os caminhos existentes de config e secret no template. O script deixa o segredo candidato em `0444` para a validação upstream; não instale esse modo como permissão final.

**Gate G4 — bloqueante.** Valide o candidato pela ferramenta existente, ainda como `<GATEWAY_USER>` e sem `sudo`:

```bash
deploy/scripts/validate-headplane-config.sh "$headplane_candidate_config" "$headplane_candidate_secret"
```

O helper executa Headplane com `--network none` e monta somente o YAML Headplane e o cookie secret. O candidato desta receita também referencia `/etc/headscale/config.yaml` e a API Headscale; o helper pode falhar com configuração válida porque omite esse arquivo e não alcança o serviço. **Gate G4:** não trate erro de dependência do helper como validação aprovada nem como YAML inválido. Confirme schema/secret e mantenha G4 aberto até G5: a unidade completa deve ficar `healthy`, ler configurações/secrets nos UIDs corretos e iniciar Headplane sem erro. **Se o runtime completo falhar, pare antes da inscrição.**

Instale/adapte cópias dos arquivos existentes no diretório rootless. Revise primeiro os destinos e preserve qualquer arquivo preexistente. Ajuste `headscale.yaml`: `server_url` para `https://<HEADSCALE_FQDN>`, `prefixes.v4` para `<VPN_PREFIX>` e o nameserver de `dns.nameservers.split.dev.anatel` de `192.0.2.53` para `<ROOTLESS_BRIDGE_IP>` — o endereço do resolver Aardvark, não o IP do container Gateway. Em `nginx.conf`, defina `allow` com o prefixo IPv4 Headscale exato, atualmente `100.96.0.0/24`; nunca permita `10.90.0.0/24`. Mantenha `deny all`.

```bash
gateway_config_dir="$HOME/.config/gateway-vpn"
```

```bash
for target in \
  "$gateway_config_dir/headscale.yaml" \
  "$gateway_config_dir/headplane.yaml" \
  "$gateway_config_dir/nginx.conf" \
  "$gateway_config_dir/tls/fullchain.pem" \
  "$gateway_config_dir/tls/privkey.pem" \
  "$gateway_config_dir/secrets/headplane-cookie-secret"
do
  if [[ -e "$target" || -L "$target" ]]; then
    printf "Destino existente: %s\n" "$target" >&2
    exit 1
  fi
done
install -m 0600 deploy/gateway/v1/config/headscale.yaml "$gateway_config_dir/headscale.yaml"
install -m 0600 "$headplane_candidate_config" "$gateway_config_dir/headplane.yaml"
install -m 0600 deploy/gateway/v1/config/nginx.conf "$gateway_config_dir/nginx.conf"
```

`install-file.sh` não é a alternativa desta receita: ele chama `chown` e não faz o mapeamento rootless necessário; `install -m` executado pelo usuário mantém o proprietário atual. Faça as edições dos arquivos instalados com o usuário; não execute o instalador como root.

Obtenha `fullchain.pem` e `privkey.pem` por processo aprovado. A receita [gateway-tls.md](gateway-tls.md) produz os arquivos de TLS do host, mas a chave pode ser root-only; não copie por um caminho que o usuário não possa ler, não relaxe a permissão de origem e não passe a chave em argumentos. A infraestrutura deve entregar o par a uma área de staging legível somente pela conta rootless, por canal seguro. Defina `TLS_STAGE` como esse diretório absoluto. Preserve a chave em `0600`; o certificado público pode usar `0644`.

```bash
TLS_STAGE='<TLS_STAGE>'
```

```bash
install -m 0644 "$TLS_STAGE/fullchain.pem" "$gateway_config_dir/tls/fullchain.pem"
install -m 0600 "$TLS_STAGE/privkey.pem" "$gateway_config_dir/tls/privkey.pem"
```

Depois de validar o candidato, instale o segredo em destino novo e remova o staging criado pelo script:

```bash
chmod 0600 "$headplane_candidate_secret"
install -m 0600 "$headplane_candidate_secret" "$gateway_config_dir/secrets/headplane-cookie-secret"
if [[ -n "${headplane_candidate_dir:-}" && -d "${headplane_candidate_dir}" && ! -L "${headplane_candidate_dir}" ]]; then
  rm -rf -- "${headplane_candidate_dir}"
fi
```

```bash
podman unshare chown 20002:20002 "$gateway_config_dir/secrets/headplane-cookie-secret"
podman unshare chmod 0400 "$gateway_config_dir/secrets/headplane-cookie-secret"
```

A imagem cria `headscale` UID/GID `20001` e `headplane` UID/GID `20002`; `entrypoint.sh` inicia esses processos com seus UIDs internos. O Headplane lê `/etc/headplane/config.yaml`, `/etc/headscale/config.yaml` e seu cookie secret. O Headscale lê `/etc/headscale/config.yaml` e sua chave Noise persistida em `/var/lib/headscale/noise_private.key`. O NGINX executa como root e lê sua configuração e a chave TLS.

A receita rootful instala as configurações não secretas como `root:root` modo `0644`, o certificado público como `root:root` modo `0644`, a chave TLS como `root:root` modo `0600` e o cookie secret como `root:20002` modo `0440`. Use o mapeamento rootless equivalente: arquivos de configuração e certificado legíveis em `0644`, propriedade interna `0:0`; chave TLS restrita a `0:0` modo `0600`; cookie secret restrito a `20002:20002` modo `0400`. Assim Headplane UID `20002` também pode ler a configuração Headscale referenciada por seu próprio YAML.

```bash
podman unshare chown 0:0 "$gateway_config_dir/headscale.yaml" "$gateway_config_dir/headplane.yaml" "$gateway_config_dir/nginx.conf" "$gateway_config_dir/tls/fullchain.pem" "$gateway_config_dir/tls/privkey.pem"
podman unshare chmod 0644 "$gateway_config_dir/headscale.yaml" "$gateway_config_dir/headplane.yaml" "$gateway_config_dir/nginx.conf" "$gateway_config_dir/tls/fullchain.pem"
podman unshare chmod 0600 "$gateway_config_dir/tls/privkey.pem"
```

As pastas continuam sob controle do usuário; os arquivos mapeados podem aparecer com UID não reconhecido na namespace do host. Defina e valide o método de edição/backup desses arquivos antes da operação contínua. `tailscaled` roda como root interno e grava seu estado no volume rootless. A montagem `secrets/tailscale` é temporária para auth key e deve permanecer `0700`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 7. Rede rootless e rota de retorno

A bridge `gateway-vpn` foi criada pela conta rootless na prova de conceito. Confirme que subnet, gateway e DNS habilitado continuam corretos. Ela precisa conter o Gateway e os containers de aplicação que serão anunciados. Descubra a interface efetiva dentro da namespace rootless, não na namespace do host:

```bash
podman network inspect gateway-vpn
podman unshare --rootless-netns /usr/sbin/ip -4 addr
podman unshare --rootless-netns /usr/sbin/ip -4 route
```

O serviço rootful `gateway-vpn-return-route.service` e o arquivo `/etc/sysconfig/gateway-vpn-return-route` **não são usados**. Não instale rota no host. A rota `<VPN_PREFIX> via <GATEWAY_IP> dev <ROOTLESS_BRIDGE_IFACE>` deve existir dentro da namespace rootless e ser reaplicada quando ela for recriada, inclusive após parar todos os containers rootless.

Use drop-in Quadlet do usuário em `~/.config/containers/systemd/gateway.container.d/`. O Quadlet oficialmente aceita arquivos `<name>.container.d/*.conf` e os mescla ao arquivo fonte; consulte [podman-systemd.unit(5), seção DESCRIPTION](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html). Crie `gateway.container.d/10-return-route.conf` com editor. Use o caminho absoluto retornado por `command -v podman` e `/usr/sbin/ip`; substitua os três valores de rede por valores aprovados:

```bash
mkdir -p "$HOME/.config/containers/systemd/gateway.container.d"
```

```ini
[Service]
ExecStartPost="/usr/bin/podman" unshare --rootless-netns "/usr/sbin/sysctl" -w net.ipv4.ip_forward=1
ExecStartPost="/usr/bin/podman" unshare --rootless-netns "/usr/sbin/ip" -4 route replace "<VPN_PREFIX>" via "<GATEWAY_IP>" dev "<ROOTLESS_BRIDGE_IFACE>"
ExecStartPost="/usr/bin/podman" unshare --rootless-netns "/usr/bin/bash" -c "/usr/sbin/iptables -C FORWARD -o <ROOTLESS_BRIDGE_IFACE> -s <ROOTLESS_SUBNET> -d <VPN_PREFIX> -j ACCEPT || /usr/sbin/iptables -I FORWARD 1 -o <ROOTLESS_BRIDGE_IFACE> -s <ROOTLESS_SUBNET> -d <VPN_PREFIX> -j ACCEPT"
ExecStartPost="/usr/bin/podman" unshare --rootless-netns "/usr/bin/bash" -c "/usr/sbin/iptables -t nat -C POSTROUTING -s <ROOTLESS_SUBNET> -d <VPN_PREFIX> -j ACCEPT || /usr/sbin/iptables -t nat -I POSTROUTING 1 -s <ROOTLESS_SUBNET> -d <VPN_PREFIX> -j ACCEPT"
```

`ExecStartPost` roda depois de cada início do Gateway. Ele configura forwarding na namespace rootless, reaplica a rota e instala regras estreitas de `FORWARD` e `POSTROUTING`. As exceções permitem o retorno da bridge ao prefixo VPN e evitam SNAT por regras padrão do Netavark. Os comandos são idempotentes. Não use `route add`. O exemplo não contém `%`; escape qualquer `%` literal como `%%` para o systemd. Esse mecanismo é experimental e precisa passar G2 após reinício do serviço na seção 8. Se todos os containers forem parados, a namespace rootless pode desaparecer e a rota junto com ela; o próximo start do Gateway deve instalá-la novamente.

Se `ExecStartPost` falhar, o systemd marca a inicialização da unidade como falha e interrompe o container; trate isso como falha G2/G5.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 8. Instalar unidades e iniciar

Como `<GATEWAY_USER>`, copie o Quadlet versionado para `~/.config/containers/systemd/` depois de confirmar que o destino não existe. Edite somente a cópia do usuário; não altere `deploy/`.

```bash
mkdir -p "$HOME/.config/containers/systemd"
gateway_quadlet="$HOME/.config/containers/systemd/gateway.container"
[[ ! -e "$gateway_quadlet" && ! -L "$gateway_quadlet" ]] || { printf "Destino existente: %s\n" "$gateway_quadlet" >&2; exit 1; }
install -m 0644 deploy/gateway/v1/quadlet/gateway.container "$HOME/.config/containers/systemd/gateway.container"
```

Aplique estas mudanças exatas na cópia:

| Diretiva original | Alteração na cópia rootless |
| --- | --- |
| `After=network-online.target` | Remova. |
| `Requires=gateway-vpn-return-route.service` | Remova. |
| `After=gateway-vpn-return-route.service` | Remova. |
| `Wants=network-online.target` | Remova. |
| `Network=podman` | `Network=gateway-vpn` |
| `IP=CHANGE_ME_GATEWAY_IPV4` | `IP=<GATEWAY_IP>` |
| `PublishPort=443:443/tcp` | Mantenha; publicação direta da TCP 443 |
| `Volume=/etc/gateway-vpn/headscale.yaml:/etc/headscale/config.yaml:ro` | `Volume=<GATEWAY_HOME>/.config/gateway-vpn/headscale.yaml:/etc/headscale/config.yaml:ro` |
| `Volume=/etc/gateway-vpn/headplane.yaml:/etc/headplane/config.yaml:ro` | `Volume=<GATEWAY_HOME>/.config/gateway-vpn/headplane.yaml:/etc/headplane/config.yaml:ro` |
| `Volume=/etc/gateway-vpn/nginx.conf:/etc/nginx/nginx.conf:ro` | `Volume=<GATEWAY_HOME>/.config/gateway-vpn/nginx.conf:/etc/nginx/nginx.conf:ro` |
| `Volume=/etc/gateway-vpn/tls:/etc/gateway-vpn/tls:ro` | `Volume=<GATEWAY_HOME>/.config/gateway-vpn/tls:/etc/gateway-vpn/tls:ro` |
| `Volume=/etc/gateway-vpn/secrets/headplane-cookie-secret:/run/secrets/headplane-cookie-secret:ro` | `Volume=<GATEWAY_HOME>/.config/gateway-vpn/secrets/headplane-cookie-secret:/run/secrets/headplane-cookie-secret:ro` |
| `Volume=/etc/gateway-vpn/secrets/tailscale:/run/tailscale-auth` | `Volume=<GATEWAY_HOME>/.config/gateway-vpn/secrets/tailscale:/run/tailscale-auth` |
| `WantedBy=multi-user.target` | `WantedBy=default.target` |

Obtenha a home absoluta com `getent passwd "$GATEWAY_USER"` e substitua `<GATEWAY_HOME>` pelo sexto campo, por exemplo `/home/podman_user`. Não use `~` nem `<GATEWAY_USER>` nas linhas `Volume=`. Mantenha `NetworkAlias=dev-gateway.dev.anatel`, os três volumes nomeados, `AddCapability=NET_ADMIN`, `/dev/net/tun` e `Sysctl=net.ipv4.ip_forward=1`. Os volumes nomeados pertencem ao store rootless, não ao rootful. Não adicione `User=`, `Group=` ou `DynamicUser=`; Quadlet não os suporta para executar como usuário não-root. Também não use `--privileged`, socket Podman ou networking Tailscale userspace.

Mantenha `PublishPort=443:443/tcp` na unidade e instale o drop-in de rota da seção 7. O endpoint Headscale e o tráfego VPN usam diretamente TCP 443 no host. O encaminhador rootless padrão (`rootlessport`) não preserva o IP de origem do cliente no listener público Headscale. O encaminhador `pasta` é experimental e não deve ser presumido. Teste a regra VPN-only do Headplane contra o endereço de origem que o NGINX realmente recebe.

**Gate G5 — bloqueante.** Recarregue o generator Quadlet e inicie a unidade. O generator processa `[Install] WantedBy=default.target` no `daemon-reload`; unidades geradas não aceitam o comando tradicional de habilitação. Confirme o autostart (`generated`), o target, o linger, os processos e as permissões:

```bash
systemctl --user daemon-reload
systemctl --user start gateway.service
systemctl --user is-enabled gateway.service
```

A saída de `is-enabled` deve ser `generated`. Confira `[Install] WantedBy=default.target` na cópia Quadlet e confirme que o linger está ativo. Aguarde a inicialização do Headplane antes do healthcheck; uma falha durante `HealthStartPeriod` não é resultado final:

```bash
loginctl show-user "$(id -un)" -p Linger
systemctl --user status gateway.service --no-pager
```

Verifique o healthcheck e a leitura como Headplane UID `20002` e Headscale UID `20001`. O container usa `setpriv` do pacote Debian `util-linux` instalado no Containerfile; `entrypoint.sh` já usa esse binário para iniciar ambos os processos:

```bash
sleep 10
podman healthcheck run gateway
podman inspect --format '{{.State.Health.Status}}' gateway
podman exec gateway setpriv --reuid=20002 --regid=20002 --clear-groups -- test -r /etc/headscale/config.yaml
```

```bash
podman exec gateway setpriv --reuid=20002 --regid=20002 --clear-groups -- test -r /etc/headplane/config.yaml
podman exec gateway setpriv --reuid=20002 --regid=20002 --clear-groups -- test -r /run/secrets/headplane-cookie-secret
```

```bash
podman exec gateway setpriv --reuid=20001 --regid=20001 --clear-groups -- test -r /etc/headscale/config.yaml
podman exec gateway setpriv --reuid=20001 --regid=20001 --clear-groups -- test -r /var/lib/headscale/noise_private.key
```

```bash
podman exec gateway stat -c '%a %u:%g %n' /etc/nginx/nginx.conf /etc/gateway-vpn/tls/fullchain.pem /etc/gateway-vpn/tls/privkey.pem
```

Espera-se estas linhas de `stat -c %a`: `644 0:0 /etc/nginx/nginx.conf`, `644 0:0 /etc/gateway-vpn/tls/fullchain.pem` e `600 0:0 /etc/gateway-vpn/tls/privkey.pem`. Os testes com `setpriv` acima continuam validando leitura como UIDs `20001` e `20002`.

Leia os logs do container e da unidade; confirme inicialização do Headplane e ausência de erros de leitura de configuração ou segredo:

```bash
podman logs gateway
journalctl --user -u gateway.service -n 100 --no-pager
```

Reinicie e confira se a rota volta sem comando manual:

```bash
systemctl --user restart gateway.service
podman unshare --rootless-netns /usr/sbin/ip -4 route show '<VPN_PREFIX>'
```

**Critério G5:** unidade ativa, estado `healthy`, `is-enabled` retorna `generated`, linger ativo, Headplane UID `20002` lê ambas as configurações e o cookie secret, e Headscale UID `20001` lê sua chave Noise. Os logs confirmam inicialização Headplane sem erro de leitura. **Critério final G2:** a rota reaparece após restart sem comando manual. **Se qualquer verificação falhar: pare** e não inscreva o Gateway.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 9. Inscrever o Gateway e acessar o Headplane

Crie o usuário no Headscale e obtenha seu ID sem expor segredo:

```bash
podman exec gateway headscale users create gateway-router
podman exec gateway headscale users list
```

Para obter o ID do nó após a inscrição, execute `podman exec gateway headscale nodes list` e use o valor correspondente em `<ID_DO_NÓ>`.

Crie auth key de uso único e validade curta diretamente no bind mount, sem exibi-la no terminal. Substitua o ID antes de executar:

```bash
HEADSCALE_USER_ID='<ID_DO_USUÁRIO>'
podman exec gateway sh -ec 'test ! -e /run/tailscale-auth/authkey; umask 077; headscale preauthkeys create --user "$1" --expiration 1h > /run/tailscale-auth/authkey' sh "$HEADSCALE_USER_ID"
deploy/scripts/enroll-gateway.sh "<HEADSCALE_FQDN>" gateway gateway-vpn
```

Execute `enroll-gateway.sh` manualmente como `<GATEWAY_USER>`, com o container `gateway` e a rede
`gateway-vpn`. Assim, o helper usa o store Podman dessa conta rootless. Ele exige um CIDR IPv4
único, chama `tailscale up` com `--snat-subnet-routes=false`, sem exit node e sem aceitar DNS/rotas,
e remove o arquivo de auth key. Confirme que anuncia **somente** `<ROOTLESS_SUBNET>`; aprove essa
rota no Headscale. O helper é classificado como alternativa rootful; a integração de inscrição
rootless permanece pendente.

```bash
NODE_ID='<ID_DO_NÓ>'
podman exec gateway headscale nodes approve-routes --identifier "$NODE_ID" --routes '<ROOTLESS_SUBNET>'
podman exec gateway tailscale status
```

### Corte do endpoint para TCP 443

Use esta sequência para migrar uma instalação existente de TCP 8443. **Não remova 8443 antes de
reinscrever o nó Tailscale do Gateway em `https://headscale.dev.anatel`; removê-la antes disso
deixa o Gateway offline.**

1. Publique TCP 443 junto com TCP 8443 na cópia Quadlet e reinicie `gateway.service`:

```ini
PublishPort=8443:443/tcp
PublishPort=443:443/tcp
```

2. Defina `server_url` em `headscale.yaml` como `https://headscale.dev.anatel`. Reinicie o Gateway
e confirme o listener TCP 443 antes de reautenticar.

3. Gere uma nova chave individual, de uso único e curta validade para o Gateway. Repita o comando
de criação acima e grave a chave em `/run/tailscale-auth/authkey`, sem exibi-la nem reutilizar a
chave anterior. Reinscreva com os mesmos flags de anúncio e roteamento, mais `--force-reauth`:

```bash
podman exec gateway tailscale up --login-server=https://headscale.dev.anatel \
  --auth-key=file:/run/tailscale-auth/authkey --advertise-routes='<ROOTLESS_SUBNET>' \
  --snat-subnet-routes=false --advertise-exit-node=false --exit-node= \
  --accept-dns=false --accept-routes=false --force-reauth
```

Remova o arquivo de chave após a tentativa; se a tentativa falhar, emita outra chave de uso único.

```bash
podman exec gateway rm -f -- /run/tailscale-auth/authkey
```

4. Reinscreva o cliente Linux com uma chave própria, lida por `file:` e removida após o uso:

```bash
sudo tailscale up --login-server=https://headscale.dev.anatel \
  --auth-key="file:<AUTH_KEY_FILE>" --accept-routes=true --accept-dns=true --force-reauth
rm -- "<AUTH_KEY_FILE>"
```

5. Confirme que Gateway e cliente estão online nos endereços atribuídos pelo Headscale. Aprove a
rota `<ROOTLESS_SUBNET>`; não remova 8443 antes dessa verificação:

```bash
podman exec gateway headscale nodes list
podman exec gateway tailscale status
tailscale status
NODE_ID='<ID_DO_NÓ>'
podman exec gateway headscale nodes approve-routes --identifier "$NODE_ID" --routes '<ROOTLESS_SUBNET>'
```

6. Só depois de confirmar a identidade e o estado online dos nós e a rota aprovada, remova a
   publicação 8443 e reinicie o Gateway. Mantenha somente `PublishPort=443:443/tcp`.

**Gate G6 — crítico, bloqueante.** A rota de retorno precisa estar presente no netns rootless. Acesse um listener descartável em container de aplicação por um cliente VPN e confira no log do listener o peer original, que deve ser o IP VPN do cliente, não o IP do Gateway/bridge. Não aceite só uma captura no Gateway como prova de ausência de SNAT.

**Critério G6:** aplicação registra o IP VPN original e o retorno funciona. **Se falhar: pare**, não anuncie ou mantenha a rota e não use SNAT como correção.

**Gate G7 — bloqueante.** De um cliente VPN, consulte por UDP e TCP o resolver Aardvark em `<ROOTLESS_BRIDGE_IP>`:

```bash
dig @'<ROOTLESS_BRIDGE_IP>' dev-gateway.dev.anatel A
dig @'<ROOTLESS_BRIDGE_IP>' '<APP_ALIAS>' A
```

```bash
dig +tcp @'<ROOTLESS_BRIDGE_IP>' dev-gateway.dev.anatel A
dig +tcp @'<ROOTLESS_BRIDGE_IP>' '<APP_ALIAS>' A
```

**Critério G7:** UDP e TCP resolvem o alias do Gateway e um alias de aplicação para seus IPs rootless. **Se falhar: pare** e revise rota, split DNS, bridge e aliases.

**Gate G8 — bloqueante.** O endpoint de controle e VPN atende diretamente em TCP 443 no host, tanto pela LAN como pela VPN; não encaminhe 443 para 8443. Acesse `https://dev-gateway.dev.anatel/admin` pela VPN e de um cliente LAN sem VPN:

```bash
curl --fail --show-error "https://<HEADSCALE_FQDN>/health"
curl --fail --show-error https://dev-gateway.dev.anatel/admin
curl -sS -o /dev/null -w '%{http_code}\n' https://dev-gateway.dev.anatel/admin
```

Confie no certificado pela CA aprovada; não use `curl -k`. A consulta `/admin` pela VPN deve retornar `302`; fixe o destino LAN em `<GATEWAY_LAN_IP>` e confirme `403`. Preserve `allow 100.96.0.0/24` e `deny all`, sem permitir `10.90.0.0/24`. **Critério G8:** Headplane autorizado somente pelo prefixo Headscale e Headscale acessível antes da VPN em TCP 443. Não use testes pela LAN como evidência de acesso WAN/perímetro externo. **Se falhar: pare.** Não enfraqueça a regra.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 10. Testes funcionais e gates

Execute os gates na ordem indicada. Qualquer falha interrompe a receita. Comandos são exemplos de verificação, não evidência de execução ou aprovação no alvo.

| Gate | Etapa | Teste ou comando | Critério de aprovação | Falha |
| --- | --- | --- | --- | --- |
| G0 | Pré-requisitos | `podman info`, cgroups, subuid/gid, executáveis, SELinux, TUN, linger, home | Rootless `true`, cgroups v2, dependências e ranges presentes, SELinux `Disabled`, TUN presente, linger ativo, home local compatível | Pare antes da POC |
| G1 | POC | `podman network inspect gateway-vpn`; `nslookup` entre probes | `dns_enabled: true`; cada alias resolve para o IP do respectivo container pela bridge | Pare; não instale Gateway |
| G2 | POC e G5 | `podman unshare --rootless-netns /usr/sbin/sysctl net.ipv4.ip_forward`; `podman unshare --rootless-netns /usr/sbin/ip -4 route replace ...`; restart do serviço | `ip_forward=1`; rota instalada e reaplicada pelo drop-in | Pare; não inscreva Gateway |
| G3 | POC | Container descartável com `NET_ADMIN`, `/dev/net/tun` e `ip_forward` | TUN e capability funcionam; `ip_forward=1` | Pare; sem `--privileged` ou substituto userspace |
| G4 | Configuração | Validador isolado como pré-checagem; fechar com o healthcheck completo em G5 | YAML/secret válidos e Headplane `healthy` no Gateway com Headscale disponível | Pare antes da inscrição se G5 falhar |
| G5 | Inicialização | `is-enabled` (`generated`), `[Install] WantedBy=default.target`, linger, healthcheck, leitura como UIDs `20001`/`20002`, logs e restart | Unidade ativa; `default.target`; permissões e rota confirmadas | Pare antes da inscrição |
| G6 | VPN/L3 | Listener de app registra peer; rota VPN no netns | IP VPN original chega à aplicação, sem SNAT, com retorno | Pare; não anuncie rota |
| G7 | DNS | `dig` UDP e TCP para `<ROOTLESS_BRIDGE_IP>` | Gateway e alias de app resolvem do cliente VPN | Pare; revise rede/DNS |
| G8 | Acesso | `/admin` e `/health` em TCP 443 pela LAN e VPN; logs NGINX | Headplane retorna 302 pela VPN e 403 pela LAN; Headscale acessível antes da VPN; não infira acesso WAN pelos testes LAN | Pare; não relaxe controles |
| G9 | Autostart e reboot | Conferir linger, unidades, rota de retorno, nós Headscale e reconexão do cliente após reinício do user manager e reboot do host | Unidades ativas, rota restaurada, nós online e cliente reconectado | Pare; G9 não aprovado |
| G10 | Modo e escopo | Conferir `podman info` para `<GATEWAY_USER>` | O runtime informa `rootless: true`; esta receita valida somente a execução rootless, não a variante rootful | Pare se o runtime não informar rootless |

**Gate G9 — crítico, bloqueante.** Não reinicie o host durante este teste. Como `root`, defina `GATEWAY_USER` para a conta aprovada e reinicie seu manager com linger:

```bash
GATEWAY_USER='<GATEWAY_USER>'
loginctl terminate-user "$GATEWAY_USER"
systemctl stop "user@$(id -u "$GATEWAY_USER").service"
systemctl start "user@$(id -u "$GATEWAY_USER").service"
```

Não execute `systemctl --user start gateway.service`: o Gateway deve iniciar pelo `default.target`. Depois da inicialização, como `<GATEWAY_USER>`, confirme:

```bash
systemctl --user is-enabled gateway.service
systemctl --user is-active gateway.service
podman inspect --format "{{.State.Health.Status}}" gateway
podman unshare --rootless-netns /usr/sbin/ip -4 route show '<VPN_PREFIX>'
podman exec gateway headscale nodes list
podman exec gateway tailscale status
```

Do cliente VPN, confirme a rota anunciada, o acesso ao app e o default route inalterado. O ID Headscale permanece o mesmo; não reinscreva o nó. Aguarde a inicialização da healthcheck antes de declarar falha:

```bash
tailscale status
ip -4 route show table 52
ip -4 route show default
curl --fail --show-error http://<APP_ALIAS>/
curl --fail --show-error https://dev-gateway.dev.anatel/admin
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

## 11. Rollback e limpeza

Rollback interrompe a VPN e o acesso Headplane. Faça-o em janela aprovada. Não apague volumes rootless: contêm banco/identidade Headscale, estado Tailscale e dados Headplane. A remoção de volumes pode causar perda permanente e reinscrição; exige backup verificado e aprovação separada.

Antes de parar a unidade, remova a rota e as regras `FORWARD`/`POSTROUTING` do drop-in dentro da namespace rootless. Use os mesmos valores e especificações de regra da seção 7. Se a namespace rootless já não existir, erros ao remover a rota ou as regras são esperados e inofensivos; continue o rollback. Deixe `net.ipv4.ip_forward=1` como está: esse valor desaparece com a namespace rootless.

```bash
podman unshare --rootless-netns /usr/sbin/ip -4 route del '<VPN_PREFIX>' via '<GATEWAY_IP>' dev '<ROOTLESS_BRIDGE_IFACE>'
```

```bash
podman unshare --rootless-netns /usr/bin/bash -c 'if /usr/sbin/iptables -C FORWARD -o <ROOTLESS_BRIDGE_IFACE> -s <ROOTLESS_SUBNET> -d <VPN_PREFIX> -j ACCEPT; then /usr/sbin/iptables -D FORWARD -o <ROOTLESS_BRIDGE_IFACE> -s <ROOTLESS_SUBNET> -d <VPN_PREFIX> -j ACCEPT; fi'
podman unshare --rootless-netns /usr/bin/bash -c 'if /usr/sbin/iptables -t nat -C POSTROUTING -s <ROOTLESS_SUBNET> -d <VPN_PREFIX> -j ACCEPT; then /usr/sbin/iptables -t nat -D POSTROUTING -s <ROOTLESS_SUBNET> -d <VPN_PREFIX> -j ACCEPT; fi'
```

Pare a unidade gerada, remova o arquivo fonte e o drop-in, e recarregue o generator:

```bash
systemctl --user stop gateway.service
rm -- "$HOME/.config/containers/systemd/gateway.container"
rm -f -- "$HOME/.config/containers/systemd/gateway.container.d/10-return-route.conf"
```

```bash
systemctl --user daemon-reload
podman rm -f gateway
```

Remova também os outros containers rootless ligados a `gateway-vpn` por suas unidades autorizadas. Remova a rede somente quando nenhum container estiver conectado:

```bash
podman network rm gateway-vpn
```

Mantenha os volumes, a conta, as faixas subuid/gid e os arquivos de configuração até revisar backups e acesso. Não execute `podman volume rm`, `podman volume prune` ou `userdel` como parte deste rollback. Não restaure o sysctl durante o rollback da aplicação: a configuração global TCP 443 pertence à preparação do host e afeta qualquer usuário não privilegiado. A receita rootful e seus volumes permanecem intocados como fallback; não opere os dois Gateways anunciando rotas sobrepostas.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 12. Fontes oficiais

- [Podman rootless](https://docs.podman.io/en/latest/markdown/podman-rootless.1.html)
- [Podman rootless tutorial](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md)
- [Podman Quadlet — `podman-systemd.unit(5)`](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
- [Podman user namespaces — `podman-unshare(1)`](https://docs.podman.io/en/latest/markdown/podman-unshare.1.html)
- [Podman redes — `podman-network(1)`](https://docs.podman.io/en/latest/markdown/podman-network.1.html)
- [Tailscale subnet routers](https://tailscale.com/kb/1019/subnets)
- [Tailscale userspace networking](https://tailscale.com/kb/1112/userspace-networking)
- [Headscale v0.29.6 release e checksums](https://github.com/juanfont/headscale/releases/tag/v0.29.6)
- [Headscale v0.29.6 configuração de referência](https://github.com/juanfont/headscale/blob/v0.29.6/config-example.yaml)
- [Headscale v0.29.6 criação de pre-auth keys](https://github.com/juanfont/headscale/blob/v0.29.6/cmd/headscale/cli/preauthkeys.go)
- [Headscale v0.29.6 aprovação de rotas](https://github.com/juanfont/headscale/blob/v0.29.6/cmd/headscale/cli/nodes.go)
- [Headplane v0.8.2 release](https://github.com/tale/headplane/releases/tag/v0.8.2)
- [Headplane v0.8.2 configuration reference](https://github.com/tale/headplane/blob/v0.8.2/docs/configuration/index.md)
- [Headplane v0.8.2 configuration schema](https://github.com/tale/headplane/blob/v0.8.2/app/server/config/config-schema.ts)
- [Headplane v0.8.2 configuration loader](https://github.com/tale/headplane/blob/v0.8.2/app/server/config/load.ts)
- [Headplane v0.8.2 server startup](https://github.com/tale/headplane/blob/v0.8.2/app/server/app.ts)
- [Headplane v0.8.2 Kubernetes schema](https://github.com/tale/headplane/blob/v0.8.2/app/server/config/integration/kubernetes.ts)
- [Headplane v0.8.2 Dockerfile](https://github.com/tale/headplane/blob/v0.8.2/Dockerfile)
- [Headplane v0.8.2 publicação e tags OCI](https://github.com/tale/headplane/blob/v0.8.2/.github/workflows/release.yaml)
- [Headplane instalação Docker e reverse proxy](https://github.com/tale/headplane/blob/v0.8.2/docs/install/docker.md)
- [Tailscale v1.104.2 release](https://github.com/tailscale/tailscale/releases/tag/v1.104.2)
- [Tailscale v1.104.2 build da imagem oficial](https://github.com/tailscale/tailscale/blob/v1.104.2/build_docker.sh)
- [Tailscale containers oficiais](https://tailscale.com/kb/1282/docker)
- [Portainer com Podman — limites de plataforma](https://docs.portainer.io/start/install-ce/server/podman/linux)
- [Receita TLS local](gateway-tls.md)

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
