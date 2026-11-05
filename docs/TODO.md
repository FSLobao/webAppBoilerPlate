<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#pendências-de-implementação">Pendências de implementação</a></li>
        <li><a href="#workarounds-rootless-a-substituir">Workarounds rootless a substituir</a></li>
        <li><a href="#diferenças-do-contrato-registradas-na-g10">Diferenças do contrato registradas na G10</a></li>
        <li><a href="#segurança-e-dev">Segurança e dev</a></li>
        <li><a href="#qualidade-do-script-de-deploy-rootless">Qualidade do script de deploy rootless</a></li>
        <li><a href="#operação">Operação</a></li>
        <li><a href="#registros-do-alvo-rootless">Registros do alvo rootless</a></li>
    </ol>
</details>

# Pendências e registros

Registro de pendências, riscos e diferenças históricas da revisão G10 e do alvo rootless.

## Pendências de implementação

- **Emulador de identidade (§8.2 do contrato): a implementar; fora do escopo.** O fluxo HTTP testado usa `app-proxy.dev.anatel`; não presume o emulador. Consulte [ARCHITECTURE.md](contracts/ARCHITECTURE.md) e a [receita do cliente VPN](recipes/gateway-vpn-client.md).
- **SSH em containers (§9 da receita do cliente; §11 do contrato): a implementar; fora do escopo.** O túnel VPN não implementa nem autentica sessões SSH ou VS Code. Consulte [ARCHITECTURE.md](contracts/ARCHITECTURE.md) e a [receita do cliente VPN](recipes/gateway-vpn-client.md).

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Workarounds rootless a substituir

Lista parcial. Os workarounds de laboratório estão detalhados no [histórico de execuções de laboratório](plans/historico-execucoes-laboratorio.md#desvios-temporários-usados-no-teste). São somente rootless e test-only.

- **(a) Healthcheck — `30-healthcheck-rootless.conf`:** o script compartilhado deve fazer leituras UID-aware de `/proc/<pid>/exe` para cada serviço; substituir a montagem local por essa correção compartilhada.
- **(b) Runtime Headscale — `20-headscale-runtime.conf`:** definir `/run/headscale` e permissões na imagem ou no Quadlet; substituir o bind do diretório local.
- **(c) CA — `50-lab-ca-bundle.conf`:** fornecer aos containers uma CA aprovada pela infraestrutura; substituir o bundle montado do laboratório.
- **(d) DNS do control server — `40-control-host.conf`:** a infraestrutura deve fornecer um nome DNS estável do Headscale; substituir `AddHost=headscale.dev.anatel:192.168.7.160`.
- **(e) Nome do nó Gateway:** o nome deriva do ID do container; `tailscale status` no cliente em 2026-11-05 mostrou a mudança de `554ad3114093` para `35085f0529a0` após recriação/reinício do container. Definir `HostName=` no Quadlet está a verificar.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Diferenças do contrato registradas na G10

- **Rede e modo do Podman — histórico:** a revisão anterior exigia a rede padrão rootful `podman`; os testes usaram `gateway-vpn` (`10.90.0.0/24`). O contrato vigente define rootless como alvo e rootful como alternativa.
- **Endereços de aplicações — histórico:** a redação anterior tratava IPs como não permanentes; o contrato vigente fixa `10.90.0.10` (`webapp-db`), `10.90.0.11` (`webapp`) e `10.90.0.12` (`app-proxy`).
- **Emulador de identidade:** permanece a implementar, fora do escopo atual; consulte [ARCHITECTURE.md](contracts/ARCHITECTURE.md) e a pendência abaixo.
- **SSH em containers:** SSH/VS Code continuam a implementar e fora do escopo atual (§11 e critérios de aceitação); consulte [ARCHITECTURE.md](contracts/ARCHITECTURE.md) e a pendência abaixo.
- **Firewall do host — histórico:** `firewalld` estava ativo antes da preparação; o script da etapa 1 desativa `firewalld` e `nftables` quando presentes, e ambos estão desativados no host testado.
- **G8 — histórico:** Headscale foi testado inicialmente em `:8443`; Headplane e o endpoint de controle/VPN foram depois testados em TCP 443 pela LAN e VPN. O ingresso WAN/perímetro externo continua sem teste.

Os caminhos HTTP `/webapp/` e `/webapp/api/` foram alinhados no contrato nesta revisão; preserve esse registro histórico.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Segurança e dev

- A chave privada `/root/gateway-cockpit-ca/gateway-dev-ca.key` ainda existe no servidor. Foi aceita temporariamente para desenvolvimento até a solução ficar estável; depois, gerar novas chaves seguindo estritamente a receita.
- Rotacionar a senha inicial da conta `podman_user` (nome antigo `gwvpn`, se ainda existir) e excluir o `.env` da raiz do repositório.
- **Pendente ao remover o `.env` local após armazenar a credencial:** renomear `GWVPN_INITIAL_PASSWORD` para `GATEWAY_INITIAL_PASSWORD` e rotacionar a senha.
- Podman publica TCP `8080` em `0.0.0.0`; revisar a exposição e os controles de perímetro.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Qualidade do script de deploy rootless

Não há testes focados de comportamento no repositório. Itens não bloqueantes apontados pelo reviewer:

- validar o kube não mapeado antes de qualquer mutação;
- executar `verify_no_etc_path` no arquivo staged antes do move;
- derivar a lista de arquivos obrigatórios de `DEPLOYMENT_MAP`;
- mesclar braços `hostPath` duplicados;
- emitir mensagem de falha para o split de attachment;
- um pull novamente da mesma tag PostgreSQL não reinicia `webapp-db`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Operação

- `apt-get` no build atingiu cerca de 16 GB de RSS e foi morto pelo OOM killer em 2026-11-04; manter margem de memória.
- Uma indisponibilidade do mirror Debian snapshot causou uma falha de build.
- O script de deploy rootless do Gateway não foi criado; o Gateway foi construído manualmente. Ele é distinto de `deploy/scripts/deploy-webapp-rootless.sh`.
- `deploy/scripts/deploy-webapp.sh` e `deploy/scripts/deploy-webapp-rootless.sh` não devem operar no mesmo host ao mesmo tempo.
- Alterações não commitadas em `webapp/frontend/` não entram no deployment, que usa o `HEAD` commitado como origem.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Registros do alvo rootless

- **(a) Deploy do Gateway rootless como código**, incluindo `deploy-gateway-rootless.sh`, arquivos rootless do Gateway e fluxo de inscrição. **Status:** pendente. **Responsável:** equipe de implementação de deployment.
- **(b) Testes de chave de uso único:** rejeitar reutilização e chave expirada. **Status:** pendente. **Responsável:** equipe de testes e segurança VPN.
- **(c) CA e confiança de produção:** obter a cadeia da infraestrutura; não usar bundle combinado. **Status:** pendente. **Responsável:** infraestrutura e segurança.
- **(d) Procedimento de backup e restore** dos volumes do Gateway, banco da webapp e imagens. **Status:** pendente. **Responsável:** equipe de operação e backup.
- **(e) Runbook de upgrade e rollback:** upgrades do Podman e rollback de imagens e unidades. **Status:** pendente. **Responsável:** equipe de operação.
- **(f) Seções 15 a 17 do contrato** (manutenção, diagnóstico e observabilidade) não avaliadas para rootless. **Status:** pendente. **Responsável:** responsáveis pelo contrato arquitetural.
- **(g) Testes de comportamento** para `deploy-webapp-rootless.sh` e `prepare-rootless-host.sh`; o repositório não tem harness de testes. **Status:** pendente. **Responsável:** mantenedores dos scripts.
- **(h) Fixar digests das imagens-base:** PostgreSQL, NGINX, Python e snapshot Debian. **Status:** pendente. **Responsável:** mantenedores das imagens.
- **(i) Procedimentos de cliente Windows 11 e macOS** ainda não testados. **Status:** pendente. **Responsável:** equipe de suporte a clientes.
- **(j) Revogação de nós e offboarding** ainda não testados. **Status:** pendente. **Responsável:** operadores do Headscale.
- **(k) Nome do nó Gateway após recriação de container:** definir `HostName=` no Quadlet. **Status:** pendente. **Responsável:** mantenedores do Gateway.
- **(l) O nó Gateway conecta pelo relay DERP de Madrid; UDP direto não foi estabelecido a partir do container. Observar, sem alterar.** **Status:** observação. **Responsável:** equipe de rede.
- **(m) Smoke test rootless da webapp** (`smoke-test-webapp.sh`) não executado. **Status:** pendente. **Responsável:** equipe de QA da webapp.
- **(n) Impedir deploy rootful e rootless simultâneos no mesmo host:** adicionar guarda de preflight. **Status:** pendente. **Responsável:** mantenedores dos scripts de deploy.
- **(o) Exceção de origem LAN:** `rootlessport` entrega solicitações LAN ao NGINX com origem `10.90.0.2` e oculta o cliente; o contrato exige preservação da origem somente no caminho VPN. Documentar essa exceção. **Status:** observação. **Responsável:** responsáveis pela arquitetura e documentação.
- **(p) RISCO ACEITO:** Cockpit escuta TCP 9090 pelo socket systemd e agora é alcançável pela LAN com o firewall desativado; o usuário decidiu manter Cockpit como está. **Status:** risco aceito. **Responsável:** equipe de infraestrutura do host.
- **(q) RISCO ACEITO:** `net.ipv4.ip_unprivileged_port_start=443` permite a qualquer usuário não privilegiado vincular portas 443 a 1023. **Status:** risco aceito pelo usuário. **Responsável:** equipe de infraestrutura do host.
- **(r) RISCO ACEITO temporariamente:** chave privada de CA `/root/gateway-cockpit-ca/gateway-dev-ca.key` no host Gateway para desenvolvimento até a solução estabilizar; depois, gerar novas chaves seguindo estritamente a receita. **Status:** risco aceito temporariamente. **Responsável:** responsável pela CA e equipe de infraestrutura.
- **(s) Credenciais locais:** rotacionar a senha inicial de `podman_user` e excluir o `.env` da raiz; ao remover a variável, renomear `GWVPN_INITIAL_PASSWORD`. **Status:** pendente. **Responsável:** administrador da conta e responsável pelo repositório.
- **(t) Tags locais `gate/*`:** decidir se devem ser enviadas ao remoto. **Status:** pendente. **Responsável:** responsável pelo repositório.
- **(u) Workarounds de laboratório rootless:** substituir montagem do healthcheck, bind de `/run/headscale`, bundle de CA combinado e `AddHost`. Manter os itens existentes em [Workarounds rootless a substituir](#workarounds-rootless-a-substituir). **Status:** pendente. **Responsável:** mantenedores do Gateway e da imagem.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
