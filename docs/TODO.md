<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#pendências-de-implementação">Pendências de implementação</a></li>
        <li><a href="#workarounds-rootless-a-substituir">Workarounds rootless a substituir</a></li>
        <li><a href="#conflitos-de-contrato-a-revisar-na-g10">Conflitos de contrato a revisar na G10</a></li>
        <li><a href="#segurança-e-dev">Segurança e dev</a></li>
        <li><a href="#qualidade-do-script-de-deploy-rootless">Qualidade do script de deploy rootless</a></li>
        <li><a href="#operação">Operação</a></li>
    </ol>
</details>

# Pendências e registros

Registro de itens fora do escopo atual, diferenças observadas e trabalho para a revisão G10.

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

Lista parcial. Os workarounds de laboratório estão detalhados na seção [Desvios de teste temporários](recipes/gateway-headscale-podman-rootless.md#desvios-de-teste-temporários). São somente rootless e test-only.

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

## Conflitos de contrato a revisar na G10

- **Rede e modo do Podman:** o contrato exige containers na rede padrão rootful `podman`; os pods webapp testados usam a bridge rootless `gateway-vpn` (`10.90.0.0/24`). O deploy rootful permanece a referência.
- **Endereços de aplicações:** §§9.4 e 10 tratam IPs individuais de containers como não permanentes; a webapp testada usa IPs fixos `10.90.0.10`, `.11` e `.12` com aliases de desenvolvimento.
- **Emulador de identidade:** o contrato prevê o emulador em §8.2 e nas decisões/gates; permanece a implementar e fora do escopo atual.
- **SSH em containers:** o contrato descreve SSH/VS Code como capacidade esperada (§11 e critérios de aceitação); permanece a implementar e fora do escopo atual.
- **Firewall do host:** §5.4 do contrato diz que `firewalld` e `nftables` ficam desativados; `firewalld` está ativo no servidor testado.
- **G8 externo:** o encaminhamento externo TCP 443 ainda não foi testado. O teste de Headscale em `:8443` foi direto pela LAN.

Os caminhos HTTP `/webapp/` e `/webapp/api/` foram alinhados no contrato nesta revisão; não permanecem como conflito aberto.

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
