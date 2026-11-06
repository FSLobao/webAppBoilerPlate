<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#1-objetivo">Objetivo</a></li>
        <li><a href="#2-ambiente-alvo">Ambiente-alvo</a></li>
        <li><a href="#3-princípio-fundamental-de-isolamento">Princípio fundamental de isolamento</a></li>
        <li><a href="#4-containers-principais">Containers principais</a></li>
        <li><a href="#5-gateway">Gateway</a></li>
        <li><a href="#6-aplicações">Aplicações</a></li>
        <li><a href="#7-postgresql">PostgreSQL</a></li>
        <li><a href="#8-http-proxy">HTTP Proxy</a></li>
        <li><a href="#9-rede-podman-e-dns-de-desenvolvimento">Rede Podman e DNS de desenvolvimento</a></li>
        <li><a href="#10-endereçamento-da-rede-podman">Endereçamento da rede Podman</a></li>
        <li><a href="#11-acesso-aos-containers-e-vs-code">Acesso aos containers e VS Code</a></li>
        <li><a href="#12-volumes">Volumes</a></li>
        <li><a href="#13-configuração-e-secrets">Configuração e secrets</a></li>
        <li><a href="#14-deployment">Deployment</a></li>
        <li><a href="#15-manutenção">Manutenção</a></li>
        <li><a href="#16-diagnóstico">Diagnóstico</a></li>
        <li><a href="#17-observabilidade">Observabilidade</a></li>
        <li><a href="#18-estrutura-lógica-do-repositório">Estrutura lógica do repositório</a></li>
        <li><a href="#19-regras-para-desenvolvimento-no-vs-code">Regras para desenvolvimento no VS Code</a></li>
        <li><a href="#20-desenvolvimento-versus-produção">Desenvolvimento versus produção</a></li>
        <li><a href="#21-princípios-de-segurança">Princípios de segurança</a></li>
        <li><a href="#22-decisões-arquiteturais-já-estabelecidas">Decisões arquiteturais já estabelecidas</a></li>
        <li><a href="#23-restrições-de-implementação">Restrições de implementação</a></li>
        <li><a href="#24-critérios-de-aceitação-arquitetural">Critérios de aceitação arquitetural</a></li>
        <li><a href="#25-regra-de-evolução">Regra de evolução</a></li>
    </ol>
</details>

# Web Application Boilerplate — Arquitetura Lógica e Contrato de Desenvolvimento

**Status:** Contrato arquitetural aprovado; requisitos de implementação e aceitação registrados abaixo.
**Objetivo:** Definir o contrato técnico e operacional do boilerplate para desenvolvimento de aplicações web com Python/FastAPI, frontend JavaScript, PostgreSQL e execução integral em containers.

**Revisão do acesso remoto:** Headscale, Headplane e `tailscaled` no Gateway constituem a única
solução aprovada para conectividade de desenvolvedores. O alvo de runtime é Podman rootless com
Quadlet; a variante rootful permanece implementada e mantida como alternativa. O deploy do Gateway
rootless como código continua pendente em [TODO.md](../plans/TODO.md).
**Revisão da rede de containers:** o alvo rootless usa exclusivamente a bridge `gateway-vpn`,
`10.90.0.0/24`, com Netavark e Aardvark DNS, resolver `10.90.0.1` e Gateway `10.90.0.2`. A rede
padrão rootful `podman` permanece como alternativa. Não haverá redes por aplicação; preserve o IP
de origem VPN.

**Revisão da administração:** Portainer será a interface de gestão de containers, em container
dedicado na rede padrão `podman`, acessível somente por operadores pela VPN. A integração ainda
precisa ser implementada e validada no alvo RHEL 9.8 / Podman rootful 5.8.2.

---

# 1. Objetivo

Este documento define a arquitetura lógica, responsabilidades, limites e princípios do boilerplate.

O documento deve ser tratado como **contrato arquitetural** durante o desenvolvimento no VS Code. Alterações que modifiquem os princípios aqui definidos devem ser deliberadas e registradas antes da implementação.

O boilerplate deve privilegiar:

- simplicidade operacional;
- reprodutibilidade;
- baixo esforço administrativo;
- uma única rede rootless `gateway-vpn` (`10.90.0.0/24`) para todos os containers, com DNS nativo e autenticação por serviço; a rede padrão rootful `podman` permanece como alternativa;
- desenvolvimento remoto por VS Code;
- manutenção direta dos containers;
- deployment reproduzível a partir do host;
- mínimo de dependências no host RHEL 9.8 com Podman rootless 5.8.2 como alvo; rootful permanece alternativa;
- separação entre acesso administrativo e prestação do serviço;
- configuração versionada no Git;
- utilização preferencial de componentes maduros em vez de software administrativo desenvolvido especificamente para o boilerplate.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 2. Ambiente-alvo

## 2.1 Host

O ambiente de produção/desenvolvimento remoto é suportado por:

- Red Hat Enterprise Linux 9.8 como alvo de qualificação;
- Podman 5.8.2 em modo rootless e Quadlet como alvo; Podman rootful é a alternativa implementada e mantida;
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

## 2.2 Cockpit no host

Cockpit será instalado diretamente no host RHEL como interface de administração geral do servidor,
independente dos containers, do Gateway e do Portainer. A instalação, atualização e configuração
ficam sob responsabilidade da equipe de infraestrutura, usando pacotes suportados do RHEL e
ativação por `cockpit.socket`. Essa instalação está planejada; não foi executada por este contrato.

Seu escopo inclui serviços systemd, logs do host, armazenamento, interfaces de rede, atualizações,
contas e diagnóstico, conforme os módulos e as permissões disponíveis no RHEL. Portainer permanece
responsável pela interface de gestão dos containers; não instalar `cockpit-podman` como segunda
interface de gestão nem substituir o deployment declarativo Quadlet por operações manuais.

Cockpit usa autenticação do sistema integrada aos controles corporativos existentes e elevação
de privilégios autorizada pela política do host. Acesso fica restrito à equipe de infraestrutura,
com HTTPS e certificado confiável em endereço de gestão do host. A porta padrão é TCP `9090`;
bind e regras de ingresso devem limitar acesso à rede administrativa corporativa, sem exposição
pública ou liberação indiscriminada no firewall.

Esse endpoint administrativo do host deve permanecer acessível à infraestrutura quando o Gateway
ou a VPN de desenvolvimento estiverem indisponíveis. Não usa o proxy NGINX de aplicações nem
constitui outro canal de acesso remoto para desenvolvedores. Não instalar Cockpit no Gateway
ou publicar sua porta por Podman; não depende da rede de containers ou de seu DNS.

Mudanças de rede e serviços do host exigem os procedimentos de controle e recuperação da
infraestrutura. A indisponibilidade do Cockpit não deve interromper containers, VPN ou DNS.
O deployment do boilerplate não instala pacotes do host nem altera suas políticas de acesso.

Referência: [instalação e execução do Cockpit no RHEL](https://cockpit-project.org/running.html#rhel).

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 3. Princípio fundamental de isolamento

A arquitetura separa o perímetro de segurança e três planos funcionais:

```text
                  ┌──────────────────────────┐
                  │ Security Perimeter       │
                  │ Firewall / ACL /         │
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
       Development Gateway    NGINX de aplicações
               │                                │
               ▼                                ▼
          Podman network                 App endpoints
```

## 3.1 Security perimeter

O perímetro externo controla quem pode alcançar os endpoints publicados do ambiente.

Inclui, conforme a infraestrutura disponível:

- firewall externo;
- ACL;
- autenticação;
- autorização de acesso ao host/endpoint;
- controle de portas de entrada.

O perímetro externo garante a autenticação do usuário HTTP e do host, validando sua identidade e não requer qualquer autenticação adicional por parte da aplicação ou verificação posterior.

Necessária que solução proveja a autenticação complementar para acesso de desenvolvedores pela VPN, usando métodos nativos do sistema, assim como acesso SSH e a bancos de dados demandará configuração manual complementar.

## 3.2 Management Plane

Realizada no pelo Gateway Container e faz parte deste repositório. O Gateway

Responsável por:

- inscrição e autorização de dispositivos pelo Headscale;
- administração do acesso VPN pelo Headplane;
- conectividade VPN por clientes Tailscale e roteamento IP pelo Gateway;
- DNS de desenvolvimento;
- diagnóstico de rede;
- Portainer para gestão dos containers pela VPN;
- gerenciamento Podman;
- acesso de manutenção aos containers.

## 3.3 Application Plane

Utiliza a autenticação fornecida pelo perímetro externo para validar usuários HTTP e credenciais repassadas pelo proxy de autenticação como campos x-user.

Responsável por executar.

- backend;
- frontend;
- workers;
- banco de dados;
- outros serviços específicos da aplicação.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 4. Containers principais

O boilerplate define quatro tipos principais de containers. Portainer é um container de gestão
associado ao Gateway, detalhado na seção 5.2.

## 4.1 Gateway

Container compartilhado para acesso remoto, coordenação VPN e diagnóstico de rede.

Responsabilidades:

- servidor de coordenação Headscale;
- interface administrativa Headplane;
- daemon Tailscale (`tailscaled`) como subnet router;
- encaminhamento entre a VPN e a rede rootless `gateway-vpn`;
- ferramentas de diagnóstico;

Portainer usa container de gestão separado. A seção 5 define composição, privilégios, acesso e
recuperação do Gateway.

---

## 4.2 Application containers

Aplicações usam containers para backend, frontend e serviços auxiliares. A configuração inicial
combina frontend e FastAPI em `webApp`; PostgreSQL permanece separado. Detalhes estão na seção 6.

---

## 4.3 Database

PostgreSQL usa container e volume persistente, sem porta publicada no host. Autenticação e
autorização são responsabilidade do banco. Detalhes estão na seção 7.

## 4.4 HTTP Proxy

NGINX obrigatório fornece um endpoint HTTP compartilhado para as aplicações. Um segundo NGINX,
exclusivo para desenvolvimento, emula os cabeçalhos de identidade do acesso autenticado. Detalhes
e limites de ambos estão na seção 8.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 5. Gateway

## 5.1 Composição

O Gateway será um único container baseado em Debian minimal.

Componentes previstos:

```text
Debian
├── Headscale
├── Headplane
├── tailscaled (subnet router)
├── integração de rede conforme seção 9
├── routing / IP forwarding
├── iproute2
├── ss
├── tcpdump
├── conntrack
└── ferramentas básicas de diagnóstico
```

Portainer não é instalado na imagem do Gateway; usa sua própria imagem e container na rede
padrão, com acesso remoto roteado pelo Gateway.

Componentes adicionais somente devem ser incluídos quando houver necessidade operacional clara.

---

## 5.2 Portainer

Portainer será a interface administrativa dos containers, em container dedicado na rede padrão
`podman`. Headplane administra o acesso VPN; Portainer não substitui Headplane, Headscale ou
`tailscaled` e não fornece administração geral do sistema operacional do host.

Funções esperadas:

- visualização do estado e consumo de recursos dos containers;
- consulta a logs e diagnóstico de containers;
- console de containers para operadores autorizados;
- operações de gestão compatíveis com a API Podman, validadas no host-alvo;
- inspeção da rede padrão, volumes e imagens.

Portainer não participa do caminho dos dados das aplicações. Sua indisponibilidade não deve
interromper containers, conectividade VPN ou DNS.

Quadlet e os scripts versionados permanecem donos do deployment declarativo e do ciclo de vida
persistente. Não criar stacks ou recriar serviços por Portainer em paralelo com Quadlet.
Alterações estruturais precisam voltar à configuração versionada; operações de parada/reinício
devem respeitar as unidades systemd e suas políticas de reinício. Validar essas interações antes
de permitir operações pela interface.

Persistir os dados do Portainer em volume dedicado montado em `/data`, incluindo configuração,
usuários e credenciais protegidas. O bootstrap administrativo ocorre pelo operador de infraestrutura,
com token inicial protegido e acesso restrito; não deixar a criação do primeiro administrador aberta.
O endpoint HTTPS deve usar certificado confiável e autenticação própria, além da autorização VPN.
Não publicar portas de gestão no host ou expor funcionalidades Edge/Agent sem necessidade aprovada.

---

## 5.3 Integração Portainer e Podman

Portainer utiliza a API compatível com Docker exposta pelo serviço Podman, não uma integração
nativa com todos os recursos Podman. O operador habilita o socket rootful local
`/run/podman/podman.sock`, disponibilizado somente ao container Portainer em
`/var/run/docker.sock`. Não é necessário Agent para esse ambiente local.

O socket concede controle administrativo equivalente a root sobre os containers e potencialmente
sobre o host. Uma montagem somente leitura não transforma a API em somente leitura. Restrinja
Portainer a operadores de infraestrutura confiáveis; não conceda esse acesso a todo desenvolvedor.
Não montar esse socket no Gateway, Headplane ou containers de aplicação, nem expor a API por TCP.

A documentação de instalação Portainer para Podman descreve CentOS 9 e Podman 5.x rootful;
isso não comprova suporte ao alvo RHEL 9.8 / Podman 5.8.2. Fixar edição e versão compatíveis,
verificar a matriz do fornecedor e validar as operações necessárias no host-alvo. Recursos
indisponíveis na edição escolhida não podem ser presumidos.

O exemplo upstream utiliza `--privileged`; este contrato não autoriza essa opção. A implantação
deve demonstrar funcionamento com permissões mínimas, sem `--privileged`. Se isso não for possível,
bloquear a aceitação e solicitar revisão explícita, sem ampliar privilégios silenciosamente.

Referências: [Portainer com Podman](https://docs.portainer.io/start/install-ce/server/podman/linux)
e [requisitos e matriz de versões](https://docs.portainer.io/start/requirements-and-prerequisites).

## 5.4 Privilégios e firewall

O Gateway precisa de capacidades de rede para encaminhar tráfego, mas não deve receber acesso
indiscriminado ao host. Use capabilities específicas; não use `--privileged`, monte o filesystem
completo do host nem exponha o socket Podman.

O Gateway não é o firewall de segurança do ambiente. O perímetro controla endpoints publicados;
Headscale/Headplane controla acesso VPN. `firewalld` e `nftables` estão desativados no host-alvo.
A preparação do host desativa esses serviços quando presentes.

## 5.5 VPN, roteamento e acesso remoto

Headscale, Headplane e `tailscaled` compartilham o Gateway. Headscale coordena inscrição, políticas
e rotas; Headplane administra usuários e dispositivos; `tailscaled` atua como subnet router.
Clientes Tailscale conectam-se ao Headscale auto-hospedado.

A VPN é split tunnel IPv4. O Gateway rootless anuncia somente `10.90.0.0/24`, da rede
`gateway-vpn`; o resolver Aardvark é `10.90.0.1` e o Gateway usa `10.90.0.2`. Clientes autorizados
aceitam essa rota. Headscale usa o prefixo IPv4 `100.96.0.0/24`. Desative SNAT com
`--snat-subnet-routes=false` e instale a rota de retorno ao prefixo VPN na namespace rootless.
Preserve o IP VPN de origem. Não anuncie rota default nem transforme o Gateway em exit node. A rede
padrão rootful `podman` é a alternativa mantida.

O endpoint de controle do Headscale e o endpoint VPN usam diretamente TCP 443 no host, acessível
pela LAN antes da VPN; não encaminhe TCP 443 para 8443. Headplane e Portainer exigem HTTPS,
autenticação própria e acesso de operadores pela VPN. O Gateway não oferece bastion, listener de
shell nem transporte alternativo para desenvolvedores.

Inscrição usa tokens individuais, de uso único e validade curta. Clientes geram e mantêm chaves
privadas localmente. Expirar um token não revoga dispositivos já inscritos; operadores gerenciam
expiração e revogação separadamente.

O retorno da VPN usa rota na namespace rootless e `--snat-subnet-routes=false`. A rede rootless
usa o egress normal do Podman; a variante rootful pode usar masquerading. Não implante estado quando
prefixos ou rotas conflitarem. Rotas gerenciadas precisam de ownership, reconciliação idempotente
e rollback limitado ao estado do deployment.

Persistir identidade e banco do Headscale, estado de `tailscaled` e dados do Headplane em volumes
separados. Reinícios não devem exigir reinscrição. Falhas de processos e de saúde devem ser
explícitas; indisponibilidade do Headplane não interrompe tráfego VPN já autorizado.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 6. Aplicações

Cada aplicação pode usar containers para backend, frontend, workers, schedulers e serviços
auxiliares. A configuração inicial combina assets frontend e FastAPI no container `webApp`;
PostgreSQL permanece separado.

FastAPI fornece API REST/HTTP, lógica de negócio, integrações e acesso ao banco. Ele autoriza
usuários com base em identidade confiável fornecida pelo perímetro, quando aplicável. O backend
não assume funções de infraestrutura do Gateway.

Vite constrói assets JavaScript estáticos, servidos por FastAPI na aplicação inicial. O caminho
padrão é `/webapp/` para a SPA e `/webapp/api/` para a API, no mesmo listener TCP `8000`. Páginas pequenas
podem usar HTML/CSS/JavaScript sem build; adote framework somente quando a complexidade justificar.
Assets do browser nunca recebem credenciais PostgreSQL.

Frontend e FastAPI compartilham o container e não têm isolamento entre processos. Somente o
processo FastAPI deve receber credenciais PostgreSQL. Cada container de aplicação conecta-se
somente à rede rootless `gateway-vpn`, autentica seus próprios serviços e usa aliases únicos
declarados no Podman. A rede padrão `podman` fica como alternativa rootful.

Imagens devem usar distribuição mantida e eficiente, preferencialmente Debian ou Alpine. O host
RHEL não determina a distribuição dos containers.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 7. PostgreSQL

PostgreSQL 18 é o padrão inicial, com versão configurável por instância no JSON. Ele usa um
container separado, uma interface na rede rootless `gateway-vpn` e volume persistente. Não publique
sua porta no host. Desenvolvedores podem alcançar o serviço pela VPN roteada; PostgreSQL aplica
autenticação e autorização próprias.

Somente o processo FastAPI no container `webApp` recebe credenciais PostgreSQL. Como frontend e
backend compartilham o container, valide que os assets servidos ao browser nunca exponham essas
credenciais.

### Backup e recuperação

O plano, ainda não implementado, usa pgBackRest dentro do container PostgreSQL como conta
`postgres`; timers no host acionam operações locais limitadas. O plano propõe full mensal e
incremental semanal, com volumes separados para `PGDATA`, repositório de trabalho e exportações
concluídas.

Publique somente gerações completas e verificadas, sem expor transferências parciais. Não sobrescreva
backups publicados nem apague a origem antes do acknowledgement externo e da retenção necessária.
Falhas de volume, permissão ou cópia devem falhar sem fallback. Restore é manual e exige restore
drill; nunca restaure automaticamente durante deployment. Os caminhos e operações ainda não são
suportados pelo runtime atual.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 8. HTTP Proxy

O deployment alvo inclui dois containers NGINX distintos na rede rootless `gateway-vpn`. O primeiro
é obrigatório e publica um endpoint compartilhado para todas as aplicações HTTP. O segundo é
exclusivo para desenvolvimento e emula o proxy autenticado de perímetro, como F5 Big-IP. A rede
padrão `podman` é a alternativa rootful. Nenhum deles atende Portainer, Headplane ou Cockpit. Este
contrato define a topologia desejada; não declara que sua implantação ou validação já ocorreu.

## 8.1 Proxy compartilhado das aplicações

Este NGINX recebe as chamadas externas na porta `8080` do host, vinculada ao listener TCP `8080`
do container. É o único endpoint HTTP publicado pelo boilerplate para aplicações e encaminha
requisições por caminho a todas as aplicações configuradas, por exemplo `/app1` e `/app2`.
Cada aplicação declara seus prefixos e upstreams. A aplicação inicial usa `/webapp/` e `/webapp/api/`,
ambos encaminhados ao listener FastAPI `webApp:8000`; avalia a rota da API antes do fallback SPA.
O proxy mantém somente estado de configuração e logs operacionais; não armazena dados de aplicação.

O proxy não armazena dados de aplicação nem autentica usuários. Em produção, o perímetro externo
fornece DNS, TLS e autenticação e encaminha HTTP à porta publicada `8080`. Ele remove ou substitui
headers de identidade enviados pelo cliente e fornece identidade confiável. A aplicação autoriza
esses usuários. A lista de campos `X-USER` e a prova de proveniência permanecem gates obrigatórios.
Rotas protegidas devem falhar fechadas sem identidade confiável; CIDR ou header bruto não provam
autenticação.

Não habilite rate limiting por padrão. Limite uploads a 1 GB por padrão no NGINX e no serviço
TUS. Compartilhamento básico de arquivos é opcional e somente para leitura.

## 8.2 Emulador de proxy autenticado para desenvolvimento

**Status:** a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md).

Este segundo NGINX existe exclusivamente para desenvolvimento e testes. Ele escuta TCP `80` no
container, não publica nem vincula porta no host e recebe chamadas pela rede Podman, inclusive
pela VPN autorizada. Encaminha as chamadas ao listener TCP `8080` do proxy compartilhado das
aplicações. Assim, testa-se o mesmo roteamento por caminho sem criar um endpoint de produção
alternativo.

O emulador substitui o F5 Big-IP somente no ambiente de desenvolvimento: remove valores de
identidade enviados pelo cliente e injeta os campos configurados `X-User-Email`, `X-User-Name`,
`X-User-Groups`, `X-User-Department` e `X-User-Job-Title`. Não implementa login nem autentica
usuários. Esses headers sintéticos não provam identidade e não podem ser usados como autenticação
de produção.

O acesso externo de usuários continua passando pelo perímetro real. O emulador não deve ser
publicado no host nem substituir o perímetro em produção.

## 8.3 Outros serviços

Serviços não HTTP destinados a usuários usam publicação direta, com bind, protocolo e portas
declarados, além de autenticação própria. O acesso de desenvolvimento pela VPN não depende de
portas de aplicação publicadas no host; quando implementado, o acesso HTTP de desenvolvimento usa
o emulador da seção 8.2, a implementar e fora do escopo atual; consulte [TODO.md](../plans/TODO.md).

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 9. Rede Podman e DNS de desenvolvimento

O alvo rootless usa exclusivamente a rede bridge `gateway-vpn` (`10.90.0.0/24`), com backend
Netavark e DNS Aardvark. Não criar redes por aplicação nem recriar automaticamente rede em uso.
O deployment inspeciona a rede e confirma DNS habilitado. A rede padrão rootful `podman` permanece
como alternativa.

Containers podem comunicar-se diretamente; não há isolamento de rede entre aplicações ou banco.
Cada serviço deve aplicar autenticação e autorização próprias. A rede publica somente endereços
IPv4 de serviços; isso não exige desativar IPv6 no host.

O Gateway usa `10.90.0.2` na rede `gateway-vpn`; o resolver Aardvark é `10.90.0.1`. Os outros
containers do alvo rootless usam a mesma rede. Endereços e aliases estão definidos na seção 10.

## 9.1 DNS nativo do Podman

Netavark e Aardvark DNS mantêm o registro dos nomes e aliases dos containers na rede `gateway-vpn` durante seu ciclo de vida. Containers usam o resolver da bridge rootless `10.90.0.1`, sem arquivos manuais de endereços ou banco de registros mantido pelo Gateway.

Não haverá serviço DNS independente para manter registros de containers. O deployment deve
validar nomes curtos, aliases completos e atualização após recriação na versão-alvo.

## 9.2 Nomes e aliases declarados

O deployment declara nomes e aliases estáveis, únicos na rede `gateway-vpn`, nas definições dos
containers. Aliases completos de desenvolvimento usam o sufixo interno `dev.anatel`, por exemplo:

```text
backend.project-a.dev.anatel
frontend.project-a.dev.anatel
backend.project-b.dev.anatel
```

Podman registra esses aliases na rede `gateway-vpn`. Não haverá inventário paralelo `dns_records`
ou watcher customizado. Nomes curtos também devem ser únicos; aliases completos distinguem serviços
de aplicações diferentes. A rede padrão rootful `podman` permanece alternativa.

Consultas externas dos containers seguem os upstreams configurados no Podman. Não configure
encaminhamento circular entre o resolver Podman, o host e o cliente VPN do Gateway.

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

Esses nomes são aliases registrados no DNS nativo da rede rootless `gateway-vpn`. Headscale
distribui split DNS de `dev.anatel` para o resolver Aardvark `10.90.0.1`. Esse endereço pertence
ao CIDR anunciado pelo Gateway; não confunda o resolver/bridge com o container Gateway `10.90.0.2`.

Clientes Tailscale devem aceitar DNS e rotas. A política VPN e as regras do host devem permitir
consultas UDP e TCP 53 ao resolver somente pelas origens autorizadas, com retorno ao prefixo VPN.
Validar consultas remotas a aliases completos e restrições por origem no Aardvark da versão-alvo
é um gate obrigatório. DNS entre containers não comprova que consultas roteadas funcionarão.
Se esse gate falhar, bloquear a aceitação e revisar explicitamente a integração; não instalar
outro DNS nem gerar registros como fallback silencioso.

Outros domínios dos clientes remotos continuam usando seus resolvers locais. Validar essa
integração em Windows 11, Linux e macOS, sem tornar o DNS Podman um resolver público.

MagicDNS nomeia dispositivos inscritos na VPN; não descobre containers atrás do subnet router.
Podman mantém os registros dos containers; o deployment apenas declara seus aliases, conforme a
seção 9.2. Não duplicar esses registros em Headscale.

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

No alvo rootless, o deployment declara endereços estáveis para os containers da webapp. Os aliases
DNS permanecem como nomes de acesso e são atualizados pelo Podman quando containers são recriados.
Outros endereços individuais não constituem identidade permanente.

A rota VPN cobre `10.90.0.0/24` e não depende dos endereços individuais. Caches DNS devem respeitar
os TTLs do resolver.

O desenvolvedor continuará utilizando o mesmo nome lógico.

```text
backend.project-a.dev.anatel
        │
        ▼
   current backend IP
```

## 9.5 Escopo

O DNS Podman cobre os containers da rede rootless `gateway-vpn`. A VPN fornece aos desenvolvedores
acesso roteado a essa rede e ao resolver `10.90.0.1`. Registros DNS não criam conectividade nem
concedem acesso; a rede `podman` é a alternativa rootful.

## 9.6 Serviços publicados no DNS

Podman registra nomes de containers e aliases em `gateway-vpn`; não haverá lista DNS independente
por serviço. Os aliases completos declarados definem os nomes de desenvolvimento. O Gateway e os
clientes autorizados alcançam os serviços configurados, inclusive bancos; cada serviço controla
sua própria autenticação e autorização.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 10. Endereçamento da rede Podman

O alvo rootless usa a rede `gateway-vpn` (`10.90.0.0/24`), com resolver Aardvark
`10.90.0.1` e endereço do Gateway `10.90.0.2`. Headscale usa o prefixo IPv4 `100.96.0.0/24`.
A rota de retorno ao prefixo VPN fica na namespace rootless.

A webapp usa endereços fixos na rede rootless:

| Serviço | Endereço | Alias de desenvolvimento |
| --- | --- | --- |
| `webapp-db` | `10.90.0.10` | `webapp-db.dev.anatel` |
| `webapp` | `10.90.0.11` | `webapp.dev.anatel` |
| `app-proxy` | `10.90.0.12` | `app-proxy.dev.anatel` |

Antes de instalar estado, compare os prefixos rootless e VPN com redes e rotas relevantes do host,
da LAN e do ambiente corporativo. O endpoint Headscale está disponível diretamente em TCP 443 no
host antes de estabelecer a VPN.

A alternativa rootful usa a rede padrão `podman`, com CIDR descoberto por inspeção; o padrão
upstream `10.88.0.0/16` não é garantido. Seus endereços de infraestrutura não devem conflitar com
redes ou rotas existentes.

Referências: [rede padrão e DNS Podman](https://docs.podman.io/en/latest/markdown/podman-network.1.html)
e [inspeção da rede](https://docs.podman.io/en/latest/markdown/podman-network-inspect.1.html).

---



---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 11. Acesso aos containers e VS Code

O desenvolvedor estabelece primeiro a VPN com o cliente Tailscale inscrito no Headscale do Gateway.
SSH e VS Code nos containers estão a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md).
Depois utiliza o DNS e as rotas distribuídos para acessar diretamente os serviços dos containers (SSH, SFTP, HTTP, ODBC etc.)

## 11.1 VS Code Remote - SSH

**Status:** a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md).

O VS Code conecta-se ao nome DNS do container de destino pela rede VPN, sem salto intermediário
de autenticação no Gateway e sem publicar a porta do serviço no host.

```text
Developer / VS Code
   │
   │ Tailscale VPN
   ▼
Gateway tailscaled
   │
   │ IP forwarding
   ▼
Application container
   │
   │ SSH authentication
   ▼
Developer identity
```

## 11.2 Administração do Gateway

Headplane e Portainer administram o Gateway conforme a seção 5.5. O endpoint de bootstrap do
Headscale precisa estar alcançável antes da VPN. Nomes e acesso seguem a seção 9. Recuperação
fora da VPN é responsabilidade da equipe de infraestrutura pelo host.

## 11.3 Credenciais dos destinos

Cada desenvolvedor possui chaves SSH individuais para os containers que exigirem esse protocolo.
Chaves privadas permanecem no equipamento do desenvolvedor e não são compartilhadas.
O deployment recebe somente chaves públicas, em arquivos externos ao Git, root-managed, montados
somente para leitura no destino e configurados por conta não-root.

O caminho padrão no host é `/etc/gateway/application-keys/<container>/authorized_keys`; o caminho
efetivo deve ser configurável no JSON. Use `root:root` e modo `0600`, com montagem somente leitura
em `/home/<account>/.ssh/authorized_keys`. O bootstrap deve validar que a conta consegue ler o
arquivo sem ampliar permissões indevidamente. A autenticação do serviço permanece independente
da autenticação VPN.

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 12. Volumes

Volumes persistentes devem ser utilizados para:

- PostgreSQL;
- banco e identidade do Headscale, estado do `tailscaled` e dados/sessões do Headplane;
- dados do Portainer em volume dedicado montado em `/data`;
- dados que precisem sobreviver à recriação do container;
- configurações persistentes, quando necessário.

Containers devem ser considerados descartáveis.

A criação inicial de volumes que exigir intervenção privilegiada no host pode ser realizada pelo administrador do RHEL.

O boilerplate deve documentar claramente quais volumes são obrigatórios.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 13. Configuração e secrets

Não armazenar secrets diretamente no Git.

A configuração deve distinguir:

## Versionada

- nomes dos serviços;
- vínculo à rede padrão e nomes dos containers conforme a seção 9;
- portas;
- configuração estrutural;
- templates;
- deployment scripts;
- definição dos caminhos esperados para secrets no host.

## Externa

- senhas;
- tokens;
- chaves;
- certificados privados;
- credenciais de produção;
- arquivos `.env` contendo secrets.

## 13.1 Armazenamento dos secrets

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

## 13.2 Mapeamento para containers

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

## 13.3 Deployment de secrets

As ferramentas de deployment deverão:

1. criar os diretórios necessários no host;
2. validar sua existência e permissões;
3. documentar os arquivos esperados;
4. configurar os mapeamentos dos secrets;
5. montar os arquivos nos containers em modo somente leitura;
6. impedir que secrets sejam incorporados às imagens;
7. impedir que secrets sejam incluídos no Git.

O conteúdo dos secrets não deverá ser gerado automaticamente pelo Git ou armazenado no repositório.

## 13.4 Evolução futura

A arquitetura deverá permitir que o armazenamento local em arquivos seja posteriormente substituído por um Secret Manager ou integração corporativa.

Essa integração não faz parte do boilerplate inicial.

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 14. Deployment

O repositório deve conter scripts para:

1. validar pré-requisitos do host e a rede rootless `gateway-vpn`; adequar `config/host_config.json` ao alvo rootless; a rede padrão `podman` é a alternativa rootful;
2. executar verificações e configurações específicas somente para os serviços declarados/ativados no arquivo;
3. criar a estrutura de diretórios, volumes e secrets sem sobrescrever dados existentes;
4. validar `gateway-vpn` conforme os requisitos da seção 9, sem recriar rede em uso;
5. construir/atualizar containers através de Quadlet;
6. conectar containers rootless somente a `gateway-vpn`, reservando `10.90.0.2` para o Gateway;
7. declarar nomes e aliases conforme a seção 9;
8. provisionar Headscale, Headplane e `tailscaled`, anunciar/aprovar somente `10.90.0.0/24` e instalar a rota de retorno na namespace rootless sem SNAT;
9. implantar o NGINX compartilhado obrigatório, publicando host TCP/8080 no container TCP/8080; o emulador de desenvolvimento está a implementar, fora do escopo atual, conforme [TODO.md](../plans/TODO.md);
10. carregar chaves públicas SSH dos arquivos seguros no host somente para containers de aplicação habilitados; SSH está a implementar, fora do escopo atual, conforme [TODO.md](../plans/TODO.md);
11. iniciar serviços em ordem, verificar saúde e testar conexões remotas;
12. apresentar estado, logs, recursos alterados e instruções de recuperação;
13. agendar no host full mensal e incremental semanal por PostgreSQL; executar pgBackRest no container como `postgres`, publicar somente gerações completas verificadas em volume host separado e fornecer restore manual validado.
14. implantar Portainer na rede padrão com volume persistente, socket Podman local exclusivo, HTTPS restrito à VPN e bootstrap administrativo protegido; validar compatibilidade sem `--privileged` e sem disputar o ciclo de vida Quadlet.

O preflight deve confirmar SELinux desativado sem alterar essa configuração. O egress rootless usa o caminho normal do Podman no host; a alternativa rootful pode usar masquerading.

O deployment deve ser idempotente sempre que possível.

Executar o deployment novamente não deve destruir dados persistentes ou secrets existentes.

O deployment deverá ser capaz de reproduzir a configuração estrutural do ambiente sem exigir acesso manual aos containers.

## 14.1 Bootstrap de acesso

A configuração inicial provisiona identidade e estado persistente do Headscale, inscrição do
subnet router, credenciais administrativas do Headplane e política de acesso. O operador de
infraestrutura cria o primeiro acesso administrativo localmente; a interface de gestão permanece
restrita à VPN após o bootstrap. Não armazene tokens no JSON versionado nem os exponha em logs.

As chaves de inscrição de dispositivos são gerenciadas pelo Headscale/Headplane e não substituem
credenciais dos serviços. O bootstrap também pode receber chaves públicas SSH para os containers
de aplicação habilitados. Chaves privadas dos desenvolvedores nunca são copiadas pelo deployment.

As chaves públicas serão lidas de arquivos fora do Git, com propriedade e permissões restritas no host. A auditoria do host registra alterações nos arquivos; PAM e logs de sessão dos operadores são controles externos e não fazem parte do deployment do boilerplate.

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 15. Manutenção

A manutenção normal das aplicações deve ser possível sem acesso ao host RHEL. A equipe de
infraestrutura administra o servidor pelo Cockpit instalado no host, conforme a seção 2.2,
independentemente dos componentes containerizados.

Ferramentas principais:

- Portainer para inspeção, logs e operações de containers compatíveis com Quadlet;
- Headplane para administração da VPN;
- SSH aos containers de aplicação pela VPN (a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md));
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

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 16. Diagnóstico

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

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 17. Observabilidade

O boilerplate deve permitir pelo menos:

- estado dos containers;
- logs;
- consumo básico de CPU/memória;
- estado da rede padrão e do DNS Podman;
- estado do gateway;
- saúde do Headscale, Headplane e `tailscaled`, dispositivos inscritos e rotas anunciadas/aprovadas;
- eventos de inscrição, expiração e revogação, sem tokens nem chaves privadas.

Observabilidade avançada não faz parte da primeira versão.

Integrações futuras podem incluir:

- Prometheus;
- Grafana;
- Zabbix;
- OpenTelemetry;
- outros sistemas corporativos.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 18. Estrutura lógica do repositório

A estrutura final deverá separar claramente:

```text
repository/
├── deploy/
│   ├── gateway/
│   ├── scripts/
│   └── webapp/
├── webapp/
│   ├── backend/
│   ├── database/
│   └── frontend/
├── docs/
│   ├── images/
│   └── recipes/       # Procedimentos para pessoas
├── .agent/
│   ├── README.md
│   ├── contracts/     # Requisitos normativos e critérios de aceitação
│   ├── memory/        # Memória durável e histórico de execução concluída
│   └── plans/         # Planos de implementação e validação planejada/ativa
└── .github/
    ├── agents/
    ├── instructions/
    └── skills/
```

A estrutura exata poderá ser ajustada durante a implementação, mas as responsabilidades devem permanecer separadas.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 19. Regras para desenvolvimento no VS Code

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

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 20. Desenvolvimento versus produção

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
- separação entre Development Gateway, proxy compartilhado obrigatório e emulador NGINX de desenvolvimento;
- rede Podman padrão única, DNS nativo e autenticação por serviço;
- mecanismo geral de deployment;
- modelo de acesso aos containers.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 21. Princípios de segurança

Mesmo com o controle de acesso externo, devem ser mantidos os seguintes princípios:

1. menor privilégio possível;
2. SELinux desativado por decisão explícita; o deployment não altera a política do host;
3. nenhum acesso desnecessário ao host;
4. Podman socket não exposto por TCP;
5. secrets fora do Git;
6. containers com filesystem mínimo;
7. evitar `--privileged`;
8. capabilities específicas quando possível;
9. conectividade direta intencional entre todos os containers na rede padrão; autenticação e autorização obrigatórias nos serviços, sem alegar isolamento por aplicação;
10. PostgreSQL não exposto externamente;
11. Gateway não utilizado para servir tráfego de usuários;
12. Proxy HTTP não utilizado como canal administrativo;
13. autenticação VPN por dispositivo e autenticação individual nos serviços de destino;
14. chaves privadas dos dispositivos geradas e mantidas localmente pelo cliente; tokens de inscrição
    de uso único e curta validade, sem logs; credenciais e estado do Gateway persistidos com proteção;
15. secrets de aplicação fora do Git;
16. secrets montados somente onde necessários e em modo somente leitura;
17. imagens versionadas e atualizadas.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 22. Decisões arquiteturais já estabelecidas

As seguintes decisões são consideradas parte do contrato:

| Decisão | Escolha |
|---|---|
| Alvo de qualificação do host | RHEL 9.8, Podman rootless 5.8.2, SELinux desativado; rootful mantido como alternativa |
| Runtime de containers | Podman 5.8.2 rootless como alvo; rootful como alternativa implementada e mantida |
| Imagens de containers | Distribuição Linux eficiente e mantida; preferir Debian ou Alpine |
| Ciclo de vida dos containers | Quadlet para containers persistentes |
| Podman mode | Rootless como alvo; rootful como alternativa |
| Backend | Python + FastAPI |
| Frontend | Vite com JavaScript sem framework por padrão; HTML/JS estático para páginas pequenas |
| Rota frontend/API | `/webapp/` e `/webapp/api/<route>` no mesmo domínio |
| Database | PostgreSQL 18 por padrão, versão configurável por instância |
| Stack inicial da aplicação | `webApp` combina assets SPA e FastAPI em um listener TCP `8000`; PostgreSQL permanece separado |
| Gateway | Um único container compartilhado |
| Gateway por aplicação | Não |
| Gestão de containers | Portainer em container dedicado na rede padrão, restrito a operadores pela VPN; implementação pendente |
| Integração Portainer | API compatível com Docker pelo socket Unix rootful local, montado somente no Portainer; sem Agent no ambiente local |
| Estado Portainer | Volume persistente em `/data`, backup protegido e bootstrap administrativo restrito |
| Fonte de deployment | Quadlet e scripts versionados; Portainer não cria stacks concorrentes nem substitui a gestão do host |
| Gestão geral do host | Cockpit instalado diretamente no RHEL pela infraestrutura; serviço independente dos containers |
| Acesso ao Cockpit | HTTPS no endereço administrativo do host, TCP `9090` por padrão, restrito à infraestrutura e aos controles corporativos; independente da VPN de desenvolvimento |
| Limite do Cockpit | Gestão do servidor, sem `cockpit-podman`; Portainer permanece a interface de containers e Quadlet a autoridade de deployment |
| Headscale | Servidor de coordenação auto-hospedado dentro do Gateway; implementação pendente |
| Endpoint de controle e VPN | TCP 443 publicado diretamente no host; Headscale e VPN usam o mesmo endpoint LAN |
| Headplane | Interface administrativa VPN dentro do Gateway, restrita a operadores |
| Daemon VPN | `tailscaled` no Gateway em modo kernel, atuando como subnet router |
| Proxy HTTP | NGINX compartilhado obrigatório; emulador exclusivo de desenvolvimento a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md) |
| Configuração mínima | Host, Gateway, Portainer e NGINX compartilhado; emulador de desenvolvimento a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md) |
| Porta do proxy de aplicações | Bind selecionado `0.0.0.0:8080`, mapeado ao TCP 8080 do container NGINX compartilhado |
| Emulador de autenticação | Container NGINX exclusivo para desenvolvimento, listener TCP 80 sem bind no host, encaminhando ao proxy compartilhado em TCP 8080; a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md) |
| Identidade HTTP | Perímetro real autentica em produção; emulador de headers sintéticos a implementar, fora do escopo atual; aplicação autoriza; consulte [TODO.md](../plans/TODO.md) |
| Autorização HTTP | Gate de deployment exige restrição efetiva ao perímetro confiável ou proveniência verificada; lista exata de campos e mecanismo permanecem pré-requisitos |
| DNS e nomes | Requisitos internos e externos, incluindo split DNS, definidos na seção 9 |
| Rede de containers | Somente `gateway-vpn` (`10.90.0.0/24`) no alvo rootless; rede padrão `podman` na alternativa rootful |
| Interface Podman do Gateway | Uma interface em `gateway-vpn`, endereço `10.90.0.2`; resolver Aardvark `10.90.0.1` |
| Acesso do Gateway | A todos os serviços em `gateway-vpn`; componente administrativo confiável |
| Configuração de rede | Adequar `config/host_config.json` à rede rootless `gateway-vpn`, sem inventário por aplicação; rede padrão `podman` é alternativa rootful |
| CIDR de containers | Alvo rootless fixo `10.90.0.0/24`; alternativa rootful descobre a rede `podman` por inspeção (`10.88.0.0/16` é padrão upstream, não garantido) |
| Endereços fixos da webapp rootless | `10.90.0.10` `webapp-db`; `10.90.0.11` `webapp`; `10.90.0.12` `app-proxy` |
| Acesso remoto | Clientes Tailscale inscritos no Headscale; split tunnel IPv4 para `10.90.0.0/24`, prefixo VPN `100.96.0.0/24`, sem SNAT; origem VPN e default route preservadas |
| Inscrição | Headplane gerencia usuários/dispositivos e tokens de uso único; chaves privadas geradas nos clientes; OIDC corporativo opcional |
| Retorno da VPN | `--snat-subnet-routes=false` e rota determinística ao prefixo VPN na namespace rootless |
| Egress de containers | Saída normal do Podman rootless pelo host; alternativa rootful pode usar masquerading |
| SSH para aplicações | Conexão direta ao destino pela VPN para VS Code; autenticação no container, sem bastion; a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md) |
| Administração do Gateway | Headplane para VPN e Portainer para gestão do container pela VPN; sem listener de shell para desenvolvedores |
| Bind de gestão | Headplane atrás de frontend HTTPS no Gateway; Portainer HTTPS no container dedicado, sem publicação no host; ingresso restrito à VPN e a operadores |
| Chaves SSH dos destinos | Individuais por desenvolvedor, privadas somente no cliente, públicas provisionadas por destino; a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md) |
| Controle de acesso | Perímetro externo mais inscrição e política Headscale; autenticação de serviço independente |
| Podman API | Socket Unix local exclusivo do Portainer; acesso de alto privilégio, sem exposição TCP |
| Acesso diário ao host | Não |
| Deployment | Scripts versionados e Quadlet; preflight comum e verificações específicas por serviço |
| SSH key bootstrap | Chaves públicas de arquivos root-owned; host audit registra alterações; PAM externo; a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md) |
| Backup PostgreSQL | pgBackRest versionado na imagem; full mensal/incremental semanal por timers host; repositório de trabalho e exportações concluídas em volumes distintos; publicação de geração completa verificada; restore manual com drill; plano, não implementado |
| TUS e file sharing | Serviços opcionais; limite de arquivo de 1 GB por padrão; file sharing NGINX somente leitura |
| Serviços não HTTP para usuários | Publicação direta por bind de host, protocolo e portas explicitamente declarados; autenticação do serviço e perímetro próprios |
| Acesso developer aos containers | Gateway alcança serviços/portas sem publicação de portas de aplicação; endpoints VPN têm publicação própria |
| NGINX rate limit | Desativado por padrão |
| Limite de body NGINX | 1 GB por padrão; configurável |
| Configuração | `schema_version: 1` atual; preservar seções não relacionadas e adequar explicitamente rede única, DNS nativo e acesso remoto |
| Application secrets | Fora do Git |
| Secret storage inicial | Arquivos no host |
| Secret mapping | Somente leitura e apenas para containers necessários |
| Secret Manager | Integração futura, fora do boilerplate inicial |
| Bootstrap sem aplicações | Gateway pode iniciar sem containers de aplicação; VPN exige identidade/estado, configuração válida e endpoints alcançáveis; primeiro acesso administrativo provisionado localmente |

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 23. Restrições de implementação

As decisões de topologia confirmadas estão registradas na seção 22. Os inputs operacionais e as
verificações planejadas ficam no [plano de inputs e gates de implementação](../plans/architecture-implementation.md).
Os critérios normativos de aceitação permanecem na seção 24 e nas demais seções aplicáveis do contrato.

A identidade de rotas protegidas exige campos `X-USER` aprovados e proveniência perímetro-aplicação
verificável. Não adicionar nomes de campos nem tratar CIDR ou header bruto como autenticação.
Mudanças de schema e configuração devem preservar compatibilidade das seções não relacionadas e
validar explicitamente campos substituídos; não presumir suporte do validador atual a campos novos.

SELinux desativado é uma decisão de segurança explícita. O deployment valida o estado, mas não
altera a política do host.

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 24. Critérios de aceitação arquitetural

Uma implementação do boilerplate será considerada aderente quando:

- uma aplicação puder ser implantada sem alterar manualmente o host na operação normal;
- containers do alvo usarem somente a rede rootless `gateway-vpn` (`10.90.0.0/24`); a rede padrão `podman` fica como alternativa rootful;
- conectividade direta entre containers ser intencional e protegida por autenticação de serviço, sem alegar isolamento por aplicação;
- configuração de serviços e aliases estiver declarada, sem inventário de redes por aplicação;
- Gateway possuir `10.90.0.2` em `gateway-vpn` e anunciar somente `10.90.0.0/24`;
- deployment e testes de DNS em `gateway-vpn` cumprirem integralmente a seção 9, sem recriar rede em uso;
- webapp usar endereços fixos `10.90.0.10` (`webapp-db`), `10.90.0.11` (`webapp`) e `10.90.0.12` (`app-proxy`);
- uma nova aplicação puder ser adicionada sem criar outro gateway;
- desenvolvedores puderem acessar containers por SSH/VS Code diretamente pela VPN Tailscale coordenada pelo Headscale (a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md));
- o gateway realizar forwarding sem substituir a autenticação SSH do container de aplicação (a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md));
- NGINX compartilhado receber todas as aplicações por um endpoint host `0.0.0.0:8080`, mapeado ao TCP/8080 do container;
- cada aplicação HTTP puder ser encaminhada por um prefixo de caminho, como `/app1` ou `/app2`, sem exigir outra porta publicada;
- o emulador NGINX de desenvolvimento escutar TCP/80 sem bind no host, injetar headers sintéticos e encaminhar ao proxy compartilhado em TCP/8080 (a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md));
- NGINX encaminhar, para a aplicação inicial, `/webapp/` e `/webapp/api/<route>` ao mesmo listener FastAPI `webApp:8000`, preservando o prefixo, sem restringir outras aplicações aos mesmos upstreams/portas;
- FastAPI servir, na aplicação inicial, a SPA em `/webapp/` e a API em `/webapp/api/` no único listener TCP `8000`;
- o perímetro autenticar usuários e fornecer identidade `X-USER` confiável, e a aplicação autorizar usuários sem atribuir autenticação ao NGINX;
- rotas protegidas falharem fechadas quando a identidade estiver ausente/não confiável e deployment aplicar o gate de perímetro/proveniência;
- serviços não HTTP de usuário usarem publicação direta explicitamente configurada, sem confundir isso com o acesso de desenvolvimento via Gateway;
- Headscale, Headplane e `tailscaled` executarem no Gateway como única solução de acesso remoto de desenvolvedores;
- clientes inscritos alcançarem `10.90.0.0/24`, inclusive PostgreSQL, por split tunnel IPv4 sem SNAT, preservando endereço VPN de origem e rota default local;
- `--snat-subnet-routes=false` e rota de retorno determinística na namespace rootless permitirem respostas aos dispositivos VPN;
- inscrição via Headplane usar tokens individuais de uso único e curta validade, sem distribuição de chaves privadas de dispositivos;
- expirar token não ser tratado como revogação de dispositivo; testar expiração/revogação do dispositivo, auditoria e bloqueio de novos acessos;
- prefixo VPN `100.96.0.0/24` não se sobrepor a `10.90.0.0/24` nem às redes/rotas relevantes do host, LAN e ambiente corporativo;
- anúncio, aprovação e aceitação de `10.90.0.0/24` funcionarem sem anunciar rota default nem aceitar rotas da alternativa rootful no próprio Gateway;
- endpoint Headscale estar disponível diretamente em TCP 443 antes da VPN e conectividade direta/relay funcionar conforme política de infraestrutura;
- endpoints administrativos dos containers exigirem autenticação e acesso de operador pela VPN, sem API administrativa pública nem socket Podman no Headplane; Cockpit do host usar o acesso corporativo independente da seção 2.2;
- reinícios preservarem identidades e inscrições; falhas dos processos serem explícitas, com comportamento de reconexão e recuperação validado;
- candidatos inválidos não mutarem estado e rotas/regras terem ownership, reconciliação idempotente e rollback definidos;
- não haver DHCP para clientes VPN, extensão Ethernet da rede de containers aos clientes ou TAP;
- egress rootless alcançar destinos externos pela saída normal do Podman no host; a alternativa rootful pode usar masquerading;
- deployment rootless usar Quadlet e passar aceitação em RHEL 9.8 / Podman 5.8.2 com SELinux desativado; rootful permanece alternativa;
- chaves públicas individuais puderem ser provisionadas pelo bootstrap do deployment (a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md));
- chaves públicas forem lidas de arquivos root-owned no host e alterações forem registradas pela auditoria existente (a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md)); PAM permanece responsabilidade externa;
- o Gateway não oferecer listener de shell ou transporte alternativo para acesso remoto de desenvolvedores;
- Portainer permitir as operações de containers aprovadas, via API compatível com Docker e socket local, no alvo RHEL 9.8 / Podman 5.8.2, sem `--privileged`; falha de compatibilidade bloqueia aceitação;
- somente Portainer receber o socket Podman, com acesso restrito a operadores confiáveis e sem exposição TCP da API;
- Portainer não substituir Quadlet nem criar stacks ou configuração estrutural concorrente; validar efeitos das operações na política de reinício systemd;
- dados em `/data` sobreviverem à recriação do Portainer, com backup/restore e bootstrap administrativo protegido;
- indisponibilidade do Portainer não interromper aplicações, VPN ou DNS, e sua interface HTTPS não permitir ingresso não autorizado pela VPN ou bridge;
- Cockpit executar diretamente no host, com HTTPS, autenticação e privilégios corporativos, restrito à infraestrutura e sem dependência dos containers, do Gateway ou da VPN de desenvolvimento;
- acesso administrativo ao Cockpit permanecer funcional com o Gateway parado, sem expor sua porta publicamente nem disponibilizar outro canal de desenvolvedores;
- Cockpit não instalar gestão concorrente de containers, não substituir Quadlet e sua indisponibilidade não interromper aplicações, VPN ou DNS;
- Podman API não estiver exposto desnecessariamente;
- PostgreSQL possuir armazenamento persistente;
- PostgreSQL 18 possuir armazenamento persistente e plano de backup pgBackRest com full mensal/incremental semanal, volumes de trabalho/exportação distintos, publicação íntegra e restore manual testado; esses campos e operações ainda não são suportados pelo runtime;
- somente o processo FastAPI possuir credenciais PostgreSQL dentro do container combinado `webApp`;
- TUS e file sharing NGINX serem recursos opcionais; uploads terem limite configurável de 1 GB por padrão e file sharing ser somente leitura;
- seções não relacionadas do JSON permanecerem compatíveis com `schema_version: 1`; rede, DNS e acesso remoto seguem validação definida nas seções 5.5 e 9;
- os dois NGINX funcionarem como proxies HTTP distintos: o compartilhado obrigatório para aplicações e o emulador exclusivo para desenvolvimento (a implementar, fora do escopo atual; consulte [TODO.md](../plans/TODO.md)); nenhum deles servir tráfego administrativo;
- o acesso externo continuar controlado pela infraestrutura de segurança existente;
- deployment puder ser repetido sem destruir dados;
- diagnóstico básico de rede puder ser realizado sem acesso ao host RHEL;
- o deployment validar que SELinux já está desativado sem alterar essa configuração.
- configuração estrutural estiver versionada;
- secrets não estiverem no Git.

---

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>

# 25. Regra de evolução

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

<div>
  <a href="#top" title="De volta ao topo da página"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
    <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
  </picture></a><br><br>
</div>
