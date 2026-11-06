<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#gateway-vpn-rootless">Gateway VPN rootless</a></li>
        <li><a href="#cliente-vpn">Cliente VPN</a></li>
        <li><a href="#gateway-rootful">Gateway rootful</a></li>
        <li><a href="#design-system-govbr">Design System GOV.BR</a></li>
        <li><a href="#validação-da-webapp">Validação da webapp</a></li>
    </ol>
</details>

# Histórico de execuções de laboratório

Este arquivo registra evidências históricas de laboratório e pesquisa. Não substitui os
procedimentos das receitas nem define resultados esperados para novas execuções. Argumentos
e resultados ausentes nos registros permanecem desconhecidos; não os infira.

## Gateway VPN rootless

Registros de 2026-10-29 e 2026-11-05. Fonte: conteúdo não versionado de
`docs/recipes/gateway-headscale-podman-rootless.md`; essa versão não possui revisão Git própria.
O servidor era `rhel9host.hv` — RHEL 9.8, Podman 5.8.2 — e o cliente `ContainerHost.hv` — Debian 13,
Tailscale 1.104.4. Pendências e riscos remanescentes constam em [TODO.md](../plans/TODO.md).

O conteúdo não versionado de `docs/recipes/gateway-headscale-podman-rootless.md` também classificava
o uso de `enroll-gateway.sh` na inscrição rootless como workaround de laboratório, enquanto a
integração rootless permanecia pendente.

O teste com `setcap` em `rootlessport` não permitiu o bind; o sysctl global
`net.ipv4.ip_unprivileged_port_start=443` foi adotado como mecanismo aprovado.

No teste de encaminhamento, as duas regras de `FORWARD` e `POSTROUTING` foram removidas juntas;
o TCP do cliente para o app expirou e as duas regras foram restauradas. O teste não comprovou a
necessidade individual de cada regra.

O encerramento da sessão e o stop/start do user manager reiniciaram o Gateway por linger; a rota
reapareceu e o cliente manteve a inscrição (2026-10-29). O reboot do host passou em 2026-11-05:
linger e unidades permaneceram ativos, a rota
`100.96.0.0/24 via 10.90.0.2 dev podman1` voltou, os nós 2 (`gateway-router`) e 3
(`containerhost`) ficaram online e o cliente reconectou. O nó 1 (cliente de teste) foi removido e
o Gateway recebeu o ID 2.

### Registros de build

- `apt-get` no build atingiu cerca de 16 GB de RSS e foi morto pelo OOM killer em 2026-11-04.
- Uma indisponibilidade do mirror Debian snapshot causou uma falha de build.
- O script de deploy rootless do Gateway não foi criado; o Gateway foi construído manualmente. Ele é distinto de `deploy/scripts/deploy-webapp-rootless.sh`.

### Resultados dos testes (2026-10-29 e 2026-11-05)

| Gate | Resultado | Evidência medida |
| --- | --- | --- |
| G0 | PASS | Rootless `true`, cgroups v2, linger `yes`, SELinux `Disabled`, TUN presente, home XFS local e dependências presentes. |
| G1 | PASS | **2026-11-05, 1ª tentativa — INVÁLIDA:** probe A reutilizou o alias `dev-gateway.dev.anatel`, que o Gateway já usa; a resposta incluiu `10.90.0.2` e o IP do probe `10.90.0.16`. Motivo: erro de desenho do teste. **2026-11-05, 2ª tentativa:** `g1-probe-a` (`g1-a.dev.anatel`) = `10.90.0.18`; `g1-probe-b` (`g1-b.dev.anatel`) = `10.90.0.19`. De `g1-probe-a` e `g1-probe-b`: `g1-a.dev.anatel` → `10.90.0.18` somente; `g1-b.dev.anatel` → `10.90.0.19` somente; `dev-gateway.dev.anatel` → `10.90.0.2` somente. **PASS:** critério atendido. **2026-10-29 (registro anterior):** layout diferente, dois aliases em um container; não comprova o critério de um container por alias. |
| G2 | PASS | Namespace rootless `ip_forward=1`; rota `100.96.0.0/24 via 10.90.0.2 dev podman1` reaplicada no restart. |
| G3 | PASS | Build `localhost/gateway:1.0.0` concluído a partir de cópia temporária em `/home/podman_user`; probe `NET_ADMIN`, `/dev/net/tun` e `ip_forward=1` retornou `0`. |
| G4 | PASS no runtime G5 | O validador isolado retornou erro: não monta `/etc/headscale/config.yaml` e usa `--network none`; com o arquivo montado, Headplane respondeu `500` porque Headscale não estava acessível. O Gateway completo passou healthcheck e leitura dos arquivos como UIDs `20001`/`20002`; essa limitação do helper não foi alterada em `deploy/`. |
| G5 | PASS | Quadlet `.container.d` entrou no unit gerado; health `healthy`; modos observados `644 0:0`, `644 0:0`, `600 0:0`; rota reapareceu após restart. |
| G6 | PASS | Cliente `100.96.0.2` alcançou o app por IP e alias; NGINX registrou peer `100.96.0.2`, sem SNAT. Remover as regras estreitas de `FORWARD`/`POSTROUTING` causou timeout; regras restauradas. |
| G7 | PASS | UDP e TCP para `10.90.0.1:53` resolveram Gateway `10.90.0.2` e app `10.90.0.3`; split DNS do cliente funcionou. |
| G8 | PASS em TCP 443 pela LAN e VPN; WAN não testada | Resultados de `/admin` constam em [Cliente VPN](#cliente-vpn); NGINX recebeu `100.96.0.2` pela VPN e `10.90.0.2` pela LAN via `rootlessport`. Headscale usa `https://headscale.dev.anatel` em TCP 443. |
| G9 | PASS; reboot do host PASS em 2026-11-05 | Linger e unidades ativos; rota `100.96.0.0/24 via 10.90.0.2 dev podman1`; nós Headscale 2 (`gateway-router`) e 3 (`containerhost`) online; cliente reconectado sem reinscrição. |
| G10 | ALVO APROVADO | `ARCHITECTURE.md` define rootless como alvo; o deploy rootless do Gateway como código permanece pendente em `.agent/plans/TODO.md`. |

Na migração, TCP 443 foi publicado junto com TCP 8443; `server_url` mudou para
`https://headscale.dev.anatel`, Gateway e cliente reautenticaram com `--force-reauth`, mantiveram
IDs 2 e 3 e IPs `100.96.0.1` e `100.96.0.2`, e a rota `10.90.0.0/24` foi aprovada antes da
remoção de 8443. Remover 8443 antes de reinscrever o Gateway deixou seu nó offline; o serviço foi
recuperado.

O helper G4 é uma pré-checagem isolada, não uma verificação completa deste YAML. Para este modelo,
G4 foi fechado somente após o healthcheck do Gateway completo passar em G5.

### Decisões e valores registrados

As aprovações ocorreram antes do teste; os valores operacionais foram confirmados no laboratório em
2026-10-29.

| Título da Decisão | Estado / input necessário | Decisão |
| --- | --- | --- |
| Nome e home da conta | Aprovar `<GATEWAY_USER>` (sugestão `podman_user`) e confirmar home local sem NFS, `noexec` ou `nodev`. | Confirmado. Criar usuário e registrar senha inicial em variável .env. Usar `su podman_user` para operações com este usuário a partir da conta principal. |
| HTTPS privilegiado | Publicar TCP 443 diretamente no host rootless; sysctl global aprovado e documentado. | Confirmado. Usar `net.ipv4.ip_unprivileged_port_start=443` |
| IP cliente no endpoint público | Medir o efeito `rootlessport`; avaliar `pasta` somente em experimento aprovado, sem assumir preservação de origem. | Confirmado. Medir efeito `rootlessport` |
| Proprietário de secrets/config | Validar `podman unshare chown` para UID `20001`/`20002`, leitura pelo processo e fluxo seguro de edição/backup. | Confirmado. Validar `podman unshare chown` |
| Mecanismo de rota | Validar drop-in `ExecStartPost` versus unidade de usuário separada, incluindo restart e recriação do netns. | Confirmado. Usar drop-in `ExecStartPost` |
| Risco residual não verificado | Suporte a drop-in `.container.d` no Podman 5.8.2 do alvo. | Confirmado. Verificar suporte no Podman 5.8.2 |
| Subnet e endereços | Definir `<ROOTLESS_SUBNET>`, `<ROOTLESS_BRIDGE_IP>`, `<GATEWAY_IP>`, `<ROOTLESS_BRIDGE_IFACE>` e `<VPN_PREFIX>` sem sobreposição. | Confirmado. Definir sem sobreposição |
| VM de teste | Aprovar VM descartável RHEL 9.8 / Podman 5.8.2, snapshots e janela de reboot/rollback. | Confirmado. VM disponível é descartável |
| Adoção | Rootless como alvo; rootful mantido como alternativa. | Aprovado; deploy do Gateway como código continua pendente em `.agent/plans/TODO.md` |

| Decisão | Justificativa | Valor medido ou adotado |
| --- | --- | --- |
| D1 — papéis de máquina | Confirmados por hostname, SO e IP; esta sessão roda no servidor descartável. | Servidor `rhel9host.hv`, RHEL 9.8, `192.168.7.160`; cliente `ContainerHost.hv`, Debian 13, `192.168.7.148`. |
| D2 — limpeza rootful | Inventário rootful sem containers/imagens/volumes; unidade antiga falha e foi preservada, não apagada. | Backup `/root/legacy-gateway-backup-20261029-165429/gateway.container`; `/etc/gateway`, `/var/lib/gateway` e rede `podman` preservados. |
| D3 — conta e senha inicial | Conta dedicada já existia; home local XFS; senha aleatória foi definida sem exibição e armazenada somente no `.env` ignorado. | `podman_user`, UID `1001`, `/home/podman_user`; `.env` modo `0600`, `git check-ignore .env` confirmou exclusão. |
| D4 — corte HTTPS | Migrar sem perder a inscrição do Gateway; publicar as duas portas até confirmar nós e rota. | TCP 443 publicado ao lado de 8443; `server_url=https://headscale.dev.anatel`; Gateway e cliente reautenticados com `--force-reauth`, IDs 2 e 3 e IPs `100.96.0.1` e `100.96.0.2`; rota `10.90.0.0/24` aprovada antes de remover 8443. |
| D5 — nomes e TLS | Certificado de laboratório com SAN para os dois endpoints; mecanismo de confiança não registrado. | `headscale.dev.anatel`, `dev-gateway.dev.anatel`; CA `GWVPN Lab CA 2026`; arquivo público da CA presente no cliente; TLS em TCP 8443 validado contra a CA do laboratório. |
| D6 — faixas | Sem sobreposição com LAN, rede rootful, bridge Podman do cliente ou prefixo VPN. | Bridge `10.90.0.0/24`, resolver `10.90.0.1`, Gateway `10.90.0.2`, app `10.90.0.3`, VPN `100.96.0.0/24`; LAN `192.168.7.0/24`, rootful `10.88.0.0/16`, cliente `10.89.0.0/24`. |
| D7 — sessão rootless | `su -` mais runtime explícito forneceu user bus e Podman rootless. O checkout sob `/home/lobao` era inacessível; fontes foram copiadas temporariamente para home `podman_user`. | `XDG_RUNTIME_DIR=/run/user/1001`; staging temporário removido após build/validação. |
| D8 — `ip_forward` | Valor `1` necessário na namespace rootless; persistir no drop-in, sem sysctl global. | `podman unshare --rootless-netns /usr/sbin/sysctl -w net.ipv4.ip_forward=1`. |
| D9 — Quadlet/forwarding | Drop-in `.container.d` foi mesclado no unit gerado. Teste sem exceções de firewall causou timeout TCP. | `10-return-route.conf`: sysctl, rota, `FORWARD` ACCEPT e `POSTROUTING` ACCEPT idempotentes e limitados às faixas testadas. |
| D10 — autostart | Reinício do user manager passou com linger; reboot do host passou em 2026-11-05. | `loginctl terminate-user podman_user`, stop/start `user@1001.service`; unidades ativas, rota restaurada, nós 2 e 3 online e cliente reconectado. |

### Diferenças do contrato registradas na G10

- **Rede e modo do Podman — histórico:** um texto do contrato, sem data registrada, exigia a rede padrão rootful `podman`; os testes usaram `gateway-vpn` (`10.90.0.0/24`). O contrato vigente define rootless como alvo e rootful como alternativa.
- **Endereços de aplicações — histórico:** uma cláusula de endereçamento do contrato, sem data registrada, tratava IPs como não permanentes; o contrato vigente fixa `10.90.0.10` (`webapp-db`), `10.90.0.11` (`webapp`) e `10.90.0.12` (`app-proxy`).
- **Emulador de identidade:** permanece a implementar, fora do escopo atual; consulte [ARCHITECTURE.md](../contracts/ARCHITECTURE.md) e a pendência em [TODO.md](../plans/TODO.md).
- **SSH em containers:** SSH/VS Code continuam a implementar e fora do escopo atual (§11 e critérios de aceitação); consulte [ARCHITECTURE.md](../contracts/ARCHITECTURE.md) e a pendência em [TODO.md](../plans/TODO.md).
- **Firewall do host — histórico:** `firewalld` estava ativo antes da preparação; o script da etapa 1 desativa `firewalld` e `nftables` quando presentes, e ambos estão desativados no host testado.
- **G8 — histórico:** Headscale foi testado inicialmente em `:8443`; Headplane e o endpoint de controle/VPN foram depois testados em TCP 443 pela LAN e VPN. O ingresso WAN/perímetro externo continua sem teste.

A revisão G10 alinhou no contrato os caminhos HTTP `/webapp/` e `/webapp/api/`.

### Endereços da webapp no laboratório

No laboratório, os pods da webapp usaram a rede `gateway-vpn` (`10.90.0.0/24`) com endereços
fixos:

| Container | Endereço | Alias de desenvolvimento |
| --- | --- | --- |
| `webapp-db` | `10.90.0.10` | `webapp-db.dev.anatel` |
| `webapp` (API) | `10.90.0.11` | `webapp.dev.anatel` |
| `app-proxy` | `10.90.0.12` | `app-proxy.dev.anatel` |

Os nomes internos `webapp-db`, `webapp` e `app-proxy` permaneceram inalterados. O deployment
rootless da aplicação está em
[deploy/scripts/deploy-webapp-rootless.sh](../../deploy/scripts/deploy-webapp-rootless.sh).
O deploy rootful permanece como alternativa implementada e mantida. O alvo rootless foi aprovado;
a implementação do deploy do Gateway como código continua pendente em [TODO.md](../plans/TODO.md).

### Desvios temporários usados no teste

Os desvios abaixo foram usados somente no laboratório rootless; os arquivos compartilhados do
repositório permaneceram inalterados.

#### (a) Healthcheck compatível com UIDs rootless

- **O que é arquivo/drop-in:** `/home/podman_user/.config/gateway-vpn/gateway-healthcheck-rootless.sh` montado sobre `/usr/local/sbin/gateway-healthcheck` pelo drop-in `30-healthcheck-rootless.conf`; usa `setpriv` para ler `/proc/<pid>/exe` como Headscale UID `20001` e Headplane UID `20002`.
- **Motivo:** o healthcheck compartilhado lê `/proc/<pid>/exe` de outro UID, operação negada no modo rootless.
- **Escopo:** rootless-only, test-only.
- **Substituição:** corrigir o healthcheck compartilhado para fazer leituras de executáveis compatíveis com o UID de cada serviço.

#### (b) Diretório de runtime do Headscale

- **O que é arquivo/drop-in:** `20-headscale-runtime.conf` vincula `/home/podman_user/.local/share/gateway-headscale-runtime` a `/run/headscale` com escrita.
- **Motivo:** `/var/run` aponta para `/run`, pertencente a root e sem escrita pelo UID `20001`.
- **Escopo:** rootless-only, test-only.
- **Substituição:** definir `/run/headscale` e suas permissões na imagem ou no Quadlet.

#### (c) Bundle de CA do laboratório

- **O que é arquivo/drop-in:** `50-lab-ca-bundle.conf` monta `/home/podman_user/.config/gateway-vpn/trust/ca-bundle.crt` sobre `/etc/ssl/certs/ca-certificates.crt`; o bundle combina as CAs da imagem e a CA pública do laboratório.
- **Motivo:** o container não confiava na CA do laboratório (verify code 21).
- **Escopo:** rootless-only, test-only.
- **Substituição:** fornecer aos containers a CA aprovada pela infraestrutura.

#### (d) Nome do control server no container

- **O que é arquivo/drop-in:** `40-control-host.conf` adiciona `AddHost=headscale.dev.anatel:192.168.7.160`.
- **Motivo:** o container não tinha resolução DNS para o control server.
- **Escopo:** rootless-only, test-only.
- **Substituição:** usar um nome DNS estável do Headscale, fornecido pela infraestrutura.

#### (e) Ownership dos arquivos Headscale

- **O que é arquivo/drop-in:** `/var/lib/headscale/noise_private.key` e `/var/lib/headscale/db.sqlite` no volume Headscale foram ajustados para `20001:20001`; a receita não define regra de ownership para eles.
- **Motivo:** os arquivos estavam pertencentes a root dentro do volume.
- **Escopo:** rootless-only, test-only.
- **Substituição:** declarar uma regra de ownership reproduzível no provisionamento do volume e validá-la para UID `20001`.

#### (f) Porta não padrão na inscrição

- **O que é arquivo/drop-in:** inscrição de laboratório usou `https://headscale.dev.anatel:8443`; `deploy/scripts/enroll-gateway.sh` monta a URL de controle sem porta.
- **Motivo:** o endpoint de teste estava em TCP `8443` e o script não inclui uma porta não padrão.
- **Escopo:** rootless-only, test-only.
- **Substituição:** usar o endpoint estável de produção em TCP `443`; se uma porta não padrão for necessária, atualizar e testar o fluxo de inscrição antes de adotá-lo.

#### (g) Volume da imagem webapp

- **O que é arquivo/drop-in:** volume da imagem criado com `--opt o=uid=10001,gid=10001` no fluxo `deploy/scripts/deploy-webapp-rootless.sh`.
- **Motivo:** a primeira montagem de um volume vazio copia o proprietário do ponto de montagem.
- **Escopo:** rootless-only, test-only.
- **Substituição:** definir e validar ownership no mecanismo oficial de criação do volume, sem depender da cópia inicial do proprietário.

#### (h) Chave privada da CA de desenvolvimento

- **O que é arquivo/drop-in:** `/root/gateway-cockpit-ca/gateway-dev-ca.key` ainda existe no servidor.
- **Motivo:** chave temporária de desenvolvimento mantida durante a estabilização da solução.
- **Escopo:** rootless-only, test-only e dev-only.
- **Substituição:** depois que a solução estiver estável, gerar novas chaves seguindo estritamente a receita; não documentar nem compartilhar o conteúdo da chave existente.

**Status registrado:** G0, G1, G2, G3, G5, G6, G7, G8 e G9 passaram; G4 foi confirmado pelo runtime integrado em G5, pois o validador isolado não monta a configuração Headscale e usa `--network none`. G8 em TCP 443: `/admin` retornou 302 pela VPN e 403 pela LAN. O ingresso WAN/perímetro externo não foi testado. G9: reboot do host passou; rota `100.96.0.0/24 via 10.90.0.2 dev podman1`, Gateway ID 2 (`gateway-router`, `100.96.0.1`) e cliente ID 3 (`containerhost`, `100.96.0.2`) online. O build G3 foi executado de cópia temporária em `/home/podman_user`. A adoção do rootless como alvo foi aprovada; o deploy do Gateway como código continua pendente em [TODO.md](../plans/TODO.md).

### Observações complementares registradas

As datas das observações abaixo não foram especificadas, exceto quando indicadas.

- **Nome do nó Gateway:** `tailscale status` no cliente em 2026-11-05 mostrou a mudança de `554ad3114093` para `35085f0529a0` após recriação/reinício do container.
- **Transporte UDP/DERP:** o nó Gateway conecta pelo relay DERP de Madrid; UDP direto não foi estabelecido a partir do container.
- **Exceção de origem LAN:** `rootlessport` entrega solicitações LAN ao NGINX com origem `10.90.0.2` e oculta o cliente; o contrato exige preservação da origem somente no caminho VPN.
- **RISCO ACEITO:** Cockpit escuta TCP 9090 pelo socket systemd e é alcançável pela LAN com o firewall desativado; o usuário decidiu manter Cockpit como está.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Cliente VPN

Registros históricos extraídos de conteúdo não versionado de
`docs/recipes/gateway-vpn-client.md`; essa versão não possui revisão Git própria. O registro das
linhas de 2026-10-29 veio de uma sessão de laboratório dessa data, fora do repositório.

| Data | Comando ou teste | Plataforma | Estado |
| --- | --- | --- | --- |
| 2026-10-29 | `tailscale status` e nós do Headscale | Debian 13 / Tailscale 1.104.4 | Testado; os nós observados naquela sessão permaneceram online. A numeração atual está registrada na linha de 2026-11-05. |
| 2026-10-29 | DNS dividido por `10.90.0.1:53` | Debian 13 / Tailscale 1.104.4 | Testado por UDP e TCP; o Gateway resolveu para `10.90.0.2` e o serviço de aplicação da prova para `10.90.0.3`. |
| 2026-10-29 | HTTPS em TCP 8443 pela LAN | Debian 13 / Tailscale 1.104.4 | Testado; respondeu HTTP 200; TLS em TCP 8443 validado contra a CA do laboratório. Um arquivo público da CA estava presente no cliente; o mecanismo de confiança (`update-ca-certificates` ou `--cacert`) não foi registrado. Isso não comprova a execução do procedimento de confiança da CA. Certificado `CN=headscale.dev.anatel`, emissor `CN=GWVPN Lab CA 2026`. |
| 2026-10-29 | Acesso à aplicação por IP e alias | Debian 13 / Tailscale 1.104.4 | Testado; a aplicação recebeu `100.96.0.2` como IP de origem VPN preservado, conforme §5.5 do contrato. |
| 2026-10-29 | TCP 443 e 9090 do servidor pela LAN | Debian 13 / Tailscale 1.104.4 | Sem conexão (`http_code=000`); o servidor não tinha listener nessas portas no momento. O encaminhamento externo TCP 443 não foi testado. |
| 2026-10-29 | Rota default do cliente | Debian 13 / Tailscale 1.104.4 | Testado; permaneceu `192.168.7.1`. |
| 2026-11-05 | Reboot do host e reconexão do cliente | RHEL 9.8 / Podman 5.8.2; Debian 13 / Tailscale 1.104.4 | Testado; linger e unidades ativos, rota `100.96.0.0/24 via 10.90.0.2 dev podman1`, nós Headscale 2 e 3 online e cliente reconectado. |
| 2026-11-05 | `getent hosts` para os aliases da webapp | Debian 13 / Tailscale 1.104.4 | Testado; `webapp-db.dev.anatel` → `10.90.0.10`, `webapp.dev.anatel` → `10.90.0.11` e `app-proxy.dev.anatel` → `10.90.0.12`. |
| 2026-11-05 | SPA `http://app-proxy.dev.anatel:8080/webapp/index.html` | Debian 13 / Tailscale 1.104.4 | Testado; HTTP 200. |
| 2026-11-05 | Saúde da API `http://app-proxy.dev.anatel:8080/webapp/api/health` | Debian 13 / Tailscale 1.104.4 | Testado; resposta `{"status":"ok"}`. |
| 2026-11-05 | TCP `webapp-db.dev.anatel:5432` | Debian 13 / Tailscale 1.104.4 | Testado; conexão TCP aberta. Não houve autenticação nem consulta PostgreSQL. |
| 2026-11-05 | Origem do cliente nos logs NGINX | Debian 13 / Tailscale 1.104.4 | Testado; NGINX registrou `100.96.0.2`. |
| 2026-11-05 | Headplane `/admin` pela VPN em TCP 443 | Debian 13 / Tailscale 1.104.4 | Testado; HTTP 302. |
| 2026-11-05 | Headplane `/admin` pela LAN em TCP 443 | Debian 13 / Tailscale 1.104.4 | Testado com destino fixado em `192.168.7.160`; HTTP 403. NGINX recebeu `10.90.0.2`. |
| 2026-11-05 | Ping do cliente ao Gateway | Debian 13 / Tailscale 1.104.4 | Testado; 30/30 pacotes, 0% de perda. |
| 2026-11-05 | Webapp pela LAN em TCP 8080 | Debian 13 / Tailscale 1.104.4 | Testado; HTTP 200. |

A inscrição inicial de 2026-10-29 usou uma chave de uso único e o endpoint temporário
`https://headscale.dev.anatel:8443` pela LAN; o comando CLI exato não consta no registro. Não use
8443 para novas inscrições. Em 2026-11-05, os nós mantiveram IDs 2 (`gateway-router`,
`100.96.0.1`) e 3 (`containerhost`, `100.96.0.2`). O nó 1 de teste foi removido. O endpoint TCP
443 foi testado pela LAN e pela VPN; o ingresso WAN/perímetro externo não foi testado.

Os comandos e fluxos que não constam como testados na tabela são não verificados, inclusive a forma
escrita `tailscale up --auth-key=file:`, `--operator`, `resolvectl query`, `ip route get`, GUIs,
Windows e macOS. Os comandos da seção de confiança na CA também não foram executados como escritos.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Gateway rootful

O arquivo `docs/recipes/gateway-headscale-podman-rootfull copy.md` em HEAD
`6fe47b29172bece1c804b7ce59d68b3d9577db80` dizia: “Receita manual para RHEL 9.8, Podman 5.8.2
e Quadlet. Testado em verificação descartável no Debian 13.6 (trixie) com Podman 5.4.2; a
qualificação-alvo permanece RHEL 9.8 / Podman rootful 5.8.2.” A receita rootful atual mantém o
aviso de que o alvo não deve ser declarado qualificado antes da validação final no ambiente RHEL
autorizado (seção [Testes funcionais](../../docs/recipes/gateway-headscale-podman-rootfull.md#7-testes-funcionais)).
A fonte em HEAD não registra resultados individuais desses testes.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Design System GOV.BR

Registro da pesquisa original de 2026-10-31, extraído de
`docs/recipes/govbr-design-system.md` em HEAD
`6fe47b29172bece1c804b7ce59d68b3d9577db80`. As fontes oficiais e URLs externas não
foram rechecadas na rodada registrada. A pesquisa consultou somente conteúdo público externo;
nenhum código do projeto foi enviado a serviços externos. Foram lidos os fundamentos, guias,
configuração pública e arquivos distribuídos citados.

Core 3.7.0, CSS/JS versionados, CSS Rawline e CSS Font Awesome 5.11.2 responderam HTTP 200.
O registro também compara `chevron-left.svg` e `chevron-right.svg` aos arquivos Font Awesome Free
5.11.2; a única diferença observada foi o newline final.

- Os logotipos da Anatel e do gov.br foram usados com autorização do responsável do projeto; a
  verificação do manual da marca gov.br segue pendente de confirmação da versão vigente.
- O pacote oficial de ilustrações 1.0.0 foi inspecionado; 248 PNGs 1x foram copiados. Versões
  2x/3x e arquivos-fonte Adobe Illustrator não foram incluídos.
- O ZIP não contém arquivo de licença; a política de licenças GOV.BR-DS e o repositório oficial
  `govbr-ds-assets-de-design/LICENSE-CC0` identificam CC0 para os assets de design.
- CDNFonts respondeu 403; a licença Rawline foi verificada no ZIP oficial.
- Links Figma do catálogo responderam 202 sem conteúdo legível; seus arquivos não foram
  inspecionados.
- A iconografia menciona Font Awesome 5.10.2, o guia Core usa 5.11.2 e o exemplo CDN WBC usa
  5.15.4. Escolha as dependências da release auditada, não uma mistura de exemplos.
- O guia Core desaconselha o CDN antigo do DS; o guia WBC recomenda jsDelivr. São serviços
  distintos.
- O texto “WCAG 2.1” da diretriz de cores aponta a WCAG 2.0; use o endereço W3C 2.1 vinculado
  acima.
- A página Secom foi consultada; seu PDF, arquivos de marca e permissões específicas não foram
  auditados.
- Os testes estáticos de header/footer verificam HTML e CSS; o teste de header também lê o CSS
  Core. O teste estático de menu verifica HTML, CSS local, CSS Core e `navigation.mjs`; o teste de
  page-header verifica apenas HTML.
- `css-scanner.test.mjs` testa explicitamente, via `node --test`, o subconjunto CSS documentado em
  `webapp/frontend/tests/helpers/css-scanner.mjs`; o scanner não é um parser CSS completo.
- Os testes comportamentais executam `navigation.mjs` e o `app.js` real com DOM, APIs de diálogo,
  media query e `fetch` simulados. `dialog-accessibility.test.mjs` testa isoladamente
  `dialog-accessibility.mjs` com alvos de foco simulados. Nenhuma validação em Chromium/Electron
  ou renderização real foi executada; os testes não comprovam estilos computados, dimensões,
  integração com APIs nativas do navegador, serviço de rede ou comportamento com leitor de tela.
- Os SVGs dos logotipos da Anatel e do gov.br declaram proporção intrínseca nos atributos
  `width` e `height`, não têm atributo `viewBox`, e sua renderização no navegador não foi
  verificada.
- A validação automatizada do frontend foi executada em Linux, Bash 5.1.8 (shell com expansão de
  glob) e Node.js v24.21.0. Essa é uma versão testada, não uma versão mínima declarada. Os
  comandos explícitos, sem glob, estão na [receita CRUD](../../docs/recipes/webapp-crud.md#desenvolver).
- A validação visual em navegador e dos estilos computados ainda está pendente.
- As verificações não incluem auditoria completa com leitor de tela nem certificação de
  acessibilidade.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>

## Validação da webapp

Em HEAD `6fe47b29172bece1c804b7ce59d68b3d9577db80`, `docs/recipes/webapp-crud.md` dizia
“Validado em RHEL 9.8 com Podman 5.8.2.” Em HEAD `6fe47b29172bece1c804b7ce59d68b3d9577db80`,
`docs/plans/webapp-crud.md` registrava: “Status: implementado e validado no host RHEL 9.8 com
Podman 5.8.2 rootful.” Essas fontes não informam resultados ou argumentos específicos de testes.

O plano atual, `.agent/plans/webapp-crud.md`, registra “Status: implementação concluída” e aponta
o registro histórico da validação para este arquivo.

O ambiente registrado para a validação automatizada do frontend foi Linux, Bash 5.1.8 (shell com
expansão de glob) e Node.js v24.21.0, verificado por `node --version`. Essa é uma versão testada,
não uma versão mínima declarada. Os comandos explícitos, sem glob, estão na
[receita CRUD](../../docs/recipes/webapp-crud.md#desenvolver).

Em 2026-11-06, gate G1 (fundamentos CSS da tabela de usuários), arquivo
`webapp/frontend/styles.css`: duas revisões independentes, com correções aplicadas.
Validação: css-scanner 4/4 PASS, navegação 46/46 PASS e `git diff --check` limpo.
O Reviewer não tinha shell; o Coder executou os testes.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
