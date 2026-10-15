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
       Gateway            Application Gateway
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

Esse plano é independente do Gateway.

---

# 4. Containers principais

O boilerplate define quatro categorias lógicas de containers.

## 4.1 Gateway

Container compartilhado entre todas as aplicações.

Responsabilidades:

- SSH;
- DNS;
- routing;
- OpenVPN client e SSH TUN;
- forwarding roteado entre túneis ativos e todas as redes Podman configuradas;
- acesso às redes de desenvolvimento das aplicações;
- ferramentas de diagnóstico;
- Cockpit;
- cockpit-podman.

O acesso remoto de desenvolvedores preserva o IP de origem e não usa NAT. O egress iniciado por containers usa a saída normal do Podman rootful no host e pode usar masquerading.

O Gateway é uma **unidade administrativa única**.

Não deve ser criado um gateway independente por aplicação salvo necessidade arquitetural futura claramente justificada.

---

## 4.2 Application Gateway

Container independente do Gateway.

Responsabilidade:

- receber conexões HTTP/HTTPS;
- encaminhar requests para as aplicações;
- receber tráfego HTTP encaminhado pelo perímetro externo, que fornece TLS, certificados e DNS público;
- eventualmente realizar virtual hosting;
- eventualmente aplicar políticas de acesso específicas da aplicação.

NGINX é o único provedor HTTP previsto. Instale-o somente quando `application_gateway` estiver habilitado.

A escolha concreta deve ser definida separadamente da arquitetura do Gateway.

O Application Gateway **não deve ser utilizado como canal de manutenção dos containers**.

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
- OpenVPN e SSH TUN.

Entretanto, o container não deve receber acesso indiscriminado ao host RHEL.

Particularmente, deve-se evitar, sem justificativa:

- montagem do filesystem completo do host;
- acesso irrestrito a `/proc` do host;
- acesso irrestrito a `/sys` do host;
- execução `--privileged` quando capacidades específicas forem suficientes;
- exposição remota do Podman socket.

A configuração final de capabilities será definida durante a implementação e validada em RHEL 9.8 com Podman rootful 5.8.2 e SELinux desativado. O deployment não altera a configuração de segurança do host.

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

Cada aplicação deve possuir uma rede Podman própria com CIDR exclusivo.

Exemplo:

```text
project-a-net
project-b-net
project-c-net
```

As redes app-specific não roteiam entre si. A topologia inicial também conecta todos os containers de aplicação e PostgreSQL à rede `shared`; essa rede fornece conectividade direta e exige autenticação/autorização em cada serviço.

---

## 8.2 Gateway compartilhado

O Gateway compartilhado possui uma interface Podman para cada rede no inventário global `networks` de `config/host_config.json`, incluindo `shared`. Ele não mantém uma lista seletiva de redes por serviço:

```text
                 Gateway
                  /        |        \
                 /         |         \
        project-a-net project-b-net project-c-net
```

O Gateway administra todas as redes declaradas sem rotear entre redes app-specific. A rede `shared` é uma exceção explícita: seus membros podem comunicar-se diretamente na mesma rede.

O JSON declara o endereço da interface do Gateway em cada rede. Esse endereço atende DNSMasq para os containers conectados à rede.

A configuração solicitada declara `shared` e `webApp` em `gateway.networks`, mantendo o Gateway conectado a todas as redes do inventário. Aplicações futuras devem adicionar cada rede nova à configuração do Gateway existente.

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
backend.project-a.dev.internal
frontend.project-a.dev.internal
backend.project-b.dev.internal
```

A configuração deverá ser regenerável sem intervenção manual dentro do container do gateway.

Containers e clientes remotos consultam DNSMasq no endereço do Gateway correspondente à sua rede ou túnel. DNSMasq resolve nomes declarados para os endereços atuais dos containers. Clientes remotos precisam de rotas até os CIDRs Podman; o acesso não usa NAT nem portas traduzidas. Consultas de domínios não declarados seguem para os resolvers upstream configurados no host.

## 9.3 Nomes internos e externos

A arquitetura deverá distinguir explicitamente:

### Nomes internos de desenvolvimento

Utilizados pelos desenvolvedores e pelas ferramentas de manutenção.

Exemplos:

```text
backend.project-a.dev.internal
frontend.project-a.dev.internal
dev-gateway.dev.internal
```

Esses nomes apontam para endereços atuais das redes Podman. Clientes remotos consultam DNSMasq por OpenVPN ou SSH TUN e precisam de rotas para os CIDRs correspondentes. ProxyJump sozinho não transporta consultas DNS.

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
backend.project-a.dev.internal
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

O mecanismo de deployment deve validar os CIDRs declarados no JSON contra as redes externas disponíveis. Rotas e endereços de clientes são descobertos nas sessões ativas de OpenVPN e SSH TUN; compare-os com os CIDRs Podman antes de instalar rotas e falhe em caso de sobreposição.

O pool de endereços do SSH TUN é declarado no JSON. O perfil OpenVPN permanece externo, privado e exclusivo do Gateway.

Endereços IP individuais de containers não devem ser tratados como identificadores permanentes.

---



---

# 11. Acesso SSH e VS Code

O Gateway será o ponto de entrada para acesso SSH aos containers. ProxyJump encaminha conexões SSH TCP ao destino, onde ocorre a autenticação. SSH TUN (`ssh -w`) fornece conectividade IP roteada e também permite consultas DNS do cliente ao Gateway.

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

O gateway deverá, portanto, encaminhar a conexão sem substituir a autenticação SSH do destino.

ProxyJump é um caminho TCP para SSH; não substitui o túnel IP SSH TUN. Os dois caminhos são suportados.

## 11.2 Acesso ao próprio Gateway

O próprio container do Gateway constitui uma exceção.

Quando o objetivo for administrar o gateway em si, a conexão será terminada no próprio container e sua autenticação SSH será realizada por ele.

O gateway deverá possuir sua própria identidade/nome DNS de administração, distinta dos nomes dos containers das aplicações.

Exemplo conceitual:

```text
dev-gateway.dev.internal
backend.project-a.dev.internal
frontend.project-a.dev.internal
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

# 12. Acesso via VPN

O Gateway suporta um cliente OpenVPN opcional e SSH TUN. Os dois transportes podem operar simultaneamente. O perfil `.ovpn` é privado, externo ao Git e exclusivo do Gateway; rotas fornecidas pelo servidor são descobertas em runtime. O servidor VPN e suas rotas permanecem responsabilidade externa.


---

# 13. Roteamento, egress e forwarding

O acesso remoto de desenvolvedores usa roteamento IP entre OpenVPN ou SSH TUN e todas as redes Podman declaradas no JSON. Ele permite qualquer protocolo e porta, preserva o IP de origem e não usa DNAT nem SNAT. Não existe uma segunda aprovação de rede por serviço; a autenticação e autorização pertencem a cada container ou serviço.

Rotas e endereços de clientes são descobertos nas sessões ativas. Antes de instalar estado, o deployment compara-os com os CIDRs Podman declarados e falha se encontrar sobreposição. O host e o Gateway devem fornecer rotas de retorno simétricas. As rotas externas do servidor VPN são pré-requisito e não são configuradas por este projeto.

Containers podem iniciar conexões para qualquer destino externo alcançável pela rota padrão do host. O egress usa o caminho normal do Podman rootful e pode usar masquerading; serviços externos verão o endereço de saída do host. Esse comportamento é separado do acesso remoto de desenvolvedores, que preserva o IP de origem.

O Gateway não encaminha tráfego entre redes de aplicações. Sua interface em cada rede permite alcançar todos os serviços, inclusive PostgreSQL; cada serviço deve controlar sua própria autenticação e autorização.

---

# 14. Application Gateway

O Application Gateway possui função distinta do Gateway.

Exemplo:

```text
Internet / Corporate users
          │
          ▼
Application Gateway
          │
          ├── Application A
          ├── Application B
          └── Application C
```

Pode utilizar:

- HTTP;
- HTTPS;
- TLS termination;
- virtual hosts;
- reverse proxy.

O acesso administrativo não deve depender do Application Gateway.

Use NGINX como único provedor HTTP, somente quando `application_gateway` estiver habilitado. O container escuta TCP 80; o endereço de bind e a porta publicada no host ficam no JSON, com a porta padrão 8080. O perímetro externo fornece DNS público, certificados, TLS termination e encaminha HTTP ao host. Por aplicação, `/app` serve o frontend e `/app/api/<route>` encaminha ao FastAPI com o prefixo preservado. A rota da API deve ser avaliada antes do fallback SPA. Não configure rate limiting por padrão. Limite uploads a 1 GB por padrão; configure esse limite no NGINX e no serviço TUS. O file sharing básico do NGINX é opcional e somente leitura por padrão.

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
- autenticação/autorização da aplicação, quando aplicável.

O backend não deve assumir responsabilidades de infraestrutura do gateway.

---

# 16. Frontend

O frontend será composto por componentes JavaScript.

O boilerplate deve permitir evolução futura do framework sem alterar a arquitetura de infraestrutura.

O frontend deve ser servido por:

- Nginx;
- servidor estático apropriado;
- ou mecanismo equivalente.

Os assets Vite residem no container `webApp` e FastAPI os serve em `/app`; FastAPI também serve `/app/api/*` no listener interno TCP `8000`. NGINX faz proxy de ambas as rotas para esse listener. Não há processo frontend separado no modo selecionado.

Use Vite com módulos JavaScript sem framework, gerados como arquivos estáticos. Para aplicações muito pequenas, HTML/CSS/JavaScript sem build também é válido; adote Vue, Svelte ou React somente quando complexidade de estado, componentes reutilizáveis ou padrão da equipe justificar. Configure o asset base como `/app/`.

O padrão de API recomendado é mesma origem e prefixo por aplicação: `/app` serve o frontend e `/app/api/<route>` encaminha ao FastAPI. Um hostname separado para a API permanece uma alternativa futura para consumidores independentes, mas exige CORS, DNS e TLS adicionais.

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


O backup obrigatório executa `pg_dumpall` sem filtros para salvar dados, estrutura de todos os bancos e objetos globais do cluster. O schedule mensal padrão e os caminhos do mount host/container são configurados por instância no JSON; um timer systemd é gerado a partir do schedule. O armazenamento remoto é montado no host e compartilhado somente para leitura com PostgreSQL. O job registra erro e falha se o mount não estiver disponível; não usa fallback local. Restore é uma ação manual do operador, inicialmente por script: conexão direta e privada ao PostgreSQL, seguida da execução do SQL completo via `psql`. Não exponha PostgreSQL pelo Application Gateway nem restaure automaticamente durante deployment.

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
13. gerar, para cada PostgreSQL configurado, um timer systemd mensal por padrão e uma execução `pg_dumpall` completa no mount remoto declarado.

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
- separação entre gateway de desenvolvimento e gateway de aplicação;
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
12. Application Gateway não utilizado como canal administrativo;
13. autenticação SSH individual, sem chaves privadas compartilhadas;
14. chaves privadas nunca armazenadas no gateway;
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
| Rota frontend/API | `/app` e `/app/api/<route>` no mesmo domínio |
| Database | PostgreSQL 18 por padrão, versão configurável por instância |
| Container de aplicação | `webApp` combina frontend e FastAPI; PostgreSQL permanece separado |
| Gateway | Um único container compartilhado |
| Gateway por aplicação | Não |
| Cockpit | Dentro do Gateway |
| cockpit-podman | Dentro do Gateway |
| Application Gateway | Nginx compartilhado separado do Development Gateway |
| Configuração mínima | Host e Development Gateway; serviços de aplicação são opcionais |
| Porta HTTP no host | TCP 8080 por padrão, mapeada ao TCP 80 do NGINX; endereço e porta definidos no JSON |
| TLS, DNS público e perímetro | Fornecidos externamente e assumidos por este host |
| Rede por aplicação | Sim |
| Gateway compartilhado entre redes | Sim; uma interface Podman para cada rede no inventário global `networks` |
| Acesso do Gateway | A todas as redes e serviços Podman, sem aprovação individual por serviço; componente administrativo confiável |
| Inventário de redes | `config/host_config.json` declara todas as redes; blocos opcionais configuram serviços do host |
| Redes iniciais | `shared` `192.168.7.0/24`; `webApp` `192.168.8.0/29`; cada app futuro recebe CIDR único |
| DNS de desenvolvimento | DNSMasq no Gateway |
| Configuração DNS | Gerada/atualizada pelo deployment |
| Nomes internos | DNSMasq resolve nomes para endereços atuais de containers; clientes usam rotas aos CIDRs Podman |
| Nomes externos | Namespace/endpoints externos separados |
| Acesso remoto | OpenVPN ou SSH TUN com roteamento IP a todas as redes; sem NAT; origem preservada |
| Egress de containers | Saída normal do Podman rootful pelo host, com masquerading quando necessário |
| SSH | ProxyJump e SSH TUN (`ssh -w`) via Gateway |
| SSH para aplicações | ProxyJump encaminha TCP; TUN fornece rede IP; autenticação ocorre no destino |
| SSH para gateway | Autenticação no próprio Gateway |
| Bind de gestão | SSH em `0.0.0.0` sob ACL do perímetro; Cockpit em `127.0.0.1` |
| SSH keys | Individuais por desenvolvedor |
| SSH shared keys | Não |
| SSH Certificate Authority | Fora do boilerplate inicial |
| VPN | Cliente OpenVPN opcional e SSH TUN; ambos podem operar simultaneamente |
| Firewall de usuários | Fora do gateway |
| Podman API | Preferencialmente Unix socket |
| Acesso diário ao host | Não |
| Deployment | Scripts versionados e Quadlet; preflight comum e verificações específicas por serviço |
| SSH key bootstrap | Chaves públicas de arquivos root-owned; host audit registra alterações; PAM externo |
| Backup PostgreSQL | `pg_dumpall` integral; schedule mensal padrão; mount host/ container no JSON; restore manual por script; retenção pelo storage |
| TUS e file sharing | Serviços opcionais; limite de arquivo de 1 GB por padrão; file sharing NGINX somente leitura |
| NGINX rate limit | Desativado por padrão |
| Limite de body NGINX | 1 GB por padrão; configurável |
| Configuração | `schema_version: 1` obrigatória; seções de recursos opcionais e retrocompatíveis |
| Application secrets | Fora do Git |
| Secret storage inicial | Arquivos no host |
| Secret mapping | Somente leitura e apenas para containers necessários |
| Secret Manager | Integração futura, fora do boilerplate inicial |

# 29. Inputs e gates de implementação

As decisões de topologia confirmadas estão registradas na seção 34. Os valores operacionais e testes abaixo permanecem como inputs de deployment:

1. Definir endereços estáticos do Gateway em cada rede e validar conflitos com CIDRs externos descobertos nas sessões VPN.
2. Provisionar o perfil OpenVPN privado e as rotas externas. O deployment não configura o servidor VPN; falha se as sessões não expuserem dados suficientes para rotas simétricas.
3. Definir o pool de endereços SSH TUN, a conta dedicada e a política restrita de `PermitTunnel`.
4. Validar capabilities, rotas, reinício, DNS e egress no host descartável autorizado RHEL 9.8 / Podman 5.8.2.
5. Definir operadores autorizados de produção, UIDs/GIDs, identidades de processo no container `webApp`, paths de dados e mount host/container para backup.
6. Definir host bind address do NGINX, método de servir os assets e ports frontend/API do container `webApp`.
7. Definir a versão Node.js suportada, o storage e a conta do TUS. O limite de arquivo padrão é 1 GB e é configurável.
8. Definir os nomes DNS internos e validar o handoff de atualização DNS entre deployment da aplicação e Development Gateway.
9. Decidir separadamente quando converter a receita Debian do File Gateway em uma implantação containerizada.

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
- endpoints NGINX forem opcionais e declarados no JSON, com host TCP/8080 mapeado ao container TCP/80;
- NGINX servir `/app` e encaminhar `/app/api/<route>` ao FastAPI preservando o prefixo;
- frontend e FastAPI executarem no container `webApp`, com portas upstream configuradas separadamente;
- OpenVPN e SSH TUN permitirem tráfego IP remoto sem NAT, preservando a origem e com rotas de retorno simétricas;
- egress de containers alcançar destinos externos pela saída normal do Podman no host, usando masquerading quando necessário;
- deployment usar Quadlet e passar aceitação em RHEL 9.8 / Podman rootful 5.8.2 com SELinux desativado;
- chaves públicas individuais puderem ser provisionadas pelo bootstrap do deployment;
- chaves públicas forem lidas de arquivos root-owned no host e alterações forem registradas pela auditoria existente; PAM permanece responsabilidade externa;
- o próprio gateway possuir autenticação SSH independente;
- Cockpit permitir administrar os containers;
- Podman API não estiver exposto desnecessariamente;
- PostgreSQL possuir armazenamento persistente;
- PostgreSQL 18 possuir armazenamento persistente e backup `pg_dumpall` mensal por padrão, com schedule e mount remoto definidos no JSON e restore manual por script via `psql`;
- somente o processo FastAPI possuir credenciais PostgreSQL dentro do container combinado `webApp`;
- TUS e file sharing NGINX serem recursos opcionais; uploads terem limite configurável de 1 GB por padrão e file sharing ser somente leitura;
- seções opcionais do JSON permanecerem compatíveis com `schema_version: 1`;
- Application Gateway estiver separado do Gateway;
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
shared 192.168.7.0/24: Gateway, NGINX, webApp, PostgreSQL
                     │
webApp 192.168.8.0/29: webApp, PostgreSQL
```

The `webApp` container runs frontend and FastAPI. PostgreSQL is separate. All four services join `shared`, so they have direct network reach to each other. Future app networks use unique, non-overlapping CIDRs and attach their app services to the existing Gateway.

A característica central continua sendo um Gateway compartilhado. As redes app-specific não roteiam entre si, mas os containers ligados a `shared` têm conectividade direta e dependem de autenticação por serviço.

Isso proporciona um único ponto de manutenção para os desenvolvedores sem transformar as aplicações em uma única rede ou exigir um gateway dedicado por aplicação.

---

# 33. Próxima etapa

Use os planos de implementação abaixo para decompor o contrato sem misturar acesso administrativo, tráfego de usuários e ciclo de vida das aplicações:

1. [Application Gateway](application-gateway-plan.md): entrada HTTP/HTTPS, roteamento, TLS e isolamento de rede.
2. [Application stack](application-stack-plan.md): frontend, backend FastAPI e PostgreSQL.
3. [Application deployment and operations](application-deployment-plan.md): configuração declarativa, secrets, volumes, atualização, recuperação e handoff de DNS.

Resolva os inputs restantes da seção 29 antes da implementação. Valide Podman, Quadlet, roteamento, DNS, egress e SELinux desativado no host descartável autorizado RHEL 9.8 com Podman rootful 5.8.2. Testes locais de containers não substituem a aceitação do host.

# 34. Topologia selecionada e inputs pendentes

`config/host_config.json` declara a topologia selecionada:

| Rede Podman | CIDR | IP do Gateway | Membros declarados |
|---|---|---|---|
| `shared` | `192.168.7.0/24` | `192.168.7.2` | Gateway, NGINX, `webApp` e `postgres` |
| `webApp` | `192.168.8.0/29` | `192.168.8.2` | `webApp` e `postgres` |

O Gateway está conectado a todas as redes declaradas. `webApp` é um único container que reúne frontend e FastAPI; PostgreSQL permanece separado. Ambos possuem interfaces em `shared` e `webApp`. NGINX e Gateway usam `shared`. O solicitante aceita a conectividade direta entre membros de `shared` e confia na autenticação/autorização de cada serviço. Não há roteamento entre redes específicas de aplicações, mas isso não isola serviços que compartilham `shared`. Os IPs estáticos `.2` foram aprovados para as duas interfaces do Gateway.

`192.168.8.0/29` fica reservado à rede `webApp`. Ele fornece seis endereços utilizáveis; quatro ficam reservados ao bridge, Gateway, `webApp` e PostgreSQL. Cada aplicação futura deverá receber um CIDR exclusivo e não sobreposto. O deploy da aplicação cria sua rede, atualiza o inventário e `gateway.networks`, e reconcilia o Gateway existente. Não deve criar outro Gateway.

O solicitante aprovou estender `schema_version: 1` para rotas NGINX e endereços estáticos do Gateway. O validador aceita `gateway_address` e `application_gateway`; o deployment de NGINX ainda não foi implementado.

Inputs e gates restantes:

1. Validar no host-alvo a atribuição Quadlet dos IPs aprovados `192.168.7.2` e `192.168.8.2`.
2. NGINX usa `0.0.0.0:8080`, mapeado ao TCP `80` do container. A rede externa encaminha tráfego para o IP DHCP atual do host.
3. `/app` e `/app/api/` apontam ao mesmo `webApp:8000`; FastAPI serve os assets Vite e a API.
4. Decisão confirmada: FastAPI serve assets e API no mesmo processo `webApp:8000` e mantém credenciais PostgreSQL. Browser assets não são processos do container; teste que build output e respostas HTTP nunca exponham essas credenciais.
5. Implementar deployment NGINX e atualização idempotente do Gateway quando novas redes forem adicionadas.
6. Verificar que os CIDRs escolhidos não conflitam com redes existentes ou rotas externas de VPN antes de deployment.
7. SSH do Gateway usa bind `0.0.0.0` para forwarding externo sob controle do perímetro; Cockpit permanece em `127.0.0.1`.
