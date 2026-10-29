<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#resumo">Resumo</a></li>
        <li><a href="#entenda-as-duas-chaves-privadas">Entenda as duas chaves privadas</a></li>
        <li><a href="#1-escolha-a-url-e-a-autoridade-emissora">1. Escolha a URL e a autoridade emissora</a></li>
        <li><a href="#2-crie-uma-ca-de-desenvolvimento-dedicada">2. Crie uma CA de desenvolvimento dedicada</a></li>
        <li><a href="#3-gere-a-chave-do-servidor-e-o-csr">3. Gere a chave do servidor e o CSR</a></li>
        <li><a href="#4-assine-o-certificado-do-servidor">4. Assine o certificado do servidor</a></li>
        <li><a href="#5-instale-e-replique-no-host">5. Instale e replique no host</a></li>
        <li><a href="#6-compartilhe-o-material-público-de-confiança">6. Compartilhe o material público de confiança</a></li>
        <li><a href="#7-conecte-se-e-verifique">7. Conecte-se e verifique</a></li>
        <li><a href="#renovação-e-remoção">Renovação e remoção</a></li>
        <li><a href="#faça-backup-do-material-de-assinatura-em-armazenamento-seguro-aprovado">Faça backup do material de assinatura em armazenamento seguro aprovado</a></li>
        <li><a href="#restaure-o-material-de-assinatura-para-uma-nova-chave-de-servidor">Restaure o material de assinatura para uma nova chave de servidor</a></li>
    </ol>
</details>

# Gateway e Cockpit TLS: geração de certificados de servidor e implantação de serviços

Use este procedimento para gerar, assinar e instalar o certificado TLS de servidor e a chave privada exigidos pelo host Gateway. Um único certificado unificado é emitido e compartilhado pelos dois serviços:

1. **Cockpit no host:** fornece administração do host na porta TCP `9090` (acessível por túnel SSH ou rede de gerenciamento direta), conforme o [limite do Cockpit](../contracts/ARCHITECTURE.md#22-cockpit-no-host) definido no contrato de arquitetura.
2. **Container VPN do Gateway:** encerra HTTPS na porta TCP `443` para Headscale (inscrição de clientes antes da VPN) e Headplane (administração dentro da VPN em `https://dev-gateway.dev.anatel/admin`), conforme descrito em [docs/recipes/gateway-headscale-podman.md](gateway-headscale-podman.md).

HTTPS da aplicação (por exemplo, NGINX na porta 8080) e certificados de cliente são independentes e não fazem parte deste procedimento.

## Resumo

- Gere a chave privada do servidor no **host** Gateway. Mantenha-a nele.
- Emita um único certificado de servidor com os Subject Alternative Names (SANs) necessários ao Cockpit e à VPN do Gateway:
  - `DNS:<HEADSCALE_FQDN>`: FQDN público ou corporativo para conexão ao Headscale antes da VPN.
  - `DNS:dev-gateway.dev.anatel`: alias interno de split DNS para administração do Headplane dentro da VPN.
  - `DNS:localhost` e `IP:127.0.0.1`: acesso de gerenciamento ao Cockpit no host por encaminhamento de porta SSH.
- Prefira um certificado emitido pela CA aprovada da organização. Se não houver uma disponível, use a CA de desenvolvimento dedicada descrita abaixo.
- Replique o certificado e a chave para os dois serviços no host:
  - Cockpit: `/etc/cockpit/ws-certs.d/50-gateway.crt` e `/etc/cockpit/ws-certs.d/50-gateway.key`.
  - VPN do Gateway: `/etc/gateway-vpn/tls/fullchain.pem` e `/etc/gateway-vpn/tls/privkey.pem`.
- Compartilhe com desenvolvedores e operadores somente o **certificado público da CA** e uma impressão digital SHA-256 verificada por um canal separado. Nunca compartilhe chaves privadas.
- Desenvolvedores confiam na CA em Windows, macOS ou Linux. A confiança no certificado não concede permissão de login.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Entenda as duas chaves privadas

O host e a estação de trabalho de assinatura geram **chaves diferentes para funções diferentes**. Eles não geram cópias da mesma chave.

- **Host Gateway:** `gateway.key` é a chave privada do servidor. Cockpit e NGINX do Gateway a usam para comprovar a posse da identidade em `gateway.cert` durante conexões TLS. Gere-a no host; o Cockpit a usa diretamente no host, e o container Gateway a recebe por uma montagem de volume somente leitura.
- **Estação de trabalho de assinatura do administrador:** `gateway-dev-ca.key` é a chave privada de assinatura da CA. Ela assina o certificado público do servidor criado a partir do CSR. Use uma máquina controlada pelo administrador, não a estação de trabalho de cada desenvolvedor. Não instale a chave da CA no host nem dentro de qualquer container.
- **Computadores de desenvolvedores e operadores:** importe somente `gateway-dev-ca.crt`, o certificado público da CA. Para este procedimento, eles não geram nem recebem uma chave privada TLS. Chaves de login SSH são independentes e não estão incluídas aqui.

O CSR leva a chave pública do servidor até quem fará a assinatura. O certificado assinado retorna ao host. Nenhuma dessas transferências exige o envio de uma chave privada. Manter a CA separada do host impede que uma chave de servidor roubada seja usada para emitir outros certificados confiáveis pela CA.

Uma CA organizacional substitui a estação de trabalho de assinatura local e a chave da CA. Usar a mesma CA e o mesmo certificado de servidor nos serviços do host (Cockpit e Gateway) evita várias âncoras de confiança nos computadores dos desenvolvedores e simplifica o gerenciamento do ciclo de vida do certificado.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 1. Escolha a URL e a autoridade emissora

Os comandos exigem OpenSSL no host e uma estação de trabalho controlada com Bash e OpenSSL para assinatura. Não execute comandos de geração de chaves dentro do repositório.

O certificado unificado deve incluir todos os Subject Alternative Names (SANs exigidos pelos dois serviços):

- **Acesso ao Cockpit:** `DNS:localhost` e `IP:127.0.0.1` para acesso por túnel SSH (`https://localhost:9443/`). Se o acesso direto ao Cockpit pela rede estiver autorizado, adicione o nome DNS ou o IP de gerenciamento do host.
- **Acesso ao Headscale:** `DNS:<HEADSCALE_FQDN>` (por exemplo, `vpn.example.com`), resolvido por DNS externo ou corporativo antes de estabelecer a VPN.
- **Acesso ao Headplane:** `DNS:dev-gateway.dev.anatel`, resolvido pelo split DNS do Aardvark depois da conexão à VPN (`https://dev-gateway.dev.anatel/admin`).

Portas não fazem parte de um SAN. Um único certificado que cubra esses nomes atende a todos os requisitos sem precisar de certificados ou CAs separados.

Se houver uma CA organizacional, envie a ela o CSR da etapa 3. Solicite um certificado TLS de servidor com os SANs necessários e uso `serverAuth`. Obtenha os certificados raiz e intermediários pelo canal aprovado da organização. Ignore as etapas 2 e 4; não introduza outra CA sem necessidade.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 2. Crie uma CA de desenvolvimento dedicada

Use esta alternativa somente com aprovação da equipe de infraestrutura. Confiar em uma CA permite que ela autentique servidores na máquina que confia nela. Limite seu uso ao desenvolvimento. Nunca distribua `gateway-dev-ca.key`, inclua-a no Git ou copie-a para o Gateway. Armazene a chave da CA criptografada e sua frase secreta em locais seguros aprovados e separados; mantenha a chave offline quando não estiver assinando.

Na estação de trabalho de assinatura, execute isto uma vez em um diretório privado fora do Git:

```bash
(
  set -Eeuo pipefail
  umask 077
  mkdir -m 0700 gateway-cockpit-ca
  cd gateway-cockpit-ca
  openssl genpkey -algorithm RSA -aes-256-cbc \
    -pkeyopt rsa_keygen_bits:3072 -out gateway-dev-ca.key
  openssl req -new -x509 -sha256 -days 1825 \
    -key gateway-dev-ca.key -out gateway-dev-ca.crt \
    -subj "/CN=Gateway Development CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash"
  openssl x509 -in gateway-dev-ca.crt -noout -sha256 -fingerprint
)
```

O OpenSSL solicitará a frase secreta da chave da CA. Não a inclua em comandos, variáveis de ambiente ou transcrições de terminal compartilhadas. Se o diretório já existir, este bloco será interrompido em vez de substituir uma CA existente.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 3. Gere a chave do servidor e o CSR

No host Gateway, abra uma sessão de administrador. Substitua `<HEADSCALE_FQDN>` pelo nome de host externo aprovado (por exemplo, `vpn.example.com`):

```bash
sudo bash <<'BASH'
set -Eeuo pipefail
umask 077
install -d -o root -g root -m 0700 /etc/gateway/tls
for path in /etc/gateway/tls/gateway.key /etc/gateway/tls/gateway.csr /etc/gateway/tls/gateway.cert; do
  if [[ -e "${path}" || -L "${path}" ]]; then
    printf 'Refusing to replace existing TLS input: %s\n' "${path}" >&2
    exit 1
  fi
done
openssl req -new -newkey rsa:3072 -nodes -sha256 \
  -keyout /etc/gateway/tls/gateway.key \
  -out /etc/gateway/tls/gateway.csr \
  -subj "/CN=gateway-server" \
  -addext "subjectAltName=DNS:<HEADSCALE_FQDN>,DNS:dev-gateway.dev.anatel,DNS:localhost,IP:127.0.0.1"
chmod 0600 /etc/gateway/tls/gateway.key
openssl req -in /etc/gateway/tls/gateway.csr -noout -verify -text
BASH
```

A chave do servidor não é criptografada intencionalmente para que os serviços iniciem sem intervenção. A propriedade de `root`, o modo `0600` e o diretório pai restrito a protegem. Se a geração falhar, inspecione quaisquer arquivos parciais antes de tentar novamente; não exclua um certificado ou uma chave em uso.

Transfira somente `gateway.csr` para a estação de trabalho de assinatura por um canal autenticado de administração. Por exemplo, um administrador pode exibi-lo com `sudo cat /etc/gateway/tls/gateway.csr` e salvar o bloco PEM completo como `gateway.csr` dentro de `gateway-cockpit-ca`. O CSR é público; a chave privada permanece no host.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 4. Assine o certificado do servidor

Na estação de trabalho de assinatura, dentro de `gateway-cockpit-ca`, substitua `<HEADSCALE_FQDN>` pelo mesmo nome de host externo usado na etapa 3:

```bash
(
  set -Eeuo pipefail
  umask 077
  if [[ -e gateway.cert || -L gateway.cert || -e gateway-server.ext || -L gateway-server.ext ]]; then
    printf 'Existing signing output found; use a fresh signing directory.\n' >&2
    exit 1
  fi
  cat > gateway-server.ext <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:<HEADSCALE_FQDN>,DNS:dev-gateway.dev.anatel,DNS:localhost,IP:127.0.0.1
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
  openssl x509 -req -in gateway.csr \
    -CA gateway-dev-ca.crt -CAkey gateway-dev-ca.key \
    -set_serial "0x$(openssl rand -hex 16)" \
    -out gateway.cert -days 365 -sha256 -extfile gateway-server.ext
  openssl verify -CAfile gateway-dev-ca.crt -purpose sslserver \
    -verify_hostname localhost gateway.cert
  openssl verify -CAfile gateway-dev-ca.crt \
    -verify_ip 127.0.0.1 gateway.cert
  openssl verify -CAfile gateway-dev-ca.crt -purpose sslserver \
    -verify_hostname dev-gateway.dev.anatel gateway.cert
  openssl verify -CAfile gateway-dev-ca.crt -purpose sslserver \
    -verify_hostname "<HEADSCALE_FQDN>" gateway.cert
  openssl x509 -in gateway.cert -noout -dates -ext subjectAltName
)
```

Garanta que a CA continue válida durante todo o período de validade do certificado do servidor. As extensões de assinatura definem explicitamente os SANs emitidos; o CSR, por si só, não garante que eles apareçam no certificado.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 5. Instale e replique no host

Transfira o `gateway.cert` assinado e o `gateway-dev-ca.crt` público para o diretório pessoal do administrador do host por uma conexão SSH verificada. Nesse diretório, valide-os antes da instalação:

```bash
openssl verify -CAfile gateway-dev-ca.crt -purpose sslserver \
  -verify_hostname localhost gateway.cert
openssl x509 -in gateway.cert -pubkey -noout
sudo openssl pkey -in /etc/gateway/tls/gateway.key -pubout
```

Os dois blocos `PUBLIC KEY` completos devem corresponder. Interrompa o processo se a validação falhar ou se as chaves forem diferentes. Para um emissor organizacional, use a CA raiz na validação e `-untrusted intermediates.pem` quando necessário.

Depois da validação, instale o certificado principal em `/etc/gateway/tls/` e replique-o nos diretórios dos dois serviços no host:

```bash
# 1. Base storage on the host
sudo install -d -o root -g root -m 0700 /etc/gateway/tls
sudo install -o root -g root -m 0644 gateway.cert /etc/gateway/tls/gateway.cert
sudo stat -c '%U:%G %a %n' /etc/gateway/tls/gateway.cert /etc/gateway/tls/gateway.key

# 2. Replicate for Cockpit (host administration on TCP 9090)
sudo install -d -o root -g root -m 0755 /etc/cockpit/ws-certs.d
sudo install -o root -g root -m 0644 gateway.cert /etc/cockpit/ws-certs.d/50-gateway.crt
sudo install -o root -g root -m 0600 /etc/gateway/tls/gateway.key /etc/cockpit/ws-certs.d/50-gateway.key
sudo systemctl try-restart cockpit.socket cockpit.service 2>/dev/null || true

# 3. Replicate for Gateway VPN (Headscale on TCP 443 and Headplane on dev-gateway.dev.anatel)
sudo install -d -o root -g root -m 0750 /etc/gateway-vpn/tls
sudo install -o root -g root -m 0644 gateway.cert /etc/gateway-vpn/tls/fullchain.pem
sudo install -o root -g root -m 0600 /etc/gateway/tls/gateway.key /etc/gateway-vpn/tls/privkey.pem
```

A propriedade esperada é `root:root`; use os modos `0644` para certificados e `0600` para chaves privadas. Para uma cadeia organizacional, `gateway.cert` deve conter certificados PEM nesta ordem: primeiro o certificado do servidor e depois os certificados intermediários. Não inclua uma chave privada no arquivo de certificado.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 6. Compartilhe o material público de confiança

Distribua `gateway-dev-ca.crt`, a URL aprovada, as datas de validade e estas instruções para clientes por um canal interno autenticado. Para uma CA organizacional, use o processo aprovado de distribuição de confiança.

Publique a impressão digital SHA-256 do certificado da CA por um **canal verificado separado**, como uma chamada de voz com um administrador conhecido ou um aviso da equipe de TI gerenciada. Os desenvolvedores devem compará-la antes da importação. Um hash enviado junto com um download não verificado não autentica esse download.

Não compartilhe `gateway.key` nem `gateway-dev-ca.key`. Um navegador precisa do certificado público da CA, não da chave privada do servidor. Não inclua a senha do Cockpit no pacote do certificado; siga a política de credenciais da equipe.

### Windows 11

Salve o certificado PEM da CA como `$HOME\Downloads\gateway-dev-ca.crt`. Consulte a **impressão digital do certificado** SHA-256 no PowerShell:

```powershell
$path = "$HOME\Downloads\gateway-dev-ca.crt"
$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($path)
$cert.GetCertHashString([System.Security.Cryptography.HashAlgorithmName]::SHA256)
```

Compare o resultado com a impressão digital do administrador, ignorando separadores de dois-pontos e diferenças entre maiúsculas e minúsculas. Não compare o hash do arquivo com a impressão digital do certificado. Depois da validação, importe o certificado para o usuário atual do Windows:

```powershell
Import-Certificate -FilePath $path -CertStoreLocation Cert:\CurrentUser\Root
```

Isso confia na CA para aplicativos que usam o repositório raiz do Windows desse usuário. Só aceite a importação se a política local de TI permitir. Reinicie o navegador.

### macOS

Salve o certificado em `~/Downloads`. No Terminal:

```bash
openssl x509 -in "$HOME/Downloads/gateway-dev-ca.crt" -noout -sha256 -fingerprint
```

Depois de comparar a impressão digital, use o repositório de confiança do sistema somente com aprovação da equipe de TI:

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain "$HOME/Downloads/gateway-dev-ca.crt"
```

Isso altera a confiança em todo o sistema. Como alternativa, use o Acesso às Chaves para importar o certificado no chaveiro de início de sessão e aprovar a confiança SSL para o usuário atual, conforme a política. Reinicie o navegador.

### Linux

Primeiro, compare a impressão digital do certificado:

```bash
openssl x509 -in "$HOME/Downloads/gateway-dev-ca.crt" -noout -sha256 -fingerprint
```

Depois, use **somente** os comandos da sua distribuição. Eles alteram a confiança em todo o sistema.

Debian / Ubuntu:

```bash
sudo install -m 0644 "$HOME/Downloads/gateway-dev-ca.crt" \
  /usr/local/share/ca-certificates/gateway-dev-ca.crt
sudo update-ca-certificates
```

RHEL / Fedora:

```bash
sudo install -m 0644 "$HOME/Downloads/gateway-dev-ca.crt" \
  /etc/pki/ca-trust/source/anchors/gateway-dev-ca.crt
sudo update-ca-trust extract
```

Reinicie o navegador. Os repositórios de confiança de navegadores, containers, Java, Python e outros aplicativos podem ser diferentes do repositório do sistema operacional. Se o Firefox ou outro navegador não usar o repositório do sistema, siga a política gerenciada do navegador ou importe a CA verificada nas configurações de **Authorities** do navegador para identificação de sites. Não ignore avisos de certificado nem desative a validação.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## 7. Conecte-se e verifique

### Verificação do Cockpit (por túnel SSH)

No Windows PowerShell, Terminal do macOS ou Linux, inicie o túnel SSH:

```text
ssh -N -T -o ExitOnForwardFailure=yes -L 127.0.0.1:9443:127.0.0.1:9090 -p 22 host-admin@gateway-host
```

Abra `https://localhost:9443/`. O certificado deve ser válido, emitido pela CA esperada e conter `localhost` nos SANs, sem avisos de segurança.

Teste com curl:

```bash
curl --cacert gateway-dev-ca.crt --fail --show-error https://localhost:9443/ -o /dev/null
```

### Verificação do Headscale (endpoint antes da VPN)

Confirme que o endpoint externo responde com TLS válido na porta 443:

```bash
curl --cacert gateway-dev-ca.crt --fail --show-error "https://<HEADSCALE_FQDN>/health" -o /dev/null
```

### Verificação do Headplane (interface administrativa dentro da VPN)

Depois de se conectar à VPN e ativar o split DNS, verifique o acesso à interface do Headplane:

```bash
curl --cacert gateway-dev-ca.crt --fail --show-error https://dev-gateway.dev.anatel/admin -o /dev/null
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

## Renovação e remoção

Acompanhe as datas de validade do servidor e da CA. Renove antes do vencimento, mantendo o mesmo contrato de SANs. Prepare e valide os arquivos de substituição antes de uma janela de manutenção aprovada; nunca sobrescreva uma chave ativa durante a geração da substituta. Faça backup do par existente em armazenamento acessível somente por `root` para permitir rollback. Replique o novo certificado e a chave em `/etc/cockpit/ws-certs.d/` e `/etc/gateway-vpn/tls/`. Reinicie o socket e o serviço Cockpit e recarregue o container Gateway (`systemctl restart gateway.service`).

Para fazer a rotação da CA, valide e distribua a nova CA pública antes de trocar o certificado do servidor. Remova a CA antiga depois que todos os certificados dependentes forem aposentados. Se uma chave privada for exposta, pare de usá-la e siga o processo de resposta a incidentes da infraestrutura; emitir outro certificado, por si só, não invalida o antigo.

Para remover a confiança, remova a CA específica das Autoridades de Certificação Raiz Confiáveis do Usuário Atual do Windows, do Acesso às Chaves do macOS ou do certificado âncora instalado no Linux. No Linux, execute novamente o comando de atualização de confiança correspondente. Remova também importações separadas em navegadores. Identifique a CA pela impressão digital, não apenas pelo nome de exibição.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Faça backup do material de assinatura em armazenamento seguro aprovado

Neste guia, “repositório seguro” significa armazenamento de segredos aprovado e com controle de acesso ou um backup criptografado, **não este repositório Git de código-fonte**. A configuração do sistema de armazenamento está fora do escopo deste procedimento. Nunca envie chaves privadas ao controle de versão, mesmo que a chave da CA esteja criptografada com frase secreta.

Preserve estes itens da CA de desenvolvimento dedicada:

- **`gateway-dev-ca.key` — obrigatória e secreta:** a chave original de assinatura da CA, criptografada. Sem ela, não será possível emitir outro certificado sob a CA existente.
- **Frase secreta da chave da CA — obrigatória e secreta:** mantenha-a em armazenamento seguro aprovado separado, não junto da chave nem na configuração de assinatura. Um backup da chave sem uma frase secreta recuperável é inutilizável.
- **`gateway-dev-ca.crt` — obrigatório e público:** o certificado original da CA já confiado pelos desenvolvedores. Restaure exatamente esse certificado, em vez de gerar outro certificado de CA com o mesmo nome.
- **`gateway-server.ext` — configuração de assinatura reproduzível:** preserve os SANs aprovados, as restrições e o uso de servidor. Revise-a para cada nova solicitação; não reutilize cegamente a identidade de um host anterior.
- **Arquivos `gateway.cert` emitidos e respectivos arquivos `gateway.csr` — registros públicos:** mantenha-os com datas de emissão, números de série, datas de validade e nomes de host pretendidos. Eles ajudam na auditoria e na recuperação, mas não são necessários para gerar uma nova chave de servidor.
- **Impressão digital da CA e metadados de recuperação:** mantenha a impressão digital SHA-256 do certificado verificada de forma independente, o administrador responsável, os SANs aprovados e este procedimento de emissão.

A etapa 4 gera um número de série aleatório para cada certificado usando `-set_serial`; ela não cria um arquivo `.srl` nem um banco de dados de CA do OpenSSL. Este procedimento não tem arquivo de contador de números de série para restaurar. Se a organização usar outra ferramenta de CA, preserve o banco de dados, o estado dos números de série e os registros de revogação conforme o procedimento de recuperação dessa ferramenta.

Um **backup separado opcional para recuperação do servidor** pode conter o par correspondente `/etc/gateway/tls/gateway.key` e `/etc/gateway/tls/gateway.cert`. A chave do servidor não é criptografada em disco; portanto, o backup exige criptografia e acesso restrito. Esta é a exceção à regra de manter a chave somente no host: trata-se de uma cópia de recuperação do administrador, nunca de um artefato para distribuir a desenvolvedores. O par do servidor não é necessário para assinar uma nova chave de servidor.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Restaure o material de assinatura para uma nova chave de servidor

Use este procedimento ao substituir uma chave de servidor ou recuperar a estação de trabalho de assinatura. Ele reutiliza a CA existente; não cria outra.

1. Em uma estação de trabalho de assinatura controlada, crie um diretório privado novo fora do Git. Restrinja o acesso ao proprietário (`0700`). Restaure nele os arquivos originais `gateway-dev-ca.key` e `gateway-dev-ca.crt`. Restrinja a chave privada ao proprietário (`0600`) e obtenha sua frase secreta pelo processo de recuperação aprovado e separado.
2. Compare a impressão digital SHA-256 do certificado da CA restaurado com o registro verificado de forma independente, usando o comando da etapa 2. Inspecione as datas de validade. Confirme se ele continuará válido durante o período planejado para o certificado do servidor; caso contrário, siga o procedimento de rotação da CA.
3. Verifique a chave da CA restaurada com `openssl pkey -in gateway-dev-ca.key -check -noout`. O OpenSSL solicitará a frase secreta. Compare a saída completa da chave pública de `openssl pkey -in gateway-dev-ca.key -pubout` com `openssl x509 -in gateway-dev-ca.crt -pubkey -noout`. Interrompa se forem diferentes ou se qualquer validação falhar. Esses comandos não exibem a chave privada.
4. No host Gateway, gere uma **nova chave de servidor e um CSR** usando a etapa 3. Para uma implantação existente, use um diretório de preparação novo, acessível somente por `root`, e ajuste os caminhos de saída; a etapa 3 recusa-se deliberadamente a sobrescrever entradas existentes. Mantenha o par em uso até que a substituição esteja pronta.
5. Transfira somente o novo CSR para o diretório de assinatura restaurado. Revise sua chave pública, seu assunto e seus SANs. Restaure a configuração de assinatura salva como referência e use a etapa 4 para criar um `gateway-server.ext` revisado e emitir um certificado novo. Antes de executar a etapa 4, deixe inexistentes os arquivos de saída; a proteção da etapa recusa-se a sobrescrever arquivos existentes.
6. Valide e instale o novo par correspondente de servidor durante uma janela de manutenção aprovada, seguindo a etapa 5 e o procedimento de renovação. Para uma chave substituta preparada em staging, instale-a como `root:root`, modo `0600`, em `/etc/gateway/tls/gateway.key` e instale também o certificado assinado. Execute novamente o preflight e o apply e verifique o certificado apresentado aos desenvolvedores.
7. Atualize os registros de emissão do backup seguro e qualquer cópia de recuperação do servidor. Depois de concluir a assinatura, remova as cópias temporárias da chave privada da CA da estação de trabalho conforme a política de limpeza segura da organização. Mantenha o backup recuperável da CA criptografada.

Os desenvolvedores não precisam importar a CA novamente quando somente a chave e o certificado do servidor mudarem sob a mesma CA confiável e a URL continuar correspondendo aos SANs.

Se for restaurar o servidor existente em vez de gerar uma nova chave, recupere o par correspondente de chave e certificado do backup, confirme que correspondem e que o certificado continua válido, restaure a propriedade e os modos descritos na etapa 5 e execute novamente o preflight e o apply. Não restaure uma chave comprometida nem um certificado expirado.

Se a chave ou a frase secreta da CA for perdida, o certificado público da CA não poderá recuperar a chave de assinatura. Crie uma CA nova por meio de uma rotação aprovada e redistribua seu certificado público e a impressão digital verificada. O comprometimento de uma CA também exige resposta a incidentes e remoção da confiança antiga; restaurar o backup não a torna segura.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
