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
- isolamento entre aplicações;
- desenvolvimento remoto por VS Code;
- manutenção direta dos containers;
- deployment reproduzível a partir do host;
- mínimo de dependências no host RHEL 9;
- separação entre acesso administrativo e prestação do serviço;
- configuração versionada no Git;
- utilização preferencial de componentes maduros em vez de software administrativo desenvolvido especificamente para o boilerplate.

---

# 2. Ambiente-alvo

## 2.1 Host

O ambiente de produção/desenvolvimento remoto é suportado por:

- Red Hat Enterprise Linux 9;
- Podman;
- acesso administrativo ao host restrito à equipe responsável pela infraestrutura;
- autenticação do acesso ao host realizada pelos mecanismos corporativos existentes;
- firewall e controles de acesso externos ao ambiente dos containers.

O boilerplate **não deve exigir acesso administrativo permanente dos desenvolvedores ao host RHEL**.

O host é responsável principalmente por:

- executar Podman;
- fornecer armazenamento;
- executar os containers;
- aplicar a configuração inicial do ambiente;
- executar operações excepcionais de infraestrutura.

---

# 3. Princípio fundamental de isolamento

A arquitetura possui três planos distintos:

```text
### 3. Princípio fundamental de isolamento

A arquitetura possui três planos distintos:

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
       Development Gateway            Application Gateway
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

O Development Gateway assume que uma conexão que chegou até ele já passou pelos mecanismos externos de autorização.

## 3.2 Management Plane

Responsável por:

- acesso SSH;
- túneis;
- NAT e forwarding;
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

Esse plano é independente do Development Gateway.

---

# 4. Containers principais

O boilerplate define quatro categorias lógicas de containers.

## 4.1 Development Gateway

Container compartilhado entre todas as aplicações.

Responsabilidades:

- SSH;
- DNS;
- routing;
- NAT;
- TCP forwarding;
- acesso às redes de desenvolvimento das aplicações;
- ferramentas de diagnóstico;
- Cockpit;
- cockpit-podman.

O Development Gateway é uma **unidade administrativa única**.

Não deve ser criado um gateway independente por aplicação salvo necessidade arquitetural futura claramente justificada.

---

## 4.2 Application Gateway

Container independente do Development Gateway.

Responsabilidade:

- receber conexões HTTP/HTTPS;
- encaminhar requests para as aplicações;
- eventualmente realizar TLS termination;
- eventualmente realizar virtual hosting;
- eventualmente aplicar políticas de acesso específicas da aplicação.

Tecnologias possíveis incluem Nginx, Caddy ou outra solução equivalente.

A escolha concreta deve ser definida separadamente da arquitetura do Development Gateway.

O Application Gateway **não deve ser utilizado como canal de manutenção dos containers**.

---

## 4.3 Application containers

Cada aplicação pode possuir:

- backend;
- frontend;
- worker;
- scheduler;
- serviços auxiliares.

Os serviços devem ser independentes e substituíveis.

---

## 4.4 Database

PostgreSQL deve ser executado em container.

O banco deve possuir armazenamento persistente através de volume dedicado.

O PostgreSQL não deve ser acessível diretamente pela rede externa de desenvolvimento salvo necessidade excepcional.

---

# 5. Development Gateway

## 5.1 Composição

O Development Gateway será um único container baseado em Debian minimal.

Componentes previstos:

```text
Debian
├── OpenSSH
├── DNS service
├── routing / IP forwarding
├── NAT
├── TCP forwarding / tunneling
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

# 6. Modelo de privilégios do Development Gateway

O gateway necessita de capacidades de rede para:

- forwarding;
- NAT;
- routing;
- acesso às redes Podman;
- SSH.

Entretanto, o container não deve receber acesso indiscriminado ao host RHEL.

Particularmente, deve-se evitar, sem justificativa:

- montagem do filesystem completo do host;
- acesso irrestrito a `/proc` do host;
- acesso irrestrito a `/sys` do host;
- execução `--privileged` quando capacidades específicas forem suficientes;
- exposição remota do Podman socket.

A configuração final de capabilities será definida durante a implementação e validada no RHEL 9.

---

# 7. Firewall

O Development Gateway **não é concebido como firewall de segurança do ambiente**.

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

Cada aplicação deve possuir uma rede Podman própria.

Exemplo:

```text
project-a-net
project-b-net
project-c-net
```

As redes são independentes.

Não deve existir uma rede global compartilhada entre todas as aplicações apenas para facilitar o acesso administrativo.

---

## 8.2 Development Gateway compartilhado

O Development Gateway pode estar conectado a múltiplas redes:

```text
                 Development Gateway
                  /        |        \
                 /         |         \
        project-a-net project-b-net project-c-net
```

O gateway funciona como ponto comum de administração, sem transformar as redes das aplicações em uma única rede.

---

## 8.3 Isolamento

Por padrão:

```text
project-a-net  ──X── project-b-net
project-a-net  ──X── project-c-net
project-b-net  ──X── project-c-net
```

O acesso entre aplicações deve ser explicitamente configurado quando necessário.

O fato de o Development Gateway possuir acesso às redes não implica que as redes tenham conectividade entre si.

---

# 9. DNS de desenvolvimento

## 9.1 DNSMasq

O Development Gateway deverá executar **DNSMasq** como serviço DNS de desenvolvimento.

O objetivo é fornecer aos desenvolvedores resolução de nomes para os serviços dos containers sem exigir conhecimento ou gerenciamento manual de seus endereços IP.

O fluxo esperado é:

```text
Developer
    │
    │ DNS query
    ▼
Development Gateway
    │
    ▼
DNSMasq
    │
    ▼
generated DNS configuration
    │
    ▼
container IP
```

## 9.2 Configuração gerada pelo deployment

A configuração do DNSMasq deverá ser gerada ou atualizada pelo mecanismo de deployment.

O deployment deverá conhecer a relação entre:

```text
application
    └── service
          └── current container address
```

e produzir os registros DNS correspondentes.

Exemplo:

```text
backend.project-a.dev.internal
frontend.project-a.dev.internal
backend.project-b.dev.internal
```

A configuração deverá ser regenerável sem intervenção manual dentro do container do gateway.

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

Esses nomes podem apontar diretamente para endereços das redes Podman ou para endpoints destinados ao acesso administrativo.

### Nomes externos de aplicação

Utilizados pelos usuários/consumidores da aplicação.

Exemplos conceituais:

```text
app-a.example.com
api-a.example.com
```

Esses nomes são responsabilidade do Application Gateway e da infraestrutura DNS externa.

Os namespaces interno e externo não devem ser tratados como equivalentes.

## 9.4 Containers recriados

Os endereços IP individuais dos containers não constituem identidade permanente.

Quando um container for recriado, o deployment deverá atualizar a configuração do DNSMasq para refletir o novo endereço.

O desenvolvedor continuará utilizando o mesmo nome lógico.

```text
backend.project-a.dev.internal
        │
        ▼
   current backend IP
```

## 9.5 Escopo

O Development Gateway deve disponibilizar resolução para todas as aplicações cujas redes estejam conectadas ao gateway.

A existência de registros DNS não implica conectividade entre as redes das aplicações.

## 9.6 Serviços publicados no DNS

Somente serviços que necessitem de acesso administrativo ou de desenvolvimento devem receber nomes DNS de desenvolvimento.

Por padrão, bancos de dados e outros serviços internos não devem ser publicados para desenvolvedores sem necessidade explícita.

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

O mecanismo de deployment deve possuir uma política determinística para alocação ou validação de CIDRs.

Endereços IP individuais de containers não devem ser tratados como identificadores permanentes.

---


O Development Gateway deve fornecer ou encaminhar DNS para nomes de desenvolvimento.

Os desenvolvedores não devem precisar conhecer IPs dos containers.

Exemplos conceituais:

```text
backend.project-a.dev
frontend.project-a.dev

backend.project-b.dev
frontend.project-b.dev
```

O mecanismo concreto de DNS será definido na implementação.

A resolução deve ser compatível com containers recriados.

---

# 11. Acesso SSH e VS Code

O Development Gateway será o ponto de entrada para acesso SSH aos containers.

O objetivo é permitir utilização do:

**VS Code Remote - SSH**

ou mecanismos equivalentes.

## 11.1 Papel do gateway no SSH

Para acesso aos containers das aplicações, o Development Gateway deverá atuar como **gateway de forwarding**, e não como autoridade de autenticação dos desenvolvedores.

O gateway não deverá validar a identidade do desenvolvedor para os containers de aplicação. A autenticação SSH deverá ocorrer no próprio destino, utilizando as credenciais/chaves configuradas para aquele container.

Conceitualmente:

```text
Developer
   │
   │ SSH connection
   ▼
Development Gateway
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

## 11.2 Acesso ao próprio Development Gateway

O próprio container do Development Gateway constitui uma exceção.

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

O bootstrap poderá receber um conjunto de chaves públicas por desenvolvedor e instalá-las nos destinos correspondentes.

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

VPN não faz parte obrigatória do boilerplate.

O gateway deve, entretanto, permitir futura integração com tecnologias de VPN.

Exemplos possíveis:

- WireGuard;
- OpenVPN;
- Tailscale;
- VPN corporativa;
- outras tecnologias compatíveis.

A tecnologia de VPN será uma decisão de implantação.

O boilerplate não deve assumir uma tecnologia específica.

O gateway deve, entretanto, permitir futura integração com tecnologias de VPN.

Exemplos possíveis:

- WireGuard;
- OpenVPN;
- Tailscale;
- VPN corporativa;
- outras tecnologias compatíveis.

A tecnologia de VPN será uma decisão de implantação.

O boilerplate não deve assumir uma tecnologia específica.

---

# 13. NAT e forwarding

NAT é uma função fundamental do Development Gateway.

Deve permitir, quando necessário:

- acesso de desenvolvedores a serviços nas redes Podman;
- port forwarding;
- encaminhamento de conexões;
- tradução de endereços quando a topologia exigir.

O NAT não deve ser utilizado como mecanismo primário de segurança.

---

# 14. Application Gateway

O Application Gateway possui função distinta do Development Gateway.

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

---

# 15. Backend

O backend será implementado em:

- Python;
- FastAPI;
- ambiente Python versionado;
- container próprio.

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

A tecnologia concreta do framework JavaScript deve ser definida em uma decisão separada.

---

# 17. PostgreSQL

PostgreSQL será o banco padrão do boilerplate.

Características:

- container independente;
- volume persistente;
- rede de banco dedicada;
- acesso normalmente permitido somente ao backend;
- credenciais fora do código-fonte;
- backup tratado como preocupação de infraestrutura.

Topologia recomendada:

```text
backend
   │
   ▼
database network
   │
   ▼
PostgreSQL
```

Frontend não deve acessar PostgreSQL diretamente.

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

1. validar pré-requisitos;
2. criar a estrutura de diretórios necessária no host;
3. criar/configurar redes;
4. criar volumes necessários;
5. preparar a estrutura de secrets;
6. configurar chaves públicas SSH de bootstrap;
7. criar ou atualizar containers;
8. conectar o Development Gateway às redes das aplicações;
9. gerar/atualizar a configuração do DNSMasq;
10. configurar o Application Gateway;
11. iniciar os serviços;
12. verificar saúde básica;
13. apresentar informações úteis para manutenção.

O deployment deve ser idempotente sempre que possível.

Executar o deployment novamente não deve destruir dados persistentes ou secrets existentes.

O deployment deverá ser capaz de reproduzir a configuração estrutural do ambiente sem exigir acesso manual aos containers.

## 20.1 Bootstrap de acesso

A configuração inicial deverá poder incluir as chaves públicas SSH dos desenvolvedores autorizados.

O mecanismo de bootstrap deverá permitir distinguir:

- chaves para acesso aos containers de aplicação;
- chaves para acesso administrativo ao próprio Development Gateway.

As chaves privadas nunca deverão ser copiadas para o ambiente pelo deployment.

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

O Development Gateway deve incluir ferramentas suficientes para investigar rapidamente problemas de conectividade.

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
├── config/
├── docs/
├── scripts/
└── compose/
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
2. nenhum acesso desnecessário ao host;
3. Podman socket não exposto por TCP;
4. secrets fora do Git;
5. containers com filesystem mínimo;
6. evitar `--privileged`;
7. capabilities específicas quando possível;
8. redes de aplicações isoladas;
9. PostgreSQL não exposto externamente;
10. Development Gateway não utilizado para servir tráfego de usuários;
11. Application Gateway não utilizado como canal administrativo;
12. autenticação SSH individual, sem chaves privadas compartilhadas;
13. chaves privadas nunca armazenadas no gateway;
14. secrets de aplicação fora do Git;
15. secrets montados somente onde necessários e em modo somente leitura;
16. imagens versionadas e atualizadas.

---

# 28. Decisões arquiteturais já estabelecidas

As seguintes decisões são consideradas parte do contrato:

| Decisão | Escolha |
|---|---|
| Host | RHEL 9 |
| Runtime | Podman |
| Podman mode | Rootful |
| Backend | Python + FastAPI |
| Frontend | JavaScript |
| Database | PostgreSQL |
| Development Gateway | Um único container compartilhado |
| Gateway por aplicação | Não |
| Cockpit | Dentro do Development Gateway |
| cockpit-podman | Dentro do Development Gateway |
| Application Gateway | Container separado |
| Rede por aplicação | Sim |
| Gateway compartilhado entre redes | Sim |
| DNS de desenvolvimento | DNSMasq no Development Gateway |
| Configuração DNS | Gerada/atualizada pelo deployment |
| Nomes internos | Namespace DNS interno de desenvolvimento |
| Nomes externos | Namespace/endpoints externos separados |
| NAT | Via Development Gateway |
| SSH | Via Development Gateway |
| SSH para aplicações | Gateway realiza forwarding; autenticação ocorre no destino |
| SSH para gateway | Autenticação no próprio Development Gateway |
| SSH keys | Individuais por desenvolvedor |
| SSH shared keys | Não |
| SSH Certificate Authority | Fora do boilerplate inicial |
| VPN | Opcional/futura |
| Firewall de usuários | Fora do gateway |
| Podman API | Preferencialmente Unix socket |
| Acesso diário ao host | Não |
| Deployment | Scripts versionados |
| SSH key bootstrap | Parte do deployment |
| Application secrets | Fora do Git |
| Secret storage inicial | Arquivos no host |
| Secret mapping | Somente leitura e apenas para containers necessários |
| Secret Manager | Integração futura, fora do boilerplate inicial |

# 29. Decisões ainda abertas

As seguintes questões permanecem para o desenho detalhado:

1. capabilities exatas necessárias ao Development Gateway;
2. mecanismo de acesso do Cockpit ao Podman socket;
3. estratégia exata de alocação de CIDRs;
4. tecnologia do Application Gateway;
5. framework JavaScript do frontend;
6. estratégia de backup PostgreSQL;
7. estratégia de atualização das imagens;
8. health checks;
9. estratégia de logs;
10. política de versionamento das imagens;
11. mecanismo de certificados TLS;
12. integração opcional com VPN;
13. política de acesso temporário aos ambientes;
14. mecanismo de exposição dos endpoints do Application Gateway.

Essas decisões não devem alterar os princípios arquiteturais deste documento sem revisão explícita.

# 30. Critérios de aceitação arquitetural

Uma implementação do boilerplate será considerada aderente quando:

- uma aplicação puder ser implantada sem alterar manualmente o host na operação normal;
- cada aplicação possuir rede Podman independente;
- o Development Gateway puder acessar múltiplas redes;
- uma nova aplicação puder ser adicionada sem criar outro gateway;
- desenvolvedores puderem acessar containers por SSH/VS Code através do gateway;
- o gateway realizar forwarding sem substituir a autenticação SSH do container de aplicação;
- chaves públicas individuais puderem ser provisionadas pelo bootstrap do deployment;
- o próprio gateway possuir autenticação SSH independente;
- Cockpit permitir administrar os containers;
- Podman API não estiver exposto desnecessariamente;
- PostgreSQL possuir armazenamento persistente;
- Application Gateway estiver separado do Development Gateway;
- o acesso externo continuar controlado pela infraestrutura de segurança existente;
- deployment puder ser repetido sem destruir dados;
- diagnóstico básico de rede puder ser realizado sem acesso ao host RHEL;
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
                         EXTERNAL SECURITY
                    VPN / Firewall / ACL / Auth
                               │
             ┌─────────────────┴─────────────────┐
             │                                   │
             ▼                                   ▼
     Development access                  Application access
             │                                   │
             ▼                                   ▼
┌─────────────────────────┐           ┌─────────────────────┐
│ Development Gateway     │           │ Application Gateway │
│                         │           │                     │
│ Debian                  │           │ HTTP / HTTPS        │
│ SSH                     │           │ Reverse proxy       │
│ DNS                     │           │ TLS                 │
│ NAT / Routing           │           └──────────┬──────────┘
│ Diagnostics             │                      │
│ Cockpit                 │                      │
│ cockpit-podman          │                      │
└───────────┬─────────────┘                      │
            │                                    │
            │ Podman API                         │
            │                                    │
     ┌──────┼──────────────┐                     │
     │      │              │                     │
     ▼      ▼              ▼                     ▼
  App A   App B          App C               Applications
  network network        network
     │      │              │
     │      │              │
 backend  backend       backend
 frontend frontend      frontend
 postgres postgres      postgres
```

A característica central do projeto é que **o Development Gateway é compartilhado**, enquanto **as redes e os componentes de cada aplicação permanecem isolados**.

Isso proporciona um único ponto de manutenção para os desenvolvedores sem transformar as aplicações em uma única rede ou exigir um gateway dedicado por aplicação.

---

# 33. Próxima etapa

Depois da aprovação deste contrato arquitetural, a próxima etapa recomendada é produzir um **desenho técnico de implementação**, ainda sem necessariamente escrever o código da aplicação, contendo:

1. topologia exata das redes Podman;
2. portas;
3. interfaces do Development Gateway;
4. fluxo de SSH;
5. fluxo de DNS;
6. fluxo de NAT;
7. integração Cockpit/Podman socket;
8. capabilities do container;
9. volumes;
10. estrutura dos arquivos de deployment;
11. ciclo de vida dos containers;
12. fluxo de criação de uma nova aplicação;
13. fluxo de atualização;
14. fluxo de remoção;
15. fluxo de recuperação de falhas.

Esse desenho deverá ser validado contra as restrições reais do RHEL 9/Podman antes da implementação.
