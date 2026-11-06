<details id="top">
    <summary>Índice</summary>
    <ol>
        <li><a href="#inputs-e-gates-de-implementação">Inputs e gates de implementação</a></li>
    </ol>
</details>

# Plano: inputs e gates de implementação

Este plano registra inputs operacionais, decisões pendentes e verificações planejadas para a
implementação. Os critérios normativos de aceitação permanecem em
[ARCHITECTURE.md](../contracts/ARCHITECTURE.md), especialmente na seção 24.

## Inputs e gates de implementação

1. Inspecionar CIDR, bridge e IPAM da rede padrão conforme a seção 9; validar endereço estável do Gateway e conflitos com prefixo VPN e rotas relevantes do host, LAN e ambiente corporativo.
2. Definir URL HTTPS, DNS de bootstrap, certificados, binds e portas do Headscale, conectividade direta e infraestrutura DERP/STUN autorizada.
3. Fixar versões compatíveis de Headscale, Headplane e Tailscale; validar runtime Headplane, supervisão conjunta, `/dev/net/tun`, capabilities e volumes persistentes no Gateway.
4. Desativar SNAT do subnet router, validar retorno determinístico pelo host e determinar por teste se policy routing adicional é necessário.
5. Validar capabilities, rotas, reinício, DNS e egress no host descartável autorizado RHEL 9.8 / Podman 5.8.2.
6. Definir operadores autorizados de produção, UIDs/GIDs e identidades de processo; validar os três locais de PostgreSQL (`PGDATA`, repositório pgBackRest de trabalho e mount de exportação concluída), capacidade/permissões, snapshot consistente, staging de publicação e restore drill.
7. Definir a lista permitida dos campos de identidade `X-USER` e o mecanismo verificável de proveniência perímetro-aplicação antes de expor rotas protegidas.
8. Definir a versão Node.js suportada, o storage e a conta do TUS. O limite de arquivo padrão é 1 GB e é configurável.
9. Implementar e validar os requisitos DNS e os testes de clientes descritos na seção 9.
10. Definir prefixo IPv4 da VPN, política de acesso, aprovação de rotas e restrição dos endpoints Headplane/Portainer a operadores. Validar inscrição pelo endpoint HTTPS antes da VPN.
11. Implementar bootstrap administrativo e fluxo Headplane de tokens de uso único, expiração/revogação por dispositivo, auditoria sem segredos, backup e recuperação sem reinscrição. OIDC exige decisão e configuração separadas. Essa decisão segue planejada, não é requisito normativo nem aprovação para implantação.
12. Decidir separadamente quando converter a receita Debian do File Gateway em uma implantação containerizada.
13. Adequar schema, runtime, configuração, testes e documentação operacional aos contratos de acesso único, rede padrão única e DNS Podman nativo. Validar explicitamente campos substituídos, preservar compatibilidade das seções não relacionadas e não presumir suporte do validador atual a campos novos.
14. Selecionar edição/versão Portainer compatível, validar RHEL 9.8 / Podman 5.8.2 pela API compatível com Docker e comprovar acesso local ao socket sem `--privileged`. Testar HTTPS, restrição de ingresso pela VPN e pela bridge, bootstrap, backup/restore de `/data` e operações sem conflito com Quadlet. Falha de compatibilidade bloqueia aceitação.
15. A infraestrutura deve instalar e habilitar Cockpit no host RHEL, definir endereço/bind e certificado HTTPS, autenticação corporativa e autorização de privilégios. Validar restrição de ingresso, gestão de serviços/logs/armazenamento e acesso administrativo com o Gateway parado, sem depender da VPN de desenvolvimento nem instalar `cockpit-podman`.

<div>
  <a href="#top" title="De volta ao topo da página">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="../../docs/images/up-arrow_white.svg">
      <img align="right" width="40" height="40" src="../../docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
    </picture>
  </a>
  <br><br>
</div>
