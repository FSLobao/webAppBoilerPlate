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
- SELinux em modo Enforcing;
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
- NAT;
- TCP forwarding;
- acesso às redes de desenvolvimento das aplicações;
- ferramentas de diagnóstico;
- Cockpit;
- cockpit-podman.

O Gateway é uma **unidade administrativa única**.

Não deve ser criado um gateway independente por aplicação salvo necessidade arquitetural futura claramente justificada.

---

## 4.2 Application Gateway

Container independente do Gateway.

Responsabilidade:

- receber conexões HTTP/HTTPS;
- encaminhar requests para as aplicações;
- eventualmente realizar TLS termination;
- eventualmente realizar virtual hosting;
- eventualmente aplicar políticas de acesso específicas da aplicação.

Tecnologias possíveis incluem Nginx, Caddy ou outra solução equivalente.

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

Os serviços devem ser independentes e substituíveis.

As imagens do Gateway e das aplicações devem usar uma distribuição Linux eficiente e mantida,
preferencialmente Debian ou Alpine. A distribuição do container é independente do host RHEL.

---

## 4.4 Database

PostgreSQL deve ser executado em container.

O banco deve possuir armazenamento persistente através de volume dedicado.

O PostgreSQL não deve ser acessível diretamente pela rede externa de desenvolvimento salvo necessidade excepcional.

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

# 6. Modelo de privilégios do Gateway

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

A configuração final de capabilities será definida durante a implementação e validada em RHEL 9.8 com Podman rootful 5.8.2.

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

## 8.2 Gateway compartilhado

O Gateway compartilhado deve possuir uma interface Podman para cada rede no inventário global `networks` de `config/host_config.json`. Ele não mantém uma lista seletiva de redes por serviço:

```text
                 Gateway
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

O fato de o Gateway possuir acesso às redes não implica que as redes tenham conectividade entre si.

O Gateway é a exceção confiável: conectado a todas as redes, ele pode iniciar conexões para todos os containers, inclusive bancos. O isolamento entre redes de aplicação não protege esses serviços de um Gateway comprometido. Mantenha autenticação nos destinos e trate o container Gateway como componente administrativo de alto privilégio.

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
    reachable Gateway address (NAT) or container IP (routed network)
```

## 9.2 Configuração gerada pelo deployment

A configuração do DNSMasq deverá ser gerada ou atualizada pelo mecanismo de deployment.

O deployment deverá conhecer a relação entre:

```text
application
    └── service
          ├── current container address and service port
          ├── optional Gateway NAT listener address and port
          └── DNS answer selected for routed or NAT clients
```

e produzir os registros DNS correspondentes.

Exemplo:

```text
backend.project-a.dev.internal
frontend.project-a.dev.internal
backend.project-b.dev.internal
```

A configuração deverá ser regenerável sem intervenção manual dentro do container do gateway.

Para clientes remotos sem uma rota para os CIDRs Podman, o registro DNS resolve para o endereço alcançável do Gateway; a regra NAT encaminha a porta declarada ao endereço e à porta atuais do container. DNS não transporta portas, portanto serviços TCP distintos no mesmo endereço precisam de portas externas únicas. Registros com IP de container são válidos somente para clientes com rotas explícitas até essa rede.

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

Esses nomes apontam para endereços das redes Podman somente quando os clientes possuem rotas para esses CIDRs. Para acesso remoto por NAT, apontam para o endereço alcançável do Gateway; a porta do serviço é declarada separadamente.

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

Quando um container for recriado, o deployment deverá atualizar o destino NAT para o novo endereço. No modo NAT, o registro DNS continua apontando para o endereço estável do Gateway; em redes roteadas, o registro aponta para o endereço atual do container.

O desenvolvedor continuará utilizando o mesmo nome lógico.

```text
backend.project-a.dev.internal
        │
        ▼
   current backend IP
```

## 9.5 Escopo

O Gateway deve disponibilizar resolução para todas as aplicações cujas redes estejam conectadas ao gateway.

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



---

# 11. Acesso SSH e VS Code

O Gateway será o ponto de entrada para acesso SSH aos containers. Para clientes remotos, uma exposição NAT explícita encaminha uma porta alcançável do Gateway ao serviço SSH do container; a autenticação continua ocorrendo no destino.

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


---

# 13. NAT e forwarding

NAT é uma função fundamental do Gateway.

Deve permitir, quando necessário:

- acesso de desenvolvedores a serviços nas redes Podman;
- port forwarding;
- encaminhamento de conexões;
- tradução de endereços quando a topologia exigir.

O NAT não deve ser utilizado como mecanismo primário de segurança.

O JSON de configuração define endereço de bind, porta externa, serviço/container de destino, rede e porta atual do container. DNSMasq resolve o nome ao endereço alcançável do Gateway; a porta é configurada separadamente. Não existe uma segunda aprovação por serviço: os endpoints declarados no JSON constituem o estado desejado, e o perímetro externo controla quem pode alcançá-los. O Gateway também deve conseguir acessar SSH, HTTP/80 e outras portas dos containers em todas as redes anexadas.

Preservar o IP original do cliente é incompatível com SNAT, que reescreve esse endereço. Portanto, use DNAT sem SNAT e configure rotas de retorno para os CIDRs dos clientes via interface do Gateway em cada rede relevante. Valide o caminho simétrico no host e nos containers. Se essas rotas não puderem ser garantidas, escolha explicitamente entre SNAT (perde o IP original) ou um proxy que transporte metadados de origem e cujo serviço de destino suporte esse protocolo. Não declare preservação de IP com SNAT. O escopo inicial deve suportar TCP; adicione UDP somente para necessidade concreta.

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

A primeira implementação deverá usar Nginx. O container escuta TCP 80; o endereço de bind e a porta publicada no host ficam em `application_gateway` no `config/host_config.json`, com a porta padrão 80. Por aplicação, `/app` serve o frontend e `/app/api/<route>` encaminha ao FastAPI. A rota da API deve ser avaliada antes do fallback SPA. HTTP na porta 80 não criptografa tráfego; TLS deve terminar em Nginx ou em uma camada externa confiável antes de enviar credenciais ou dados sensíveis.

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

Recomendação inicial: Vite com módulos JavaScript sem framework, gerados como arquivos estáticos. Para aplicações muito pequenas, HTML/CSS/JavaScript sem build também é válido; adote Vue, Svelte ou React somente quando complexidade de estado, componentes reutilizáveis ou padrão da equipe justificar. O plano de stack compara as opções.

O padrão de API recomendado é mesma origem e prefixo por aplicação: `/app` serve o frontend e `/app/api/<route>` encaminha ao FastAPI. Um hostname separado para a API permanece uma alternativa futura para consumidores independentes, mas exige CORS, DNS e TLS adicionais.

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


O backup obrigatório executa `pg_dumpall` sem filtros para salvar dados, estrutura de todos os bancos e objetos globais do cluster. O schedule e o caminho do mount remoto são configurados por instância PostgreSQL no JSON; um timer systemd é gerado a partir do schedule. O mount e a retenção são responsabilidade da infraestrutura de armazenamento; o job falha se o mount não estiver disponível e não usa fallback local. Restore é uma ação manual do operador: conexão direta e privada ao PostgreSQL, seguida da execução do SQL completo via `psql`. Não exponha PostgreSQL pelo Application Gateway nem restaure automaticamente durante deployment.

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
7. gerar DNSMasq com endereços alcançáveis e destinos atuais conforme o modo NAT ou roteado;
8. instalar exposições NAT explícitas para serviços remotos;
9. configurar rotas HTTP/HTTPS do Application Gateway;
10. carregar chaves públicas SSH dos arquivos seguros no host;
11. iniciar serviços em ordem, verificar saúde e testar conexões remotas;
12. apresentar estado, logs, recursos alterados e instruções de recuperação.
13. gerar, para cada PostgreSQL configurado, um timer systemd do schedule JSON e uma execução `pg_dumpall` completa no mount remoto declarado.

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
2. nenhum acesso desnecessário ao host;
3. Podman socket não exposto por TCP;
4. secrets fora do Git;
5. containers com filesystem mínimo;
6. evitar `--privileged`;
7. capabilities específicas quando possível;
8. redes de aplicações isoladas;
9. PostgreSQL não exposto externamente;
10. Gateway não utilizado para servir tráfego de usuários;
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
| Alvo de qualificação do host | RHEL 9.8 com SELinux Enforcing |
| Runtime de containers | Podman 5.8.2 rootful |
| Imagens de containers | Distribuição Linux eficiente e mantida; preferir Debian ou Alpine |
| Ciclo de vida dos containers | Quadlet para containers persistentes |
| Podman mode | Rootful |
| Backend | Python + FastAPI |
| Frontend | Vite com JavaScript sem framework como opção inicial proposta; HTML/JS estático para páginas pequenas |
| Rota frontend/API | `/app` e `/app/api/<route>` no mesmo domínio |
| Database | PostgreSQL |
| Gateway | Um único container compartilhado |
| Gateway por aplicação | Não |
| Cockpit | Dentro do Gateway |
| cockpit-podman | Dentro do Gateway |
| Application Gateway | Nginx compartilhado separado do Development Gateway |
| Porta HTTP pública | TCP 80 por padrão; endereço de bind e portas definidos no JSON |
| Rede por aplicação | Sim |
| Gateway compartilhado entre redes | Sim; uma interface Podman para cada rede no inventário global `networks` |
| Acesso do Gateway | A todas as redes e serviços Podman, sem aprovação individual por serviço; componente administrativo confiável |
| Inventário de redes | `config/host_config.json` declara todas as redes; blocos opcionais configuram serviços do host |
| DNS de desenvolvimento | DNSMasq no Gateway |
| Configuração DNS | Gerada/atualizada pelo deployment |
| Nomes internos | DNSMasq aponta ao endereço do Gateway em NAT; IP de container somente para clientes com rota ao CIDR |
| Nomes externos | Namespace/endpoints externos separados |
| NAT | DNAT-only; endereços/portas no JSON e rota simétrica para preservar IP de origem; sem SNAT |
| SSH | Via Gateway |
| SSH para aplicações | Gateway realiza forwarding; autenticação ocorre no destino |
| SSH para gateway | Autenticação no próprio Gateway |
| SSH keys | Individuais por desenvolvedor |
| SSH shared keys | Não |
| SSH Certificate Authority | Fora do boilerplate inicial |
| VPN | Opcional/futura |
| Firewall de usuários | Fora do gateway |
| Podman API | Preferencialmente Unix socket |
| Acesso diário ao host | Não |
| Deployment | Scripts versionados e Quadlet; preflight comum e verificações específicas por serviço |
| SSH key bootstrap | Chaves públicas de arquivos root-owned; host audit registra alterações; PAM externo |
| Backup PostgreSQL | `pg_dumpall` integral; schedule e mount no JSON; restore manual via `psql`; retenção pelo storage |
| Application secrets | Fora do Git |
| Secret storage inicial | Arquivos no host |
| Secret mapping | Somente leitura e apenas para containers necessários |
| Secret Manager | Integração futura, fora do boilerplate inicial |

# 29. Decisões ainda abertas

As seguintes perguntas permanecem para o desenho detalhado:

1. Quais endereços remotos reais devem substituir os exemplos no JSON, e quem mantém DNS externo e as regras do perímetro?
2. Quais CIDRs de clientes remotos precisam de rotas de retorno via Gateway em cada rede Podman para preservar o IP de origem com DNAT-only?
3. Quais capabilities mínimas e rotas de host/container permitem esse caminho simétrico no RHEL 9.8 / Podman 5.8.2 com SELinux Enforcing?
4. Qual configuração SELinux permite Cockpit acessar o socket rootful sem desativar SELinux ou usar relabel amplo?
5. Qual será a política determinística de alocação de CIDRs e prevenção de sobreposição com redes corporativas?
6. Onde termina TLS para o Nginx HTTP/80 público, e quem provisiona/rotaciona certificados e DNS externo?
7. Vite com JavaScript sem framework é um default aceitável para o SPA? O plano explica o tradeoff versus HTML/JS estático sem build e frameworks Vue/Svelte/React.
8. Um schedule `daily` é um default razoável para `pg_dumpall`, configurável por instância no JSON? O storage remoto define retenção.
9. A expansão opcional de `host_config.json` para exposições NAT requer `schema_version` 2 ou pode manter compatibilidade com a versão 1?
10. Qual responsável converterá a receita Debian separada do File Gateway em uma implantação containerizada? Seu bootstrap de host não deve ser executado no RHEL 9.8.

Essas decisões não devem alterar os princípios arquiteturais deste documento sem revisão explícita.

# 30. Critérios de aceitação arquitetural

Uma implementação do boilerplate será considerada aderente quando:

- uma aplicação puder ser implantada sem alterar manualmente o host na operação normal;
- cada aplicação possuir rede Podman independente;
- o inventário completo de redes e as opções de serviço estiverem declarados em `config/host_config.json`;
- o Gateway puder acessar múltiplas redes;
- o Gateway compartilhado possuir uma interface em cada rede configurada;
- o Gateway alcançar SSH, HTTP/80 e outros serviços em todas as redes, sem transformá-las em uma única rede;
- uma nova aplicação puder ser adicionada sem criar outro gateway;
- desenvolvedores puderem acessar containers por SSH/VS Code através do gateway;
- o gateway realizar forwarding sem substituir a autenticação SSH do container de aplicação;
- endereços e portas publicados forem declarados no JSON, com Nginx em TCP/80 como default e sem fluxo extra de aprovação por serviço;
- rotas Nginx servirem `/app` e encaminharem `/app/api/<route>` ao FastAPI;
- DNAT preservar o IP original do cliente, sem SNAT, com rotas de retorno simétricas comprovadas;
- deployment usar Quadlet e passar aceitação em RHEL 9.8, rootful Podman 5.8.2 e SELinux Enforcing;
- chaves públicas individuais puderem ser provisionadas pelo bootstrap do deployment;
- chaves públicas forem lidas de arquivos root-owned no host e alterações forem registradas pela auditoria existente; PAM permanece responsabilidade externa;
- o próprio gateway possuir autenticação SSH independente;
- Cockpit permitir administrar os containers;
- Podman API não estiver exposto desnecessariamente;
- PostgreSQL possuir armazenamento persistente;
- backup `pg_dumpall` cobrir dados e estrutura de todos os bancos, com schedule e mount remoto definidos no JSON e restore manual via `psql`;
- Application Gateway estiver separado do Gateway;
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
│ Gateway     │           │ Application Gateway │
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

A característica central do projeto é que **o Gateway é compartilhado**, enquanto **as redes e os componentes de cada aplicação permanecem isolados**.

Isso proporciona um único ponto de manutenção para os desenvolvedores sem transformar as aplicações em uma única rede ou exigir um gateway dedicado por aplicação.

---

# 33. Próxima etapa

Use os planos de implementação abaixo para decompor o contrato sem misturar acesso administrativo, tráfego de usuários e ciclo de vida das aplicações:

1. [Application Gateway](application-gateway-plan.md): entrada HTTP/HTTPS, roteamento, TLS e isolamento de rede.
2. [Application stack](application-stack-plan.md): frontend, backend FastAPI e PostgreSQL.
3. [Application deployment and operations](application-deployment-plan.md): configuração declarativa, secrets, volumes, atualização, recuperação e handoff de DNS.

Resolva as perguntas da seção 29 antes de implementar as decisões afetadas. Valide requisitos de Podman, Quadlet e SELinux em um host descartável RHEL 9.8 com Podman rootful 5.8.2. Testes locais de containers não são aceitação do host.
