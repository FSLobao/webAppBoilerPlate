# Web Application Boilerplate — Arquitetura Lógica e Contrato de Desenvolvimento

**Status:** Proposta arquitetural — baseline para implementação  
**Objetivo:** Definir o contrato técnico e operacional do boilerplate para desenvolvimento de aplicações web com Python/FastAPI, frontend JavaScript, PostgreSQL e execução integral em containers.

---

## 1. Objetivo

Este documento define a arquitetura lógica, responsabilidades, limites e princípios do boilerplate.

O documento deve ser tratado como **contrato arquitetural** durante o desenvolvimento no VS Code. Alterações que modifiquem os princípios aqui definidos devem ser deliberadas e registradas antes da implementação.

O boilerplate deve privilegiar:

- simplicidade operacional;
- reprodutibilidade;
- baixo esforço administrativo;
- redes app-specific únicas e autenticação de serviço; a rede `shared` oferece conectividade direta aos seus membros;
- desenvolvimento remoto por VS Code;
- manutenção direta dos containers;
- deployment reproduzível a partir do host;
- mínimo de dependências no host RHEL 9.8 com Podman rootful 5.8.2;
- separação entre acesso administrativo e prestação do serviço;
- configuração versionada no Git;
- utilização preferencial de componentes maduros em vez de software administrativo desenvolvido especificamente para o boilerplate.

---

# 2. Ambiente-alvo

## 2.1 Host

O ambiente de produção/desenvolvimento remoto é suportado por:

- Red Hat Enterprise Linux 9.8 como alvo de qualificação;
- Podman 5.8.2 em modo rootful e Quadlet como alvo de deployment;
- SELinux desativado, conforme decisão explícita do solicitante;
- acesso administrativo ao host restrito à equipe responsável pela infraestrutura;
- autenticação do acesso ao host realizada pelos mecanismos corporativos existentes;
- firewall e controles de acesso externos ao ambiente dos containers.

O boilerplate **não deve exigir acesso administrativo permanente dos desenvolvedores ao host RHEL**.

Desativar SELinux remove controles obrigatórios de acesso e reduz o isolamento do host. O deployment deve validar que SELinux já está desativado; não deve alterar essa configuração.

O host é responsável principalmente por:

- executar Podman;
- fornecer armazenamento;
- executar os containers;
- aplicar a configuração inicial do ambiente;
- executar operações excepcionais de infraestrutura.

---

# 3. Princípio fundamental de isolamento

A arquitetura separa o perímetro de segurança e três planos funcionais:

```text
                  ┌──────────────────────────┐
                  │ Security Perimeter       │
                  │ VPN / Firewall / ACL /   │
                  │ Authentication           │
                  └────────────┬─────────────┘
                               │
               ┌───────────────┴────────────────┐
               │                                │
               ▼                                ▼
       Management Plane                 Application Plane
       Developer access                 User access
               │                                │
               ▼                                ▼
       Development Gateway    Optional NGINX HTTP proxy
               │                                │
               ▼                                ▼
          Podman networks                App endpoints
```

## 3.1 Security perimeter

O controle de quem pode alcançar o ambiente não pertence ao boilerplate.

Inclui, conforme a infraestrutura disponível:

- VPN corporativa;
- firewall externo;
- ACL;
- autenticação;
- autorização de acesso ao host/endpoint;
- controle de portas de entrada.

O Gateway assume que uma conexão que chegou até ele já passou pelos mecanismos externos de autorização.
Essa premissa descreve o acesso administrativo ao Gateway; não comprova a identidade HTTP apresentada
à aplicação nem torna confiáveis campos `X-USER` recebidos por um caminho de bypass.
Para acesso HTTP de usuários, o perímetro autentica o usuário, remove ou substitui campos de identidade
fornecidos pelo cliente e injeta os campos `X-USER` confiáveis. A aplicação usa esses campos para
autorizar operações; o NGINX somente encaminha HTTP e não autentica usuários. A lista exata de campos
`X-USER` e o mecanismo que comprova a proveniência do perímetro permanecem pré-requisitos de
implementação. Endpoints protegidos rejeitam identidade ausente ou não confiável.

## 3.2 Management Plane

Responsável por:

- acesso SSH;
- túneis;
- túneis, roteamento IP e forwarding;
- DNS de desenvolvimento;
- diagnóstico de rede;
- Cockpit;
- gerenciamento Podman;
- acesso de manutenção aos containers.

## 3.3 Application Plane

Responsável por executar:

- backend;
- frontend;
- workers;
- banco de dados;
- outros serviços específicos da aplicação.

## 3.4 Application Access Plane

Responsável por disponibilizar a aplicação aos usuários/consumidores.

O acesso de usuários HTTP pode usar o proxy NGINX compartilhado opcional. Serviços não HTTP são
publicados diretamente por bind de host, protocolo e porta publicados explicitamente; cada serviço
mantém sua autenticação e o perímetro controla a exposição. Esse plano é independente do Development
Gateway, que fornece somente acesso de desenvolvimento aos serviços configurados.

---

# 4. Containers principais

O boilerplate define quatro categorias lógicas de containers.

## 4.1 Gateway

Container compartilhado entre todas as aplicações.

Responsabilidades:

- SSH;
- DNS;
- routing;
- servidor WireGuard IPv4-only para peers de desenvolvimento;
- cliente OpenVPN e SSH TUN, mantidos como caminhos separados;
- forwarding roteado entre túneis ativos e todas as redes Podman configuradas;
- acesso às redes de desenvolvimento das aplicações;
- ferramentas de diagnóstico;
- Cockpit;
- cockpit-podman.

O acesso remoto de desenvolvedores preserva o IP IPv4 de origem e não usa NAT. O contrato de túneis,
destinos roteados, pools, pares de endereços ponto a ponto, rotas de retorno e DNS do Gateway é
IPv4-only; DNS publica registros A, não AAAA. Isso não desativa IPv6 no host, Gateway, VM ou cliente.
O runtime não força IPv4 na conexão SSH externa; clientes que precisam dessa família usam `ssh -4`.
O egress iniciado por containers usa a saída normal do Podman rootful no host e pode usar masquerading.

WireGuard é um servidor aditivo no Gateway; não substitui o cliente OpenVPN nem SSH TUN. O runtime
WireGuard, seu schema/configuração, gerenciamento de peers e integração DNS ainda não existem.
OpenVPN client e SSH TUN permanecem opt-in e desativados na configuração versionada. O runtime SSH
TUN está implementado, mas ativação real e aceitação em host-alvo permanecem pendentes. O perfil
OpenVPN externo exige revisão humana e o gate `profile_reviewed: true`; diretivas IPv6 locais não
são suportadas pelo runtime.

O Gateway é uma **unidade administrativa única**.

Não deve ser criado um gateway independente por aplicação salvo necessidade arquitetural futura claramente justificada.

---

## 4.2 HTTP proxy opcional

Container NGINX opcional e compartilhado, distinto do Development Gateway. Ele fornece somente
reverse proxy HTTP; não representa um componente geral de acesso a aplicações.

Responsabilidade:

- encaminhar as rotas HTTP configuradas para serviços de aplicação;
- receber HTTP do perímetro externo, que fornece TLS, certificados, DNS público e autenticação de usuários;
- opcionalmente servir downloads/arquivos estáticos somente para leitura, fora da SPA.

NGINX é o único provedor HTTP previsto. Instale-o somente quando `http_proxy` estiver habilitado. Ele
não implementa login, autenticação ou autorização e não é canal de manutenção de containers.

O perímetro remove ou substitui valores de identidade enviados pelo cliente e injeta os campos
`X-USER` confiáveis. A aplicação usa esses valores para autorização. A lista exata permitida e o
mecanismo de proveniência ainda precisam ser definidos e verificados como pré-requisito de
implementação; um CIDR ou um header bruto não prova identidade. O listener HTTP atualmente vincula
`0.0.0.0:8080`, e o Development Gateway fornece um caminho de bypass aos containers. Antes de expor
rotas protegidas, o deployment deve exigir restrição efetiva de ingresso ao perímetro confiável ou
proveniência perímetro-aplicação verificada. Acesso direto pelo Gateway ou ao listener do host não
confere confiança aos campos `X-USER`; endpoints protegidos rejeitam identidade ausente ou não
confiável.

---

## 4.3 Application containers

Cada aplicação pode possuir:

- backend;
- frontend;
- worker;
- scheduler;
- serviços auxiliares.

Na configuração inicial, os assets frontend e FastAPI serão servidos pelo mesmo processo no container `webApp`; PostgreSQL permanece em container separado. Serviços auxiliares podem usar containers próprios.

As imagens do Gateway e das aplicações devem usar uma distribuição Linux eficiente e mantida,
preferencialmente Debian ou Alpine. A distribuição do container é independente do host RHEL.

---

## 4.4 Database

PostgreSQL deve ser executado em container.

O banco deve possuir armazenamento persistente através de volume dedicado.

PostgreSQL não recebe porta publicada diretamente no host. Desenvolvedores com acesso roteado ao Gateway podem alcançar a rede do banco; PostgreSQL deve aplicar sua própria autenticação e autorização.

PostgreSQL conecta-se a `webApp` e `shared`. Todos os containers em `shared`, inclusive NGINX e Gateway, têm alcance de rede ao banco. A rede não isola frontend e backend quando ambos compartilham o container `webApp`; o deployment deve limitar credenciais à identidade de processo do FastAPI. A viabilidade desse limite permanece um gate.

---

# 5. Gateway

## 5.1 Composição

O Gateway será um único container baseado em Debian minimal.

Componentes previstos:

```text
Debian
├── OpenSSH
├── DNS service
├── routing / IP forwarding
├── OpenVPN client
├── SSH TUN / TCP forwarding
├── iproute2
├── ss
├── tcpdump
├── conntrack
├── ferramentas básicas de diagnóstico
├── Cockpit
└── cockpit-podman
```

Componentes adicionais somente devem ser incluídos quando houver necessidade operacional clara.

---

## 5.2 Cockpit

Cockpit será a interface administrativa principal.

Funções esperadas:

- visualização do estado do sistema;
- logs;
- terminal;
- diagnóstico;
- administração de containers;
- administração Podman;
- visualização de recursos;
- acompanhamento das redes.

O Cockpit não participa do caminho dos dados das aplicações.

Ele funciona como **control plane**, não como proxy de aplicação.

---

## 5.3 cockpit-podman

O `cockpit-podman` será utilizado para administração dos containers Podman.

A comunicação com Podman deve preferencialmente utilizar Unix socket/API local.

Não expor o Podman API diretamente por TCP, salvo decisão arquitetural futura explicitamente documentada.

O acesso ao socket deve ser limitado aos privilégios necessários.

---

# 6. Modelo de privilégios do Gateway

O gateway necessita de capacidades de rede para:

- forwarding;
- routing;
- acesso às redes Podman;
- servidor WireGuard, cliente OpenVPN e SSH TUN.

Entretanto, o container não deve receber acesso indiscriminado ao host RHEL.

Particularmente, deve-se evitar, sem justificativa:

- montagem do filesystem completo do host;
- acesso irrestrito a `/proc` do host;
- acesso irrestrito a `/sys` do host;
- execução `--privileged` quando capacidades específicas forem suficientes;
- exposição remota do Podman socket.

A configuração final de capabilities será definida durante a implementação e validada em RHEL 9.8 com Podman rootful 5.8.2 e SELinux desativado. Use somente capabilities mínimas, incluindo `NET_ADMIN` apenas se a implementação WireGuard/túnel demonstrar necessidade. Não use `--privileged`. O deployment não altera a configuração de segurança do host.

---

# 7. Firewall

O Gateway **não é concebido como firewall de segurança do ambiente**.

O controle de acesso externo ocorre antes da chegada da conexão ao gateway.

Portanto:

- não haverá interface de firewall para autorização de desenvolvedores;
- regras de segurança do gateway serão mínimas e estáveis;
- regras estruturais poderão ser configuradas pelo deployment;
- mudanças operacionais de autorização não serão feitas pelo Cockpit.

O uso de `firewalld` não é requisito da arquitetura.

`nftables` ou mecanismo equivalente poderá ser utilizado somente para as funções técnicas necessárias ao funcionamento do gateway, caso sejam necessárias.

---

# 8. Redes Podman

## 8.1 Princípio

O array top-level `networks` em `config/host_config.json` é o inventário global das redes Podman
declaradas para aplicações e serviços. Cada aplicação deve possuir uma rede Podman própria com CIDR exclusivo.

Exemplo do formato de registro (o sufixo interno aprovado é `dev.anatel`):

```text
project-a-net
project-b-net
project-c-net
```

As redes app-specific não roteiam entre si. A topologia inicial também conecta todos os containers de aplicação e PostgreSQL à rede `shared`; essa rede fornece conectividade direta e exige autenticação/autorização em cada serviço.

`networks` descreve somente essas redes Podman de aplicação, não interfaces físicas/do host, redes do host, rotas VPN ou pools de endereços de túneis. A rede Podman `shared` é uma bridge compartilhada por seus membros; ela não é uma interface física do host nem uma interface de host compartilhada com o Gateway.

---

## 8.2 Gateway compartilhado

O Gateway compartilhado possui uma interface Podman para cada rede declarada no inventário global top-level `networks` de `config/host_config.json`, incluindo `shared`. Ele não mantém uma lista seletiva de redes por serviço:

```text
                 Gateway
                  /        |        \
                 /         |         \
        project-a-net project-b-net project-c-net
```

O Gateway administra todas as redes declaradas sem rotear entre redes app-specific. A rede `shared` é uma exceção explícita: seus membros podem comunicar-se diretamente na mesma rede.

O JSON declara o endereço da interface Podman do Gateway em cada rede. Esse endereço atende DNSMasq para os containers conectados à rede. Não confunda essas interfaces de rede Podman com interfaces físicas/do host ou interfaces de túnel.

A configuração declara `shared` e `webApp` no inventário top-level `networks`, mantendo o Gateway conectado a todas as redes declaradas. Aplicações futuras adicionam cada rede Podman nova somente a esse inventário e reconciliam o Gateway existente.

---

## 8.3 Isolamento

Por padrão:

```text
project-a-net  ──X── project-b-net
project-a-net  ──X── project-c-net
project-b-net  ──X── project-c-net
```

Não há roteamento entre redes específicas de aplicações. A rede `shared`, porém, conecta diretamente todos os containers associados a ela. A topologia selecionada inclui `webApp` e PostgreSQL; por isso, esses serviços podem iniciar conexões uns com os outros sem atravessar o Gateway.

O Gateway também conecta-se a todas as redes e pode alcançar todos os containers, inclusive bancos. Nem redes específicas nem `shared` protegem esses serviços de um Gateway comprometido. Mantenha autenticação nos destinos e trate o Gateway como componente administrativo de alto privilégio.

Como frontend e FastAPI compartilham o container `webApp`, a rede não separa os processos. O deployment deve limitar as credenciais PostgreSQL à identidade de processo do FastAPI.

---

# 9. DNS de desenvolvimento

## 9.1 DNSMasq

O Gateway deverá executar **DNSMasq** como serviço DNS de desenvolvimento.

O objetivo é fornecer aos desenvolvedores resolução de nomes para os serviços dos containers sem exigir conhecimento ou gerenciamento manual de seus endereços IP.

O fluxo esperado é:

```text
Developer
    │
    │ DNS query
    ▼
Gateway
    │
    ▼
DNSMasq
    │
    ▼
generated DNS configuration
    │
    ▼
current container address on its declared Podman network
```

## 9.2 Configuração gerada pelo deployment

A configuração do DNSMasq deverá ser gerada ou atualizada pelo mecanismo de deployment.

O deployment deverá conhecer a relação entre:

```text
application
    └── service
          ├── current container address and declared network
          ├── Gateway DNS address on that network
          └── DNS answer for routed clients
```

e produzir os registros DNS correspondentes.

Exemplo:

```text
backend.project-a.dev.anatel
frontend.project-a.dev.anatel
backend.project-b.dev.anatel
```

A configuração deverá ser regenerável sem intervenção manual dentro do container do gateway.

Containers e clientes remotos consultam DNSMasq no endereço do Gateway correspondente à sua rede ou túnel. DNSMasq resolve nomes declarados para os endereços atuais dos containers. Clientes remotos precisam de rotas até os CIDRs Podman; o acesso não usa NAT nem portas traduzidas. Consultas de domínios não declarados seguem para os resolvers upstream configurados no host.

## 9.3 Nomes internos e externos

A arquitetura deverá distinguir explicitamente:

### Nomes internos de desenvolvimento

Utilizados pelos desenvolvedores e pelas ferramentas de manutenção.

Exemplos:

```text
backend.project-a.dev.anatel
frontend.project-a.dev.anatel
dev-gateway.dev.anatel
```

Esses nomes apontam para endereços atuais das redes Podman. Clientes remotos consultam DNSMasq por WireGuard, OpenVPN ou SSH TUN e precisam de rotas para os CIDRs correspondentes. WireGuard não configura split DNS nativamente; cada sistema operacional precisa de uma regra para `dev.anatel`. ProxyJump sozinho não transporta consultas DNS.

### Nomes externos de aplicação

Utilizados pelos usuários/consumidores da aplicação.

Exemplos conceituais:

```text
app-a.example.com
api-a.example.com
```

Esses nomes são responsabilidade da infraestrutura DNS e do perímetro externos, assumidos fora do escopo deste host.

Os namespaces interno e externo não devem ser tratados como equivalentes.

## 9.4 Containers recriados

Os endereços IP individuais dos containers não constituem identidade permanente.

Quando um container for recriado, o deployment deverá atualizar o registro DNS para o novo endereço. As rotas cobrem o CIDR da rede e não dependem do endereço individual do container.

O desenvolvedor continuará utilizando o mesmo nome lógico.

```text
backend.project-a.dev.anatel
        │
        ▼
   current backend IP
```

## 9.5 Escopo

O Gateway deve disponibilizar resolução para todas as aplicações cujas redes estejam conectadas ao gateway.

Registros DNS não criam conectividade; ela depende das interfaces declaradas. Serviços em redes app-specific distintas não têm rota entre si, mas os membros de `shared` comunicam-se diretamente.

## 9.6 Serviços publicados no DNS

Somente serviços declarados em `dns_records` recebem nomes DNS de desenvolvimento. O Gateway e os clientes autorizados têm alcance de rede a todos os serviços configurados, inclusive bancos de dados; cada serviço controla sua própria autenticação e autorização.

---

# 10. Alocação de redes

Cada aplicação deve receber um CIDR próprio.

Exemplo:

```text
project-a → 10.89.1.0/24
project-b → 10.89.2.0/24
project-c → 10.89.3.0/24
```

Os CIDRs não podem se sobrepor.

Os endereços de desenvolvedores vêm de pools de túnel dedicados, nunca dos CIDRs Podman. O servidor WireGuard terá pool IPv4 ainda não definido; o servidor OpenVPN externo aloca os endereços de seus clientes; o pool SSH TUN é uma entrada de deployment e aloca pares ponto-a-ponto distintos por sessão. Descubra os endereços/rotas ativos e compare-os com redes Podman e rotas relevantes do host, da LAN dos desenvolvedores e corporativas antes de instalar estado.

O perfil OpenVPN permanece externo, privado e exclusivo do Gateway. A infraestrutura externa provisiona rotas para cada CIDR Podman via cliente OpenVPN do Gateway. O servidor WireGuard será executado pelo Gateway; seu pool, endereço de servidor, endpoint, porta UDP, resolver e sistema operacional cliente são inputs de deployment, não decisões selecionadas.

Endereços IP individuais de containers não devem ser tratados como identificadores permanentes.

---



---

# 11. Acesso SSH e VS Code

O Gateway será o ponto de entrada para acesso SSH aos containers. ProxyJump encaminha conexões SSH TCP ao destino, onde ocorre a autenticação. SSH TUN (`ssh -w`) fornece conectividade IP roteada completa e também permite consultas DNS do cliente ao Gateway. São caminhos diferentes: ProxyJump não exige nem substitui o túnel.

O objetivo é permitir utilização do:

**VS Code Remote - SSH**

ou mecanismos equivalentes.

## 11.1 Papel do gateway no SSH

Para acesso aos containers das aplicações, o Gateway deverá atuar como **gateway de forwarding**, e não como autoridade de autenticação dos desenvolvedores.

O gateway não deverá validar a identidade do desenvolvedor para os containers de aplicação. A autenticação SSH deverá ocorrer no próprio destino, utilizando as credenciais/chaves configuradas para aquele container.

Conceitualmente:

```text
Developer
   │
   │ SSH connection
   ▼
Gateway
   │
   │ forwarding only
   ▼
Application container
   │
   │ SSH authentication
   ▼
Developer identity
```

O gateway deverá, portanto, encaminhar a conexão sem substituir a autenticação SSH do destino. O servidor SSH do destino, a conta de desenvolvedor, a chave pública de destino e os pré-requisitos do VS Code Server precisam existir no container/host de destino; o Gateway não os provisiona por ProxyJump.

ProxyJump é um caminho TCP para SSH; não substitui o túnel IP SSH TUN, não fornece DNS do cliente e não altera suas rotas. Os dois caminhos são suportados.

### 11.6 Caminhos do VS Code Remote-SSH

Há dois caminhos documentados, com aliases SSH distintos:

- **Direto por SSH TUN:** depois que `ssh -w` estiver ativo e as rotas split do CIDR Podman estiverem instaladas, o VS Code conecta-se diretamente ao endereço/DNS do container. Esse caminho usa roteamento IP e não depende do host ter portas SSH publicadas.
- **ProxyJump sem SSH TUN:** o VS Code conecta-se ao Gateway e usa `ProxyJump` para encaminhar TCP/22 ao destino. Isso não fornece conectividade Layer 3, DNS do cliente nem acesso a protocolos/portas arbitrários.

Use identidade privada de Gateway somente no alias Gateway e a chave de destino autorizada no servidor de destino. Mantenha verificação de chave de host habilitada (`StrictHostKeyChecking yes`) e entradas conhecidas separadas por destino/alias; não desative verificação nem reutilize uma identidade de host pública entre destinos diferentes. O servidor SSH e a conta de desenvolvedor do destino, a chave pública correspondente e os requisitos de instalação/execução do VS Code Server são pré-requisitos externos ao Gateway.

## 11.2 Acesso ao próprio Gateway

O próprio container do Gateway constitui uma exceção.

Quando o objetivo for administrar o gateway em si, a conexão será terminada no próprio container e sua autenticação SSH será realizada por ele.

O gateway deverá possuir sua própria identidade/nome DNS de administração, distinta dos nomes dos containers das aplicações.

Exemplo conceitual:

```text
dev-gateway.dev.anatel
backend.project-a.dev.anatel
frontend.project-a.dev.anatel
```

## 11.3 Chaves individuais

Cada desenvolvedor deverá possuir sua própria chave SSH.

Não serão utilizadas chaves privadas compartilhadas entre desenvolvedores.

A chave privada permanece no equipamento do desenvolvedor. O ambiente recebe apenas a chave pública necessária para autenticação nos destinos correspondentes.

## 11.4 Bootstrap de chaves

O mecanismo de deployment deverá suportar a configuração inicial das chaves públicas necessárias.

O bootstrap poderá receber múltiplas chaves públicas por container em um arquivo root-managed, configurado por destino, e instalá-las em uma conta de destino não-root dedicada. O arquivo fica fora do Git e é montado no container somente para leitura.

O caminho padrão no host é `/etc/gateway/application-keys/<container>/authorized_keys`; o caminho efetivo deve ser configurável no JSON. Use `root:root` e modo `0600`. Monte o arquivo somente para leitura em `/home/<account>/.ssh/authorized_keys` no container habilitado para SSH.

Isso permite que um ambiente novo seja disponibilizado já com o acesso SSH configurado, sem exigir que um administrador entre manualmente no container para configurar o primeiro usuário.

As chaves privadas nunca deverão ser copiadas para o ambiente pelo deployment.

A administração posterior das chaves poderá ser realizada pelo mecanismo de deployment ou por ferramentas administrativas, conforme definido pela infraestrutura.

## 11.5 Cockpit e administração de chaves

Cockpit não será tratado como mecanismo obrigatório para provisionamento inicial das chaves SSH dos desenvolvedores.

Embora o Cockpit possa fornecer funções de administração de usuários/SSH no próprio sistema, o contrato do boilerplate deverá privilegiar o **deployment declarativo** para o bootstrap das chaves.

Isso mantém a configuração:

- reproduzível;
- auditável;
- independente de intervenção manual no container.

O conteúdo das chaves públicas poderá ser fornecido externamente ao repositório conforme a política de acesso da organização.

O host RHEL não deve ser requisito para a conexão diária do desenvolvedor.

# 12. Acesso WireGuard, OpenVPN e SSH TUN

O Gateway deverá acrescentar um servidor WireGuard IPv4-only para onboarding de peers de
desenvolvimento. Ele coexistirá com o cliente OpenVPN existente e SSH TUN (`ssh -w`); não os
substituirá nem alterará seus perfis, pools ou regras. O servidor WireGuard termina no container
Gateway. O host publica o listener UDP do container; endpoint e porta permanecem inputs de
deployment. Nenhum painel ou API administrativa pública será criado.

Todos os peers WireGuard aprovados recebem rotas split para **todos os CIDRs** no array top-level
`networks`, incluindo `shared`, redes de aplicações e redes de PostgreSQL. A configuração atual
inclui `192.168.9.0/24` (`shared`) e `192.168.8.0/29` (`webApp`). Esses valores não definem o pool
WireGuard nem o endereço do resolver. O pool de peers, endereço IPv4 do servidor no túnel, endpoint,
porta UDP publicada e resolver DNS são inputs pendentes. Valide-os contra rotas locais, LAN, Podman
e redes corporativas antes da ativação. Clientes não recebem rota default pelo túnel. WireGuard não
distribui rotas nem DNS: cada perfil cliente declara `AllowedIPs` para os dois CIDRs Podman e
qualquer endereço do resolver que precise alcançar.

O namespace interno é exatamente `dev.anatel`, interno e não público. DNS gera somente registros A;
não cria AAAA. Registros declarados ainda estão vazios. Configure `dev.anatel` por split DNS em cada
sistema operacional, sem substituir o resolver global nem redirecionar DNS externo. WireGuard não
configura split DNS pelo arquivo nativo do túnel. Consulte os rascunhos para
[Windows 11](../recipes/wireguard-windows-11.md), [Linux](../recipes/wireguard-linux.md) e
[macOS](../recipes/wireguard-macos.md). O gerador DNS atual usa nomes declarados sem sufixo fixo;
`dns_records` segue vazio, e nenhum split DNS WireGuard existe. Exemplos documentais antigos usavam
`.dev.internal`. O schema/runtime de peer e a integração split DNS de cada sistema operacional
precisam ser implementados antes do uso.

O fluxo de peer exige identidade administrativa autenticada, aprovação explícita, inventário
auditável, rotação e revogação que removam a configuração ativa. Qualquer pessoa com privilégio
administrativo no container Gateway poderá executar essas operações e terá, por isso, alcance
roteado a todos os serviços, inclusive PostgreSQL. Autenticação e autorização de serviço continuam
obrigatórias; conectividade VPN não concede credenciais. Não haverá API/HTTP de administração
exposta publicamente.

Por decisão solicitada, o serviço deverá gerar a chave privada de cada peer dentro do Gateway e
entregá-la uma única vez por canal autenticado e não público; não deve persistir nem registrar essa chave. Isso
implica plaintext transitório em memória. Canal, identidade de operador, autorização, aprovação,
auditoria, formato da entrega e recuperação ainda exigem design. A chave privada do servidor será
root-owned, externa ao Git e consumida somente pelo WireGuard. A chave privada de cliente não é a
chave pública do peer: a chave pública é cadastrada no servidor. Receitas não inventam comandos,
endpoints ou telas antes da implementação.

WireGuard, OpenVPN e SSH TUN usam IPv4 para este contrato; isso não desativa IPv6 no host nem nos
clientes. Não haverá NAT, DNAT/SNAT ou forwarding entre redes de aplicações. Peers podem alcançar
qualquer serviço nos CIDRs configurados; cada serviço mantém sua autenticação. SSH TUN mantém seus
próprios usuários, pool, sessões e lifecycle. O servidor OpenVPN externo continua gerenciado
externamente e aloca endereços ao cliente OpenVPN do Gateway. `push_domains: ["anatel.gov.br"]`
permanece configuração separada do OpenVPN; não será reaproveitada como domínio WireGuard.

Pools, endpoints, CIDRs Podman e rotas relevantes do host, LAN dos desenvolvedores e rede corporativa
não podem se sobrepor. Prefixo de cliente ambíguo entre transportes falha fechado; não selecionar
automaticamente multihoming. Reconnect OpenVPN revalida rotas/endereço candidatos antes de ativá-los.
Pool WireGuard, endpoint, porta, resolver, operadores autorizados e regras de entrega da chave são
inputs pendentes.


---

# 13. Roteamento, egress e forwarding

O acesso remoto de desenvolvedores usa roteamento IP entre peers WireGuard, o cliente OpenVPN do Gateway ou sessões SSH TUN e todos os CIDRs Podman declarados no JSON. É split tunnel: somente destinos Podman configurados recebem rotas pelo túnel; a rota default, o egress normal do cliente/container e o IP de origem do desenvolvedor são preservados. O acesso permite qualquer protocolo e porta, sem DNAT ou SNAT e sem aprovação de forwarding por serviço. Autenticação/autorização pertencem a cada container/serviço.

Direção de rotas:

1. Peers WireGuard recebem `AllowedIPs` com cada CIDR Podman configurado. O servidor OpenVPN externo aloca endereços de cliente e o dono externo direciona cada CIDR Podman ao cliente OpenVPN do Gateway. Clientes SSH TUN recebem rotas da própria sessão.
2. O Gateway alcança cada CIDR Podman pelas rotas conectadas às interfaces Podman já anexadas. Não instale rota de CIDR de aplicação de volta por um túnel de desenvolvedor.
3. No Gateway, cada prefixo de cliente remoto retorna pelo túnel que o possui. Cada sessão SSH TUN possui interface e par de endereços únicos, com rotas alocadas e removidas por lifecycle hook daquela sessão.
4. Containers enviam replies pela rota Podman normal ao host. O host instala um próximo salto determinístico do Gateway por prefixo de cliente remoto, não cópias concorrentes do mesmo prefixo por cada rede Podman. Se testes mostrarem que tabelas de policy routing são necessárias, elas devem ser explícitas e ter propriedade/reconciliação definida.

Antes de alterar estado, validar pools/endpoints OpenVPN e SSH, rotas candidatas, CIDRs Podman e rotas relevantes do host/LAN/corporativas. Permitir rotas gerenciadas exatas e redes conectadas Podman/túnel necessárias; não rejeitar em bloco rotas default ou ranges conectados necessários. Rotas e regras têm proprietário identificável, reconciliação idempotente e rollback limitado ao estado candidato possuído pelo Gateway/sessão. Candidato inválido não altera rotas, forwarding, DNS ou serviços. Reconnect OpenVPN revalida alterações de rotas pushed antes da ativação. Não há watcher genérico; hooks de sessão são separados e limitados ao ciclo de vida de protocolo.

Containers podem iniciar conexões para qualquer destino externo alcançável pela rota padrão do host. O egress usa o caminho normal do Podman rootful e pode usar masquerading; serviços externos verão o endereço de saída do host. Esse comportamento é separado do acesso remoto de desenvolvedores, que preserva o IP de origem.

O Gateway encaminha tráfego entre túneis ativos e CIDRs Podman e tráfego de resposta relacionado, mas nunca entre redes de aplicações. Sua interface em cada rede permite alcançar todos os serviços, inclusive PostgreSQL; cada serviço deve controlar sua própria autenticação e autorização.

---

# 14. HTTP reverse proxy e publicação de serviços

O Development Gateway é exclusivamente para acesso de desenvolvedores aos serviços e portas de
containers configurados. Esse acesso roteado não depende de portas publicadas no host. NGINX é
apenas um proxy HTTP opcional, não um componente geral de acesso a aplicações.

Exemplo:

```text
Internet / Corporate users
          │
          ▼
Optional NGINX HTTP reverse proxy
          │
          ├── Application A
          ├── Application B
          └── Application C
```

Pode utilizar:

- HTTP;
- virtual hosts;
- reverse proxy.

O acesso de desenvolvimento não depende do proxy HTTP.

Use NGINX como proxy HTTP opcional somente quando `http_proxy` estiver habilitado. O container escuta
TCP 80; o endereço de bind e a porta publicada no host ficam no JSON. O bind selecionado permanece
`0.0.0.0:8080`; não o altere silenciosamente. O perímetro externo fornece DNS público, certificados,
TLS e autenticação, e encaminha HTTP ao host. Na aplicação inicial `webApp`, FastAPI no único
listener `webApp:8000` serve a SPA em `/app/` e a API em `/app/api/`; NGINX encaminha ambas ao mesmo
listener e avalia a rota da API antes do fallback SPA. Não há portas separadas de frontend e API
nessa aplicação inicial. Outras aplicações HTTP podem declarar seus próprios upstreams e portas;
`webApp:8000` não é uma restrição global do proxy.

O perímetro autentica usuários e injeta campos de identidade `X-USER` confiáveis após remover ou
substituir valores fornecidos pelo cliente. A aplicação usa esses campos para autorização. NGINX
somente faz proxy; não há engine de login/autenticação. A lista exata dos campos `X-USER` e o
mecanismo de proveniência confiável permanecem pré-requisitos de implementação, não decisões abertas.
Como o listener está em `0.0.0.0:8080` e o Gateway permite bypass direto, a implantação de rotas
protegidas exige um gate: restringir efetivamente o ingresso ao perímetro confiável ou verificar a
proveniência de identidade até a aplicação. CIDR ou header bruto não provam autenticação. Acesso
direto pelo Gateway ou ao listener do host não torna confiáveis os campos `X-USER`; endpoints
protegidos devem rejeitar identidade ausente ou não confiável.

Serviços não HTTP destinados a usuários são publicados diretamente com bind de host, protocolo e
portas publicados declarados explicitamente. Cada serviço aplica sua própria autenticação e depende
dos controles de perímetro. O Development Gateway alcança todos os serviços/portas configurados sem
publicar essas portas de serviço no host; o listener UDP WireGuard é uma publicação separada.
Não configure rate limiting NGINX por padrão. Limite
uploads a 1 GB por padrão no NGINX e no serviço TUS. O compartilhamento básico de arquivos por NGINX
é opcional, somente para leitura e fora da SPA.

---

# 15. Backend

O backend será implementado em:

- Python;
- FastAPI;
- ambiente Python versionado;
- processo no container combinado `webApp`.

Responsabilidades:

- API REST/HTTP;
- lógica de negócio;
- acesso ao PostgreSQL;
- integração com serviços externos;
- autorização da aplicação com base na identidade `X-USER` autenticada pelo perímetro, quando aplicável.

O backend não deve assumir responsabilidades de infraestrutura do gateway.

---

# 16. Frontend

O frontend será composto por componentes JavaScript.

O boilerplate deve permitir evolução futura do framework sem alterar a arquitetura de infraestrutura.

Na aplicação inicial, os assets Vite são construídos como arquivos estáticos no container `webApp`.
FastAPI serve a SPA em `/app/` e a API em `/app/api/*` pelo mesmo listener interno TCP `8000`; NGINX,
quando habilitado, faz proxy de ambas as rotas para esse único listener. Não há processo frontend
nem listener separado nesse stack inicial. Outras aplicações HTTP podem usar upstreams e portas
próprios configurados no proxy.

Use Vite com módulos JavaScript sem framework, gerados como arquivos estáticos. Para aplicações muito pequenas, HTML/CSS/JavaScript sem build também é válido; adote Vue, Svelte ou React somente quando complexidade de estado, componentes reutilizáveis ou padrão da equipe justificar. Configure o asset base como `/app/`.

O contrato selecionado usa a mesma origem e prefixo por aplicação: `/app/` serve a SPA e
`/app/api/<route>` encaminha ao FastAPI. Não há hostname nem listener separado para a API.

---

# 17. PostgreSQL

PostgreSQL 18 será o padrão inicial do boilerplate; a versão permanece configurável por instância no JSON.

Características:

- container independente;
- volume persistente;
- interfaces nas redes `webApp` e `shared`;
- autenticação própria do PostgreSQL; `shared` permite alcance de rede por NGINX, Gateway e demais containers conectados;
- credenciais fora do código-fonte;
- backup tratado como preocupação de infraestrutura.

Topologia recomendada:

```text
shared:  NGINX, Gateway, webApp, PostgreSQL
webApp:  webApp, PostgreSQL
```

Frontend JavaScript executado no browser não recebe credenciais PostgreSQL; FastAPI em `webApp:8000` possui essas credenciais. O processo FastAPI serve também os assets estáticos, então não há isolamento de processo entre frontend server e backend.


### Backup e recuperação (planejado; não implementado)

O plano primário usa pgBackRest, instalado em versão fixada na imagem PostgreSQL e executado dentro do container como conta de sistema `postgres`, com acesso local aos arquivos do banco e autenticação/roles PostgreSQL compatíveis. O operador e os timers ficam no host; uma entrada local, limitada e gerenciada invoca `podman exec`. Não exponha o socket/API rootful do Podman a um servidor ou coletor remoto.

Separe três responsabilidades de armazenamento: volume ativo `PGDATA`; volume gravável de repositório de trabalho pgBackRest, distinto de `PGDATA` e do volume de exportação; e volume de exportação concluída montado no host. PostgreSQL/operador escreve no repositório de trabalho e no mount de exportação concluída. Não use mount somente leitura nem fallback local. A configuração que expressaria esses caminhos ainda não é aceita pelo validador atual; não adicione campos de runtime nem alegue suporte implementado.

Schedules propostos: full mensal e incremental semanal, serializados para impedir concorrência e execução duplicada; se coincidirem, executa-se apenas o full. São pontos de recuperação semanais condicionados ao sucesso/publicação, não PITR. Inclua em cada exportação WAL e metadados necessários à consistência do backup selecionado; exportação contínua de WAL/PITR é opcional e exige decisão explícita.

O repositório pgBackRest é estado mutável com dependências entre backups, metadados e WAL. Não edite, pode, copie enquanto houver escritores ativos, ou renomeie subdiretórios. Antes da publicação, exija um snapshot de geração consistente por mecanismo suportado, excluindo escritores concorrentes e contendo o backup bem-sucedido, cadeia de pais, manifests/metadados e WAL de consistência necessário. A estratégia inicial proposta é exportar uma geração completa, não reconstruir seletivamente arquivos individuais. Isso simplifica a preservação de dependências, mas pode consumir alto armazenamento/tráfego e não promete transferências incrementais.

O volume do repositório de trabalho (inclusive staging de snapshot) é distinto do volume de exportações concluídas. Somente após sucesso do backup, copie a geração para um diretório transitório de publicação, oculto e separado, no filesystem de exportação concluída; esse staging de transferência não é o repositório de trabalho. Verifique a geração e a cópia; faça flush quando suportado e publique sob identidade única por rename atômico dentro do filesystem de destino ou marcador de conclusão escrito por último. Rename entre volumes não é atômico. Bytes incompletos podem existir temporariamente no staging oculto de destino, mas o namespace concluído nunca os expõe. Gerações publicadas são imutáveis, nunca sobrescritas/editadas; coletores aceitam exclusivamente gerações finais/marcadores válidos, nunca diretórios parciais nem estabilidade de tamanho. Falhas preservam publicações anteriores e a cadeia de origem; limpeza limita-se ao staging da execução. Não apague origem até acknowledgement externo e retenção que compreenda dependências.

Ausência/montagem incorreta, permissões insuficientes, timeout ou volume cheio causam falha, sem fallback. Defina coletor, caminho, credenciais de escopo mínimo, transporte/armazenamento cifrado, acknowledgement, retenção, locks e alertas. Dados e credenciais de banco são sensíveis; checksums não comprovam capacidade de restore. Restore é manual, privado e feito com pgBackRest compatível; valide cada geração por restore drill em destino descartável, incluindo recuperação da cadeia incremental. `pg_dumpall` pode continuar como exportação lógica opcional para portabilidade, não como mecanismo primário incremental/restauração. Nunca restaure automaticamente durante deployment.

---

# 18. Volumes

Volumes persistentes devem ser utilizados para:

- PostgreSQL;
- dados que precisem sobreviver à recriação do container;
- configurações persistentes, quando necessário.

Containers devem ser considerados descartáveis.

A criação inicial de volumes que exigir intervenção privilegiada no host pode ser realizada pelo administrador do RHEL.

O boilerplate deve documentar claramente quais volumes são obrigatórios.

---

# 19. Configuração e secrets

Não armazenar secrets diretamente no Git.

A configuração deve distinguir:

### Versionada

- nomes dos serviços;
- redes;
- portas;
- configuração estrutural;
- templates;
- deployment scripts;
- definição dos caminhos esperados para secrets no host.

### Externa

- senhas;
- tokens;
- chaves;
- certificados privados;
- credenciais de produção;
- arquivos `.env` contendo secrets.

## 19.1 Armazenamento dos secrets

A primeira implementação utilizará arquivos de secrets mantidos no host RHEL, fora do repositório Git.

A estrutura dos diretórios e os caminhos esperados deverão ser definidos pelo deployment.

Exemplo conceitual:

```text
/opt/boilerplate/
├── secrets/
│   ├── project-a/
│   │   ├── backend.env
│   │   └── postgres.env
│   └── project-b/
│       ├── backend.env
│       └── postgres.env
└── data/
```

A estrutura concreta poderá variar, mas deverá ser padronizada pelo boilerplate.

## 19.2 Mapeamento para containers

Cada secret deverá ser disponibilizado somente aos containers que efetivamente necessitem dele.

O acesso deverá ser somente leitura.

Exemplo conceitual:

```text
Host
└── secrets/project-a/backend.env
          │
          │ read-only
          ▼
      backend container
```

Um secret necessário apenas pelo PostgreSQL não deverá ser montado no frontend ou em outros containers.

## 19.3 Deployment de secrets

As ferramentas de deployment deverão:

1. criar os diretórios necessários no host;
2. validar sua existência e permissões;
3. documentar os arquivos esperados;
4. configurar os mapeamentos dos secrets;
5. montar os arquivos nos containers em modo somente leitura;
6. impedir que secrets sejam incorporados às imagens;
7. impedir que secrets sejam incluídos no Git.

O conteúdo dos secrets não deverá ser gerado automaticamente pelo Git ou armazenado no repositório.

## 19.4 Evolução futura

A arquitetura deverá permitir que o armazenamento local em arquivos seja posteriormente substituído por um Secret Manager ou integração corporativa.

Essa integração não faz parte do boilerplate inicial.

# 20. Deployment

O repositório deve conter scripts para:

1. validar pré-requisitos do host e todas as redes declaradas em `config/host_config.json`;
2. executar verificações e configurações específicas somente para os serviços declarados/ativados no arquivo;
3. criar a estrutura de diretórios, volumes e secrets sem sobrescrever dados existentes;
4. criar ou validar redes Podman e CIDRs;
5. construir/atualizar containers através de Quadlet;
6. conectar o Gateway compartilhado a todas as redes do inventário global `networks`, com uma interface por rede;
7. gerar DNSMasq com endereços atuais dos containers e endereços DNS do Gateway por rede;
8. descobrir rotas e endereços ativos dos túneis e instalar rotas simétricas sem NAT para acesso remoto;
9. configurar rotas HTTP do NGINX opcional, com host TCP/8080 para container TCP/80;
10. carregar chaves públicas SSH dos arquivos seguros no host;
11. iniciar serviços em ordem, verificar saúde e testar conexões remotas;
12. apresentar estado, logs, recursos alterados e instruções de recuperação;
13. agendar no host full mensal e incremental semanal por PostgreSQL; executar pgBackRest no container como `postgres`, publicar somente gerações completas verificadas em volume host separado e fornecer restore manual validado.

O preflight deve confirmar SELinux desativado sem alterar essa configuração. O egress dos containers usa o caminho padrão do Podman no host e pode usar masquerading.

O deployment deve ser idempotente sempre que possível.

Executar o deployment novamente não deve destruir dados persistentes ou secrets existentes.

O deployment deverá ser capaz de reproduzir a configuração estrutural do ambiente sem exigir acesso manual aos containers.

## 20.1 Bootstrap de acesso

A configuração inicial deverá poder incluir as chaves públicas SSH dos desenvolvedores autorizados.

O mecanismo de bootstrap deverá permitir distinguir:

- chaves para acesso aos containers de aplicação;
- chaves para acesso administrativo ao próprio Gateway.

As chaves privadas nunca deverão ser copiadas para o ambiente pelo deployment.

As chaves públicas serão lidas de arquivos fora do Git, com propriedade e permissões restritas no host. A auditoria do host registra alterações nos arquivos; PAM e logs de sessão dos operadores são controles externos e não fazem parte do deployment do boilerplate.

# 21. Manutenção

A manutenção normal deve ser possível sem acesso ao host RHEL.

Ferramentas principais:

- Cockpit;
- cockpit-podman;
- SSH;
- VS Code;
- logs dos containers;
- ferramentas de diagnóstico de rede.

Acesso direto ao host deve ficar reservado a:

- criação inicial de infraestrutura;
- problemas do Podman;
- problemas de armazenamento;
- alterações de capabilities;
- operações de infraestrutura;
- recuperação de falhas.

---

# 22. Diagnóstico

O Gateway deve incluir ferramentas suficientes para investigar rapidamente problemas de conectividade.

Ferramentas esperadas:

```text
ip
ss
tcpdump
conntrack
ping
traceroute / tracepath
dig / nslookup
curl
nc
```

A lista definitiva poderá variar conforme a distribuição e os requisitos.

O objetivo é permitir responder rapidamente:

- o container está ativo?
- a interface existe?
- a rota existe?
- o DNS resolve?
- a porta está ouvindo?
- o pacote chegou?
- a conexão foi encaminhada?
- o NAT ocorreu?
- o backend respondeu?

---

# 23. Observabilidade

O boilerplate deve permitir pelo menos:

- estado dos containers;
- logs;
- consumo básico de CPU/memória;
- estado das redes;
- estado do gateway.

Observabilidade avançada não faz parte da primeira versão.

Integrações futuras podem incluir:

- Prometheus;
- Grafana;
- Zabbix;
- OpenTelemetry;
- outros sistemas corporativos.

---

# 24. Estrutura lógica do repositório

A estrutura final deverá separar claramente:

```text
repository/
├── backend/
├── frontend/
├── gateway/
│   ├── development/
│   └── application/
├── database/
├── deploy/
│   └── quadlet/
├── config/
├── docs/
├── scripts/
```

A estrutura exata poderá ser ajustada durante a implementação, mas as responsabilidades devem permanecer separadas.

---

# 25. Regras para desenvolvimento no VS Code

O repositório deve ser adequado para desenvolvimento utilizando VS Code.

O ambiente deve favorecer:

- Git;
- desenvolvimento remoto;
- terminal integrado;
- debugging;
- testes;
- linting;
- formatação;
- execução dentro dos containers quando necessário.

O desenvolvedor não deve precisar reproduzir manualmente a infraestrutura de produção para realizar desenvolvimento normal.

---

# 26. Desenvolvimento versus produção

A arquitetura deve ser a mesma conceitualmente em ambos os ambientes.

Podem variar:

- recursos;
- secrets;
- número de réplicas;
- observabilidade;
- certificados;
- endpoints;
- políticas de backup.

Não devem variar:

- responsabilidades dos componentes;
- separação entre Development Gateway e proxy HTTP opcional;
- isolamento das redes;
- mecanismo geral de deployment;
- modelo de acesso aos containers.

---

# 27. Princípios de segurança

Mesmo com o controle de acesso externo, devem ser mantidos os seguintes princípios:

1. menor privilégio possível;
2. SELinux desativado por decisão explícita; o deployment não altera a política do host;
3. nenhum acesso desnecessário ao host;
4. Podman socket não exposto por TCP;
5. secrets fora do Git;
6. containers com filesystem mínimo;
7. evitar `--privileged`;
8. capabilities específicas quando possível;
9. redes app-specific sem roteamento entre si; a rede `shared` fornece conectividade direta intencional e exige autenticação nos serviços;
10. PostgreSQL não exposto externamente;
11. Gateway não utilizado para servir tráfego de usuários;
12. Proxy HTTP não utilizado como canal administrativo;
13. autenticação SSH individual, sem chaves privadas compartilhadas;
14. chaves privadas nunca persistidas nem registradas no Gateway; a chave privada de peer WireGuard
    será gerada dentro do Gateway, permanecerá transitoriamente em memória e será entregue uma única
    vez por canal autenticado ainda a desenhar;
15. secrets de aplicação fora do Git;
16. secrets montados somente onde necessários e em modo somente leitura;
17. imagens versionadas e atualizadas.

---

# 28. Decisões arquiteturais já estabelecidas

As seguintes decisões são consideradas parte do contrato:

| Decisão | Escolha |
|---|---|
| Alvo de qualificação do host | RHEL 9.8, Podman rootful 5.8.2, SELinux desativado |
| Runtime de containers | Podman 5.8.2 rootful |
| Imagens de containers | Distribuição Linux eficiente e mantida; preferir Debian ou Alpine |
| Ciclo de vida dos containers | Quadlet para containers persistentes |
| Podman mode | Rootful |
| Backend | Python + FastAPI |
| Frontend | Vite com JavaScript sem framework por padrão; HTML/JS estático para páginas pequenas |
| Rota frontend/API | `/app/` e `/app/api/<route>` no mesmo domínio |
| Database | PostgreSQL 18 por padrão, versão configurável por instância |
| Stack inicial da aplicação | `webApp` combina assets SPA e FastAPI em um listener TCP `8000`; PostgreSQL permanece separado |
| Gateway | Um único container compartilhado |
| Gateway por aplicação | Não |
| Cockpit | Dentro do Gateway |
| cockpit-podman | Dentro do Gateway |
| Proxy HTTP | NGINX compartilhado opcional; reverse proxy HTTP, distinto do Development Gateway |
| Configuração mínima | Host e Development Gateway; serviços de aplicação são opcionais |
| Porta HTTP no host | Bind selecionado `0.0.0.0:8080`, mapeado ao TCP 80 do NGINX; não presumir que o bind restringe o perímetro |
| Identidade HTTP | Perímetro autentica e injeta campos `X-USER`; aplicação autoriza; NGINX somente faz proxy |
| Autorização HTTP | Gate de deployment exige restrição efetiva ao perímetro confiável ou proveniência verificada; lista exata de campos e mecanismo permanecem pré-requisitos |
| TLS, DNS público e perímetro | Fornecidos externamente e assumidos por este host |
| Rede por aplicação | Sim |
| Gateway compartilhado entre redes | Sim; uma interface Podman para cada rede no inventário global `networks` |
| Acesso do Gateway | A todas as redes e serviços Podman, sem aprovação individual por serviço; componente administrativo confiável |
| Inventário de redes | `config/host_config.json` declara todas as redes; blocos opcionais configuram serviços do host |
| Redes iniciais | `shared` `192.168.9.0/24`; `webApp` `192.168.8.0/29`; cada app futuro recebe CIDR único |
| DNS de desenvolvimento | DNSMasq no Gateway |
| Configuração DNS | Gerada/atualizada pelo deployment |
| Nomes internos | DNSMasq resolve nomes para endereços atuais de containers; clientes usam rotas aos CIDRs Podman |
| Nomes externos | Namespace/endpoints externos separados |
| Acesso remoto | WireGuard server aditivo no Gateway, OpenVPN client externo e SSH TUN; split tunnel Layer 3 a todos CIDRs Podman; IPv4-only, sem NAT; origem e default route do cliente preservadas |
| Egress de containers | Saída normal do Podman rootful pelo host, com masquerading quando necessário |
| SSH | ProxyJump e múltiplas sessões SSH TUN (`ssh -w`) via Gateway |
| SSH para aplicações | ProxyJump encaminha somente TCP; TUN fornece rede IP roteada; autenticação ocorre no destino |
| SSH para gateway | Autenticação no próprio Gateway |
| Bind de gestão | SSH em `0.0.0.0` sob ACL do perímetro; Cockpit em `127.0.0.1` |
| SSH keys | Individuais por desenvolvedor |
| SSH shared keys | Não |
| SSH Certificate Authority | Fora do boilerplate inicial |
| WireGuard | Servidor IPv4-only aditivo no Gateway; peers aprovados alcançam todos CIDRs Podman; `dev.anatel` interno-only; chaves de peer geradas no Gateway e entregues uma vez por canal autenticado ainda a desenhar |
| OpenVPN | Servidor externo existente aloca endereços ao cliente OpenVPN do Gateway; `push_domains: ["anatel.gov.br"]` permanece separado; não será substituído por WireGuard |
| SSH TUN | Múltiplas sessões simultâneas usam pool próprio; runtime OpenSSH TUN é mantido |
| Firewall de usuários | Fora do gateway |
| Podman API | Preferencialmente Unix socket |
| Acesso diário ao host | Não |
| Deployment | Scripts versionados e Quadlet; preflight comum e verificações específicas por serviço |
| SSH key bootstrap | Chaves públicas de arquivos root-owned; host audit registra alterações; PAM externo |
| Backup PostgreSQL | pgBackRest versionado na imagem; full mensal/incremental semanal por timers host; repositório de trabalho e exportações concluídas em volumes distintos; publicação de geração completa verificada; restore manual com drill; plano, não implementado |
| TUS e file sharing | Serviços opcionais; limite de arquivo de 1 GB por padrão; file sharing NGINX somente leitura |
| Serviços não HTTP para usuários | Publicação direta por bind de host, protocolo e portas explicitamente declarados; autenticação do serviço e perímetro próprios |
| Acesso developer aos containers | Gateway alcança todos os serviços/portas configurados sem publicar portas de serviço; listener UDP WireGuard é publicado separadamente |
| NGINX rate limit | Desativado por padrão |
| Limite de body NGINX | 1 GB por padrão; configurável |
| Configuração | `schema_version: 1` obrigatória; seções de recursos opcionais e retrocompatíveis |
| Application secrets | Fora do Git |
| Secret storage inicial | Arquivos no host |
| Secret mapping | Somente leitura e apenas para containers necessários |
| Secret Manager | Integração futura, fora do boilerplate inicial |
| Bootstrap offline | Gateway base valida e inicia sem containers de aplicação, perfil OpenVPN, sessão SSH TUN ou segredo WireGuard; runtime checks são exigidos antes da ativação de cada transporte |

# 29. Inputs e gates de implementação

As decisões de topologia confirmadas estão registradas na seção 34. Os valores operacionais e testes abaixo permanecem como inputs de deployment:

1. Validar endereços estáticos do Gateway nas redes Podman e detectar conflitos com pools e rotas relevantes do host, LAN/corporativo e túneis.
2. Provisionar o perfil OpenVPN privado, os endereços client pool alocados pelo servidor e rotas externas que direcionam CIDRs Podman via Gateway VPN client. O deployment não instala nem configura o servidor OpenVPN externo.
3. Fornecer o pool SSH TUN real, a conta restrita e a política `PermitTunnel`; implementar alocação única por sessão, detecção de colisão e cleanup isolado.
4. Validar a rota determinística de retorno pelo host e determinar por teste se policy tables explícitas são necessárias. Revalidar mudanças de rotas pushed ao reconectar OpenVPN.
5. Validar capabilities, rotas, reinício, DNS e egress no host descartável autorizado RHEL 9.8 / Podman 5.8.2.
6. Definir operadores autorizados de produção, UIDs/GIDs e identidades de processo; validar os três locais de PostgreSQL (`PGDATA`, repositório pgBackRest de trabalho e mount de exportação concluída), capacidade/permissões, snapshot consistente, staging de publicação e restore drill.
7. Definir a lista permitida dos campos de identidade `X-USER` e o mecanismo verificável de proveniência perímetro-aplicação antes de expor rotas protegidas. Não escolher nomes de campos adicionais ou tratar CIDR/header bruto como autenticação.
8. Definir a versão Node.js suportada, o storage e a conta do TUS. O limite de arquivo padrão é 1 GB e é configurável.
9. Substituir exemplos legados `.dev.internal` por `dev.anatel`, definir registros internos e implementar/validar split DNS em Windows 11, Linux e macOS. O gerador DNS atual não impõe sufixo fixo; `dns_records` está vazio.
10. Definir pool/endereço IPv4 do servidor WireGuard, endpoint e porta UDP publicados, resolver, operadores autorizados e procedimento auditável de aprovação/rotação/revogação.
11. Projetar canal autenticado de entrega única das chaves privadas de peer geradas no Gateway. Definir identidade e auditoria do operador, formato da entrega, tratamento do plaintext transitório em memória e recuperação sem persistir a chave.
12. Decidir separadamente quando converter a receita Debian do File Gateway em uma implantação containerizada.

SELinux desativado é uma decisão de segurança explícita. O deployment valida o estado, mas não altera a política do host.

# 30. Critérios de aceitação arquitetural

Uma implementação do boilerplate será considerada aderente quando:

- uma aplicação puder ser implantada sem alterar manualmente o host na operação normal;
- cada aplicação possuir rede Podman independente;
- containers de aplicação e PostgreSQL também poderem compartilhar `shared`; essa conectividade direta é intencional e protegida por autenticação de serviço, não por roteamento;
- o inventário completo de redes e as opções de serviço estiverem declarados em `config/host_config.json`;
- o Gateway puder acessar múltiplas redes;
- o Gateway compartilhado possuir uma interface em cada rede configurada;
- o Gateway alcançar serviços em todas as redes sem transformá-las em uma única rede;
- uma nova aplicação puder ser adicionada sem criar outro gateway;
- desenvolvedores puderem acessar containers por SSH/VS Code através do gateway;
- o gateway realizar forwarding sem substituir a autenticação SSH do container de aplicação;
- rotas NGINX forem opcionais e declaradas no JSON, com o bind selecionado `0.0.0.0:8080` mapeado ao container TCP/80;
- NGINX encaminhar, para a aplicação inicial, `/app/` e `/app/api/<route>` ao mesmo listener FastAPI `webApp:8000`, preservando o prefixo, sem restringir outras aplicações aos mesmos upstreams/portas;
- FastAPI servir, na aplicação inicial, a SPA em `/app/` e a API em `/app/api/` no único listener TCP `8000`;
- o perímetro autenticar usuários e fornecer identidade `X-USER` confiável, e a aplicação autorizar usuários sem atribuir autenticação ao NGINX;
- rotas protegidas falharem fechadas quando a identidade estiver ausente/não confiável e deployment aplicar o gate de perímetro/proveniência;
- serviços não HTTP de usuário usarem publicação direta explicitamente configurada, sem confundir isso com o acesso de desenvolvimento via Gateway;
- WireGuard server aditivo, OpenVPN client e múltiplos clientes SSH TUN simultâneos permitirem tráfego Layer 3 IPv4 split-tunnel para todos os CIDRs Podman, incluindo PostgreSQL, sem NAT, preservando a origem e as rotas default dos clientes;
- peers WireGuard usarem split DNS para `dev.anatel` em Windows 11, Linux e macOS, sem alterar o resolver global, sem registros AAAA e sem tornar o domínio público;
- onboarding de peer exigir aprovação e auditoria; chaves privadas de peer serem geradas dentro do Gateway, entregues uma vez por canal autenticado e nunca persistidas/logadas;
- pools e endpoints de túnel não se sobreporem a CIDRs Podman nem rotas relevantes de host/LAN/corporativas; alocações SSH por sessão serem únicas, com cleanup isolado;
- rotas externas direcionarem CIDRs Podman ao cliente OpenVPN do Gateway e o Gateway alcançar aplicações por interfaces Podman conectadas, com rotas de retorno determinísticas ao túnel proprietário;
- reconnect OpenVPN revalidar rotas pushed, candidato inválido não mutar estado e rotas/regras terem ownership, reconciliação idempotente e rollback definidos;
- não haver forwarding entre redes de aplicação, DHCP, bridging Ethernet, TAP, deployment do servidor OpenVPN externo, nem watcher genérico;
- egress de containers alcançar destinos externos pela saída normal do Podman no host, usando masquerading quando necessário;
- deployment usar Quadlet e passar aceitação em RHEL 9.8 / Podman rootful 5.8.2 com SELinux desativado;
- chaves públicas individuais puderem ser provisionadas pelo bootstrap do deployment;
- chaves públicas forem lidas de arquivos root-owned no host e alterações forem registradas pela auditoria existente; PAM permanece responsabilidade externa;
- o próprio gateway possuir autenticação SSH independente;
- Cockpit permitir administrar os containers;
- Podman API não estiver exposto desnecessariamente;
- PostgreSQL possuir armazenamento persistente;
- PostgreSQL 18 possuir armazenamento persistente e plano de backup pgBackRest com full mensal/incremental semanal, volumes de trabalho/exportação distintos, publicação íntegra e restore manual testado; esses campos e operações ainda não são suportados pelo runtime;
- somente o processo FastAPI possuir credenciais PostgreSQL dentro do container combinado `webApp`;
- TUS e file sharing NGINX serem recursos opcionais; uploads terem limite configurável de 1 GB por padrão e file sharing ser somente leitura;
- seções opcionais do JSON permanecerem compatíveis com `schema_version: 1`;
- NGINX funcionar como proxy HTTP opcional, não como gateway geral de aplicações;
- o acesso externo continuar controlado pela infraestrutura de segurança existente;
- deployment puder ser repetido sem destruir dados;
- diagnóstico básico de rede puder ser realizado sem acesso ao host RHEL;
- o deployment validar que SELinux já está desativado sem alterar essa configuração.
- configuração estrutural estiver versionada;
- secrets não estiverem no Git.

---

# 31. Regra de evolução

O boilerplate deve permanecer deliberadamente simples.

Antes de adicionar um novo componente, deve-se perguntar:

1. Ele resolve uma necessidade real?
2. Pode ser fornecido por um componente existente?
3. A função pode ser realizada por configuração em vez de software?
4. A nova dependência aumenta significativamente a superfície de ataque?
5. Ela adiciona um processo permanente?
6. Ela exige armazenamento persistente?
7. Ela exige acesso privilegiado ao host?
8. Ela dificulta o deployment?
9. Ela dificulta o diagnóstico?
10. Ela precisa realmente fazer parte do boilerplate?

A preferência deve ser sempre:

```text
configuração
    >
componente existente
    >
script simples
    >
novo serviço
    >
software customizado
```

---

# 32. Visão final

A arquitetura lógica desejada é:

```text
External security perimeter provides TLS, DNS, VPN, firewall, and ACL
                      │
           ┌──────────┴──────────┐
           │                     │
           ▼                     ▼
Development access          User HTTP access
           │                     │
           ▼                     ▼
       Development Gateway     NGINX :8080 -> :80
           │                     │
           └─────────┬───────────┘
                     │
shared 192.168.9.0/24: Gateway, NGINX, webApp, PostgreSQL
                     │
webApp 192.168.8.0/29: webApp, PostgreSQL
```

The `webApp` container runs frontend and FastAPI. PostgreSQL is separate. All four services join `shared`, so they have direct network reach to each other. Future app networks use unique, non-overlapping CIDRs and attach their app services to the existing Gateway.

A característica central continua sendo um Gateway compartilhado. As redes app-specific não roteiam entre si, mas os containers ligados a `shared` têm conectividade direta e dependem de autenticação por serviço.

Isso proporciona um único ponto de manutenção para os desenvolvedores sem transformar as aplicações em uma única rede ou exigir um gateway dedicado por aplicação.

---

# 33. Próxima etapa

Use os planos de implementação abaixo para decompor o contrato sem misturar acesso administrativo, tráfego de usuários e ciclo de vida das aplicações:

1. [HTTP Proxy](../plans/http-proxy-plan.md): reverse proxy HTTP opcional, roteamento, pressupostos de TLS/perímetro e requisitos de identidade.
2. [Application stack](../plans/application-stack-plan.md): frontend, backend FastAPI e PostgreSQL.
3. [Application deployment and operations](../plans/application-deployment-plan.md): configuração declarativa, secrets, volumes, atualização, recuperação e handoff de DNS.

Resolva os inputs restantes da seção 29 antes da implementação. Valide Podman, Quadlet, roteamento, DNS, egress e SELinux desativado no host descartável autorizado RHEL 9.8 com Podman rootful 5.8.2. Testes locais de containers não substituem a aceitação do host.

# 34. Topologia selecionada e inputs operacionais

`config/host_config.json` declara a topologia selecionada:

| Rede Podman | CIDR | IP do Gateway | Membros declarados |
|---|---|---|---|
| `shared` | `192.168.9.0/24` | `192.168.9.2` | Gateway, NGINX, `webApp` e `postgres` |
| `webApp` | `192.168.8.0/29` | `192.168.8.2` | `webApp` e `postgres` |

O Gateway está conectado a todas as redes declaradas. `webApp` é um único container que reúne frontend e FastAPI; PostgreSQL permanece separado. Ambos possuem interfaces em `shared` e `webApp`. NGINX e Gateway usam `shared`. O solicitante aceita a conectividade direta entre membros de `shared` e confia na autenticação/autorização de cada serviço. Não há roteamento entre redes específicas de aplicações, mas isso não isola serviços que compartilham `shared`. Os IPs estáticos `192.168.9.2` e `192.168.8.2` foram aprovados para as duas interfaces do Gateway.

`shared` é uma bridge Podman compartilhada, não uma interface física/do host nem uma rota ou pool VPN. `gateway.remote_access` permanece uma área separada para configuração de túneis planejada; rotas externas e pools de endereços não são redes Podman e não entram em `networks`. O servidor WireGuard e seu schema/runtime ainda não existem. As decisões de topologia estão confirmadas; pools, endpoint, porta, resolver, OS do cliente e regras de roteamento são inputs de deployment.

`192.168.9.0/24` foi selecionado como a primeira rede /24 acima do conflito conhecido, usando o inventário versionado `shared`/`webApp` e a rota host `192.168.7.0/24` observada em `eth0`. Essa escolha não prova disponibilidade contra outras redes ou rotas. Gateway `--check` valida redes Podman, mas não verifica a tabela de rotas do host; a aceitação exige revisão no host-alvo de todas as redes e rotas relevantes.

`192.168.8.0/29` fica reservado à rede `webApp`. Ele fornece seis endereços utilizáveis; quatro ficam reservados ao bridge, Gateway, `webApp` e PostgreSQL. Cada aplicação futura deverá receber um CIDR exclusivo e não sobreposto. O deploy da aplicação cria sua rede, atualiza somente o inventário top-level `networks` e reconcilia o Gateway existente. Não deve criar outro Gateway nem manter um inventário seletivo de redes no bloco `gateway`.

O solicitante aprovou estender `schema_version: 1` para rotas NGINX e endereços estáticos do Gateway. O validador aceita `gateway_address` e a seção `http_proxy`; o deployment de NGINX ainda não foi implementado. Essa declaração representa configuração desejada, não autenticação ou sucesso de runtime.

Inputs operacionais e gates de implementação restantes:

1. Validar no host-alvo a atribuição Quadlet dos IPs aprovados `192.168.9.2` e `192.168.8.2`.
2. NGINX usa `0.0.0.0:8080`, mapeado ao TCP `80` do container. A rede externa encaminha tráfego para o IP DHCP atual do host.
3. `/app` e `/app/api/` apontam ao mesmo `webApp:8000`; FastAPI serve os assets Vite e a API.
4. Decisão confirmada: FastAPI serve assets e API no mesmo processo `webApp:8000` e mantém credenciais PostgreSQL. Browser assets não são processos do container; teste que build output e respostas HTTP nunca exponham essas credenciais.
5. Implementar deployment NGINX e atualização idempotente do Gateway quando novas redes forem adicionadas.
6. Verificar pools/endpoints de túnel e CIDRs Podman contra redes/rotas do host, LAN de desenvolvedores e ambiente corporativo antes de deployment. Preservar rotas default e conectadas necessárias.
7. SSH do Gateway usa bind `0.0.0.0` para forwarding externo sob controle do perímetro; Cockpit permanece em `127.0.0.1`.
8. Confirmar em teste o próximo salto determinístico para retorno dos containers; não instalar rotas conflitantes de um mesmo prefixo por todas as redes Podman.
