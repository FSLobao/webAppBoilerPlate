<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#1-objetivo-e-limites">Objetivo e limites</a></li>
      <li><a href="#2-inventário">Inventário</a></li>
        <li><a href="#3-pré-requisitos-e-descoberta">Pré-requisitos e descoberta</a></li>
        <li><a href="#4-preparar-configurações">Preparar configurações</a></li>
        <li><a href="#5-instalar-unidades-e-iniciar">Instalar unidades e iniciar</a></li>
        <li><a href="#6-inscrever-o-gateway-e-acessar-o-headplane">Inscrever o Gateway e acessar o Headplane</a></li>
        <li><a href="#7-testes-funcionais">Testes funcionais</a></li>
        <li><a href="#8-rollback">Rollback</a></li>
        <li><a href="#9-fontes-oficiais">Fontes oficiais</a></li>
    </ol>
</details>

# Gateway VPN com Headscale, Headplane e Tailscale

Receita manual para RHEL 9.8, Podman 5.8.2 e Quadlet. Testado em verificação descartável no Debian 13.6 (trixie) com Podman 5.4.2; a qualificação-alvo permanece RHEL 9.8 / Podman rootful 5.8.2. Execute os comandos em Bash, a partir da
raiz do repositório (o diretório que contém `deploy/` e `docs/`), e execute os comandos de host
como `root`. Este procedimento não modifica configurações do host automaticamente.

## 1. Objetivo e limites

O Gateway é um único container Debian minimal com Headscale, Headplane, `tailscaled` e NGINX.
Headscale recebe HTTPS no TCP `443` do host. Headplane usa HTTPS no mesmo listener, em
`https://dev-gateway.dev.anatel/admin`, e NGINX permite esse virtual host somente pela faixa IPv4
da VPN.

O Gateway anuncia somente o CIDR IPv4 efetivo da rede rootful padrão `podman`. O anúncio usa
`--snat-subnet-routes=false`; os containers recebem o endereço VPN original. Não anuncie rota
default nem use o Gateway como exit node.

Headscale usa DNS externo para seu endpoint HTTPS antes da VPN. Depois da conexão, clientes usam
split DNS para `dev.anatel` apontando ao resolver Aardvark descoberto na bridge do host. Aardvark
resolve o alias `dev-gateway.dev.anatel` para o IP estático do Gateway. Não publique a porta 53.

Use somente a rede existente `podman`. Não crie nem recrie redes. Não use `--privileged`, socket
Podman, publicação de porta 53, alterações de firewall ou alterações de SELinux. A capability
`NET_ADMIN` e `/dev/net/tun` ficam limitados ao container Gateway.

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

## 2. Inventário

| Arquivo | Função |
| --- | --- |
| [deploy/gateway/v1/Containerfile](deploy/gateway/v1/Containerfile) | Imagem com bases upstream fixadas por digest e pacotes Debian de snapshot imutável |
| [deploy/gateway/v1/entrypoint.sh](deploy/gateway/v1/entrypoint.sh) | Valida configs e reinicia processos individualmente |
| [deploy/gateway/v1/healthcheck.sh](deploy/gateway/v1/healthcheck.sh) | Verifica processos supervisionados e o healthcheck oficial do Headplane |
| [deploy/gateway/v1/config/headscale.yaml](deploy/gateway/v1/config/headscale.yaml) | Headscale, SQLite persistente e split DNS |
| [deploy/gateway/v1/config/headplane.yaml](deploy/gateway/v1/config/headplane.yaml) | Headplane local, sem integração com socket |
| [deploy/gateway/v1/config/nginx.conf](deploy/gateway/v1/config/nginx.conf) | TLS, proxy HTTPS e restrição de Headplane à VPN |
| [deploy/gateway/v1/quadlet/gateway.container](deploy/gateway/v1/quadlet/gateway.container) | Container Quadlet na rede padrão `podman` |
| [deploy/gateway/v1/host/gateway-vpn-return-route.service](deploy/gateway/v1/host/gateway-vpn-return-route.service) | Rota de retorno vinculada ao serviço Quadlet |
| [deploy/gateway/v1/host/gateway-vpn-return-route.env.example](deploy/gateway/v1/host/gateway-vpn-return-route.env.example) | Prefixo VPN, IP do Gateway e interface bridge |
| [deploy/scripts/install-file.sh](deploy/scripts/install-file.sh) | Instalação atômica e segura de arquivos sem sobrescrita |
| [deploy/scripts/prepare-headplane-candidate.sh](deploy/scripts/prepare-headplane-candidate.sh) | Preparação de diretório de staging para configuração e segredo de 32 hex do Headplane |
| [deploy/scripts/validate-headplane-config.sh](deploy/scripts/validate-headplane-config.sh) | Validação isolada da configuração do Headplane via container descartável e healthcheck |
| [deploy/scripts/enroll-gateway.sh](deploy/scripts/enroll-gateway.sh) | Descoberta e validação de CIDR IPv4 Podman único, inscrição Tailscale sem SNAT e descarte seguro de chave |
| [docs/recipes/gateway-cockpit-tls.md](docs/recipes/gateway-cockpit-tls.md) | Geração de certificado TLS de servidor unificado para Cockpit e Gateway |

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

## 3. Pré-requisitos e descoberta

Antes de qualquer alteração em arquivos, unidades ou imagens, confirme que SELinux já está
desativado. Este preflight é somente de leitura e não altera a política do host:

```bash
command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" == "Disabled" ]] || { echo "SELinux deve estar Disabled"; exit 1; }
```

Use o host-alvo autorizado. Não use o estado do workspace como substituto da inspeção do RHEL.
Confirme Podman, Quadlet, systemd, `ip`, OpenSSL e permissões administrativas:

```bash
podman --version
podman info --format '{{.Host.Security.Rootless}}'
systemctl --version
ip -4 route show table all
```

Inspecione a rede padrão existente, sem alterá-la:

```bash
podman network inspect podman
```

Confirme no resultado `dns_enabled: true`, o CIDR em `subnets[].subnet`, o gateway/bridge do host,
e os endereços já usados por containers. O Aardvark DNS é requisito obrigatório da arquitetura
para que o Headscale distribua split DNS de `dev.anatel` aos clientes VPN conectados, permitindo
a resolução de `dev-gateway.dev.anatel` e dos containers da aplicação.

Se `dns_enabled` for `false`, o administrador do host deve ativar o DNS definindo
explicitamente o arquivo de configuração da rede em `/etc/containers/networks/podman.json`.
Por design do Podman, a rede default `podman` é protegida e não pode ser removida via
`podman network rm podman`. O backend Netavark carrega as definições persistentes de rede a partir
de `/etc/containers/networks/<nome>.json`.

Para ativar o DNS sem recriar ou destruir a rede padrão:

1. Certifique-se de que não há containers em execução (`podman ps -q` vazio).
2. Salve a configuração inspecionada diretamente em `/etc/containers/networks/podman.json` e altere
   `dns_enabled` de `false` para `true` via `sed` (ou edite manualmente com `nano`):

```bash
mkdir -p -m 0755 /etc/containers/networks
podman network inspect podman --format '{{json .}}' > /etc/containers/networks/podman.json
sed -i 's/"dns_enabled": *false/"dns_enabled": true/' /etc/containers/networks/podman.json
```

Caso prefira editar manualmente com `nano` em lugar do comando `sed`:

```bash
nano /etc/containers/networks/podman.json
```

Localize a chave `"dns_enabled": false` e altere o valor para `true`, salvando o arquivo.

3. Reexecute `podman network inspect podman` e valide que `dns_enabled` passou para `true`. O Netavark
   iniciará automaticamente o processo `aardvark-dns` escutando na interface bridge do host (`podman0`)
   assim que o primeiro container for conectado à rede.

### 3.1 Conectividade e resolução de nomes externos (pré-VPN)

Antes do estabelecimento da VPN, o acesso dos clientes ao Headscale depende da conectividade externa do host:

- **Resolução DNS externa**: o FQDN público `<HEADSCALE_FQDN>` deve resolver no DNS externo (ou corporativo)
  para o endereço IP externo alcançável do host.
- **Porta HTTPS**: a infraestrutura de firewall e rede deve permitir o tráfego TCP `443` de entrada no host
  para alcançar o endpoint do Headscale.
- **Conectividade de saída**: o host deve possuir acesso de saída HTTPS para atualizar o mapa DERP oficial e
  acessar servidores de relay homologados, conforme a política corporativa.

### 3.2 Resolução de nomes internos (dentro da VPN)

Após o cliente autenticar e conectar-se à VPN Tailscale:

- **Split DNS**: o Headscale distribui a configuração de split DNS para o domínio interno `dev.anatel`,
  apontando as consultas para o endereço do resolver Aardvark na bridge do host (`podman0`).
- **Resolução de serviços**: o Aardvark resolve internamente o alias `dev-gateway.dev.anatel` para o IP estático
  do Gateway e os aliases dos containers de aplicação (ex.: `backend.project-a.dev.anatel`).
- **Encaminhamento de tráfego**: o roteamento entre a interface VPN e a bridge Podman deve estar habilitado no host.
- **Consultas DNS**: as consultas UDP/TCP `53` trafegam estritamente dentro do túnel criptografado VPN até a
  bridge interna; não há exposição nem publicação da porta `53` nas interfaces externas do host.

### 3.3 Certificado TLS do servidor (HTTPS)

O NGINX integrado no Gateway provê terminação TLS na porta TCP `443` para dois serviços distintos:
1. O endpoint público do Headscale (`https://<HEADSCALE_FQDN>/`).
2. A interface administrativa do Headplane (`https://dev-gateway.dev.anatel/admin`), acessível apenas via VPN.

O servidor necessita de um certificado TLS confiável cujo SAN (*Subject Alternative Name*) inclua ambos os nomes:
`<HEADSCALE_FQDN>` e `dev-gateway.dev.anatel`.

É possível e recomendado utilizar o **mesmo certificado de servidor TLS** para o Cockpit do host (porta 9090)
e para o Gateway VPN. Para o procedimento completo de geração da chave, inclusão dos SANs unificados,
assinatura e instalação/replicação dos arquivos para o Cockpit e o Gateway, consulte a receita
[docs/recipes/gateway-cockpit-tls.md](docs/recipes/gateway-cockpit-tls.md).

Não inicie a seção 4 até confirmar todos esses requisitos no host-alvo autorizado. Se algum estado
for inválido, ausente ou desconhecido, pare sem executar comandos que alterem o host. Não use a
inspeção do workspace como substituta da inspeção do alvo.

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

## 4. Preparar configurações

Antes de qualquer alteração persistente no host, confirme novamente os pré-requisitos da seção 3.
Valide primeiro a configuração candidata e o segredo em um container temporário, antes de criar
arquivos de instalação, unidades ou volumes. Execute os blocos na mesma sessão Bash como `root`.
O diretório candidato fica em `/tmp` com acesso restrito (modo `0700`) e pode ser removido ao final do procedimento.

### 4.1 Preparar staging da candidata do Headplane

O script [deploy/scripts/prepare-headplane-candidate.sh](deploy/scripts/prepare-headplane-candidate.sh) cria um diretório seguro em `/tmp`, copia o template padrão e gera um segredo criptográfico aleatório de 32 caracteres hexadecimais:

- **Uso**: `deploy/scripts/prepare-headplane-candidate.sh [candidate_dir] [template_file]`
- **Argumentos**: ambos opcionais. Por padrão cria `gateway-headplane.XXXXXX` em `/tmp` e utiliza [deploy/gateway/v1/config/headplane.yaml](deploy/gateway/v1/config/headplane.yaml).
- **Resultado esperado**: imprime o caminho do diretório em stdout e instruções em stderr.

```bash
candidate_dir=$(deploy/scripts/prepare-headplane-candidate.sh)
headplane_candidate_config="${candidate_dir}/headplane.yaml"
headplane_candidate_secret="${candidate_dir}/headplane-cookie-secret"
```

Edite somente essa cópia candidata antes de validar. Defina `headscale.public_url` com o endpoint
externo Headscale. Mantenha `server.base_url` como `https://dev-gateway.dev.anatel`, mantenha
`server.cookie_secret_path` em `/run/secrets/headplane-cookie-secret` e mantenha
`integration.kubernetes.enabled: false` com `pod_name: "gateway"`. Não copie a candidata para
`/etc` nem altere arquivos do host antes da validação.

### 4.2 Validar configuração do Headplane em container isolado

Headplane v0.8.2 não documenta um comando CLI separado para validar configuração. O caminho
suportado é iniciar o servidor na imagem fixada: `loadConfig()` lê o YAML e o segredo,
valida o schema e encerra com erro quando a configuração é inválida. O healthcheck oficial
confirma que a inicialização chegou ao listener.

O script [deploy/scripts/validate-headplane-config.sh](deploy/scripts/validate-headplane-config.sh) executa essa validação em container temporário isolado (`--network none`) e remove o container automaticamente na saída:

- **Uso**: `deploy/scripts/validate-headplane-config.sh <candidate_config> <candidate_secret> [containerfile_or_image]`
- **Argumentos**: caminho do YAML candidato, caminho do segredo de 32 hex e, opcionalmente, o Containerfile de onde extrair a imagem fixada.
- **Resultado esperado**: código de saída 0 e mensagem `Headplane configuration and cookie secret validated successfully (healthcheck passed).` Em caso de falha, exibe os logs do container e encerra com código 1.

```bash
deploy/scripts/validate-headplane-config.sh \
  "${headplane_candidate_config}" "${headplane_candidate_secret}"
```

Não continue para instalação se a validação falhar. Corrija o YAML candidato e repita o teste.

### 4.3 Instalar arquivos de configuração no host

Após a validação, instale os arquivos de configuração. O script [deploy/scripts/install-file.sh](deploy/scripts/install-file.sh) realiza a instalação segura e atômica: cria arquivo temporário no mesmo diretório de destino via `mktemp`, ajusta permissões, proprietário e grupo, e move o arquivo com `mv -T --no-clobber`, recusando substituir destinos pré-existentes.

- **Uso**: `deploy/scripts/install-file.sh <source_path|-> <target_path> <mode> <owner> <group>`
- **Argumentos**: caminho de origem (ou `-` para entrada padrão), caminho de destino absoluto, modo octal, proprietário e grupo.
- **Resultado esperado**: arquivo instalado no destino; falha com diagnóstico se o destino já existir.

Crie os diretórios de configuração e instale os arquivos de serviço:

```bash
mkdir -p -m 0750 /etc/gateway-vpn/tls /etc/gateway-vpn/secrets /etc/gateway-vpn/secrets/tailscale
deploy/scripts/install-file.sh deploy/gateway/v1/config/headscale.yaml /etc/gateway-vpn/headscale.yaml 0644 root root
deploy/scripts/install-file.sh "${headplane_candidate_config}" /etc/gateway-vpn/headplane.yaml 0644 root root
deploy/scripts/install-file.sh deploy/gateway/v1/config/nginx.conf /etc/gateway-vpn/nginx.conf 0644 root root
```

Escolha um IP estático não usado para o Gateway dentro do CIDR inspecionado. Não escolha o gateway
do host nem um endereço já ocupado ou reservado pelo IPAM. Defina um prefixo IPv4 Headscale dentro
da faixa suportada `100.64.0.0/10`; confirme que ele não conflita com o CIDR Podman, rotas do host,
LAN e redes corporativas. O prefixo VPN não é o CIDR anunciado.

Edite somente as cópias em `/etc/gateway-vpn`, exceto `headplane.yaml`, que já foi validado:

- Em `headscale.yaml`, defina `server_url` com `<HEADSCALE_FQDN>`, escolha prefixo IPv4 VPN sem
  conflito e substitua `192.0.2.53` pelo endereço da bridge do host informado pela inspeção. Esse
  endereço é o resolver Aardvark, não o IP do container Gateway.
- Não altere `headplane.yaml` depois da validação. Se precisar alterá-lo, atualize a candidata e
  repita a validação antes de substituir o arquivo instalado.
- Mantenha `grpc_listen_addr` em `127.0.0.1`; `grpc_allow_insecure` atende somente a CLI local
  dentro do container. Não exponha essa interface.
- Em `nginx.conf`, substitua `headscale.example.invalid` pelo FQDN público e alinhe
  `allow 100.64.0.0/10` ao prefixo IPv4 configurado no Headscale.
- Mantenha `dev-gateway.dev.anatel` como alias Quadlet. A rede padrão registra esse nome no
  Aardvark; não crie registros DNS duplicados.

Instale o certificado fornecido pela infraestrutura (não versione arquivos de chave privada).
Caso tenha gerado o certificado unificado para o servidor seguindo a receita
[docs/recipes/gateway-cockpit-tls.md](docs/recipes/gateway-cockpit-tls.md), utilize os caminhos
dos arquivos gerados no host (por exemplo, `/etc/gateway/tls/gateway.cert` e `/etc/gateway/tls/gateway.key`):

```bash
deploy/scripts/install-file.sh "<CAMINHO_CERTIFICADO_PEM>" /etc/gateway-vpn/tls/fullchain.pem 0644 root root
deploy/scripts/install-file.sh "<CAMINHO_CHAVE_PRIVADA_PEM>" /etc/gateway-vpn/tls/privkey.pem 0600 root root
```

Instale o segredo de cookie do Headplane validado anteriormente. O UID/GID `20002` pertence ao usuário Headplane dentro da imagem:

```bash
deploy/scripts/install-file.sh "${headplane_candidate_secret}" \
  /etc/gateway-vpn/secrets/headplane-cookie-secret 0440 root 20002
```

Edite [deploy/gateway/v1/quadlet/gateway.container](deploy/gateway/v1/quadlet/gateway.container) antes de instalá-lo. Substitua
`CHANGE_ME_GATEWAY_IPV4` pelo IP estático escolhido. Instale o arquivo de ambiente da rota de retorno a partir do exemplo:

```bash
mkdir -p /etc/sysconfig
deploy/scripts/install-file.sh deploy/gateway/v1/host/gateway-vpn-return-route.env.example \
  /etc/sysconfig/gateway-vpn-return-route 0644 root root
```

Preencha `VPN_PREFIX`, `GATEWAY_IPV4` e `PODMAN_BRIDGE_INTERFACE` com valores descobertos. O
`GATEWAY_IPV4` deve ser igual ao `IP` do Quadlet. A seção 5 não reinstala esse arquivo. Não use
`ip route replace`.

As imagens Tailscale `v1.104.2`, Headplane `0.8.2` e Debian Trixie usam digests imutáveis. O
bootstrap copia o bundle CA da imagem Tailscale fixada por digest. Antes de instalar
`ca-certificates`, APT acessa o snapshot por HTTPS com verificação de peer e hostname, valida as
assinaturas APT e confere os hashes SHA-256 de `InRelease` para `trixie`, `trixie-updates` e
`trixie-security`. O pacote CA e `tcpdump`/`conntrack` vêm desse mesmo snapshot fixado em
`20261020T213255Z`. `Check-Valid-Until=false` é necessário porque os metadados de `trixie-updates`
e `trixie-security` vencem em `2026-10-27`. Isso remove a proteção de frescor: os hashes fixam os
metadados aprovados, mas ainda é possível selecionar intencionalmente um snapshot antigo, que
também deixa de incluir atualizações de segurança posteriores. Atualize o timestamp e os três
hashes juntos após revisar suporte e segurança. Não substitua os snapshots por repositórios móveis.

O binário Headscale `0.29.6` é verificado por digests fixos obtidos do checksum oficial da
release para cada arquitetura suportada. A confiança inicial nesses digests depende dos dados
oficiais recebidos via HTTPS/TLS; não há proveniência assinada independente.

Construa a imagem somente depois de preparar as configurações e os arquivos externos, limpando o diretório de staging:

```bash
podman build --tag localhost/gateway:1.0.0 \
  --file deploy/gateway/v1/Containerfile deploy/gateway/v1
rm -rf -- "${candidate_dir}"
```

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

## 5. Instalar unidades e iniciar

Instale as unidades Quadlet e systemd usando [deploy/scripts/install-file.sh](deploy/scripts/install-file.sh). O script garante proteção contra sobrescrita com staging no diretório de destino e rename atômico sem sobrescrita (`mv -T --no-clobber`). O arquivo de rota já criado e preenchido na seção 4 não é reinstalado aqui.

```bash
mkdir -p /etc/containers/systemd /etc/systemd/system /etc/sysconfig
deploy/scripts/install-file.sh deploy/gateway/v1/quadlet/gateway.container \
  /etc/containers/systemd/gateway.container 0644 root root
deploy/scripts/install-file.sh deploy/gateway/v1/host/gateway-vpn-return-route.service \
  /etc/systemd/system/gateway-vpn-return-route.service 0644 root root
```

Edite `/etc/sysconfig/gateway-vpn-return-route` com os valores verificados. Confirme que o prefixo
VPN, IP do Gateway e interface bridge coincidem com Headscale, Quadlet e inspeção da rede. A
unidade instala somente a rota IPv4 exata e remove essa mesma rota ao parar. Quadlet exige e
ordena o Gateway depois da unidade de rota; uma falha ao instalar a rota impede o Gateway de
iniciar. `PartOf=gateway.service` remove a rota quando o Gateway para.

```bash
systemctl daemon-reload
systemctl start gateway.service
systemctl status gateway.service gateway-vpn-return-route.service --no-pager
podman network inspect podman
ip -4 route show
```

O Quadlet publica somente TCP `443` no host. O healthcheck verifica os processos supervisionados
Headscale, Headplane, NGINX e `tailscaled`, além de executar `/usr/local/bin/hp_healthcheck`.
`tailscaled` é considerado saudável antes da inscrição; o teste não exige estado conectado. Um estado
`unhealthy` informa falha, mas não reinicia o container automaticamente: `Restart=on-failure` reage
à saída do processo do container, não ao status do healthcheck. Os três volumes nomeados mantêm
banco/identidade do Headscale, dados Headplane e estado `tailscaled` separadamente. A unidade não
monta socket Podman, não publica DNS e não altera firewall ou SELinux.

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

## 6. Inscrever o Gateway e acessar o Headplane

Crie um usuário Headscale e consulte seu ID:

```bash
podman exec gateway headscale users create gateway-router
podman exec gateway headscale users list
```

Crie uma chave de uso único e curta validade diretamente no arquivo secreto montado. Substitua
`USER_ID` pelo ID retornado; não envie a chave ao terminal, histórico ou argumento de processo:

```bash
podman exec gateway sh -ec \
  'test ! -e /run/tailscale-auth/authkey; umask 077; headscale preauthkeys create --user USER_ID --expiration 1h > /run/tailscale-auth/authkey'
```

Inscreva o próprio Gateway executando o script [deploy/scripts/enroll-gateway.sh](deploy/scripts/enroll-gateway.sh):

- **Uso**: `deploy/scripts/enroll-gateway.sh <headscale_fqdn> [container_name] [network_name] [authkey_path]`
- **Argumentos**: FQDN público do Headscale (obrigatório). Parâmetros adicionais são opcionais e assumem por padrão o container `gateway`, a rede `podman` e o caminho interno `/run/tailscale-auth/authkey`.
- **Funcionamento**: descobre e valida a presença de exatamente um CIDR IPv4 na rede Podman, aciona `tailscale up` com `--snat-subnet-routes=false` e sem rota default, e garante a remoção da chave de autenticação mesmo em caso de erro através de trap.
- **Resultado esperado**: mensagem confirmando a inscrição do Gateway e instruindo a aprovação da rota no Headscale.

```bash
deploy/scripts/enroll-gateway.sh "<HEADSCALE_FQDN>"
```

A chave foi criada como não reutilizável e expira após uma hora. O script remove o arquivo mesmo se o
comando falhar; crie outra chave para uma nova tentativa se necessário.

No bootstrap local, aprove somente a rota IPv4 do Podman para o nó Gateway:

```bash
podman exec gateway headscale nodes list
podman exec gateway headscale nodes approve-routes --identifier NODE_ID --routes "<PODMAN_CIDR>"
```

Não aprove rota default nem outra faixa. O serviço de retorno deve mostrar a rota VPN via o IP
estático do Gateway. Não altere a rota default do host ou cliente.

Depois de conectar um cliente inscrito, abra `https://dev-gateway.dev.anatel/admin`. A resolução
deve ocorrer pelo split DNS `dev.anatel` encaminhado ao Aardvark. Gere uma chave de API Headscale
com validade compatível com a política operacional. Salve a chave em arquivo root-only através do
script [deploy/scripts/install-file.sh](deploy/scripts/install-file.sh), lendo diretamente da entrada padrão sem exibi-la em terminal compartilhado ou argumento de processo:

```bash
podman exec gateway headscale apikeys create --expiration 90d | \
  deploy/scripts/install-file.sh - /etc/gateway-vpn/secrets/headplane-api-key 0600 root root
```

Transfira o valor ao navegador do operador pelo canal de segredos aprovado e autentique no
Headplane. A chave completa só aparece no momento da criação; trate-a como segredo. Remova a cópia
local após transferi-la e expire a chave no Headscale quando deixar de ser necessária.

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

## 7. Testes funcionais

> **Aviso de status de teste**: Procedimento testado em verificação descartável no Debian 13.6 (trixie) com Podman 5.4.2; a qualificação-alvo da infraestrutura permanece RHEL 9.8 com Podman rootful 5.8.2. Não apresente estes procedimentos como homologados no host alvo antes da validação final no ambiente RHEL autorizado.

1. Com VPN desconectada, confirme que `<HEADSCALE_FQDN>` resolve externamente e que HTTPS valida a
   cadeia e o SAN do certificado.
2. Inscreva um cliente, aceite DNS e rotas, e confirme que ele recebe somente o CIDR Podman
   aprovado. Confirme que sua rota default permanece local.
3. Com VPN conectada, confirme que `dev-gateway.dev.anatel` resolve ao IP estático do Gateway via
   Aardvark e que `dev.anatel` não usa MagicDNS como substituto.
4. Acesse Headplane por HTTPS via VPN. Fora da VPN, confirme que o virtual host Headplane é
   negado; confirme também que Headscale continua acessível pelo endpoint externo.
5. Acesse um container de teste pela VPN e confirme no destino que o IP de origem é o IP VPN do
   cliente, sem SNAT no Gateway.
6. Confirme no host a rota de retorno exata via Gateway. Confirme que nenhuma rota default ou
   rota IPv6 de containers foi anunciada.
7. Reinicie o processo Headplane em ambiente de teste e confirme que `tailscaled` e a conectividade
   VPN existente continuam ativos.
8. Teste conexão direta e relay DERP conforme a política de conectividade aprovada.

Execute o healthcheck e confirme que o estado do container é `healthy`:

```bash
podman healthcheck run gateway
podman inspect --format '{{.State.Health.Status}}' gateway
```

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

## 8. Rollback

Parar o Gateway interrompe VPN e administração Headplane; a unidade vinculada remove somente a
rota IPv4 exata que adicionou. Preserve os três volumes nomeados para manter identidade,
inscrições, banco e sessões. Não remova volumes neste rollback.

```bash
(
  set -Eeuo pipefail
  systemctl stop gateway.service
  rm -- /etc/containers/systemd/gateway.container
  rm -- /etc/systemd/system/gateway-vpn-return-route.service
  rm -- /etc/sysconfig/gateway-vpn-return-route
  systemctl daemon-reload
)
```

Mantenha `/etc/gateway-vpn`, a imagem e os volumes até validar a recuperação. Excluir os volumes
apaga o banco/identidade Headscale, dados Headplane e estado Tailscale; isso pode exigir nova
inscrição. Faça backup e aprove essa perda separadamente.

Esta receita não reverte DNS externo, certificados, firewall, SELinux nem configuração da rede
Podman. Esses itens permanecem sob controle da infraestrutura.

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

## 9. Fontes oficiais

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
- [Podman: redes](https://docs.podman.io/en/latest/markdown/podman-network.1.html)
- [Podman: Quadlet](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>