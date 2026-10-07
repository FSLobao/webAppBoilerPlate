# Security Policy

This repository currently contains an architectural proposal and a minimal Python scaffold. The guidance below applies as the planned application and deployment components are implemented.

## Reporting a Vulnerability

Please **do not** report security vulnerabilities in public issues. Use [GitHub's private vulnerability reporting](https://github.com/FSLobao/webAppBoilerPlate/security/advisories/new) if it is enabled for this repository. Otherwise, contact the maintainers through the private channel documented by the repository.

Include the affected component, steps to reproduce, potential impact, and any suggested mitigation. Do not include secrets or personal data in the report.

Maintainers will acknowledge the report, investigate it, coordinate a fix and disclosure timeline, and credit the reporter if requested.

## Security Considerations

### Configuration and secrets

- Keep passwords, tokens, private keys, and private certificates out of Git and container images.
- Store runtime secrets outside the repository and mount each secret read-only only into services that need it.
- Restrict access to configuration, secret files, and persistent data.

### Containers and Podman

- Apply least privilege and avoid `--privileged` unless a reviewed requirement makes it necessary.
- Do not expose the Podman API over TCP; prefer the local Unix socket with restricted access.
- Keep application containers and the administrative Development Gateway separate in responsibility.

### Networks and data

- Keep each application's Podman network isolated from other applications.
- Do not expose PostgreSQL externally by default; allow access only from required services.
- Protect persistent volumes and backups with appropriate permissions and retention.

### SSH and logs

- Use individual SSH keys. Keep private keys on the developer's device and provision only public keys.
- Review logs for secrets or sensitive data before sharing them.

## Best Practices

1. Keep dependencies and container images updated.
2. Validate configuration and access controls in a non-production environment.
3. Monitor service and gateway logs while preventing sensitive data from being recorded.
4. Restrict access to host configuration, secrets, volumes, and backups.
5. Maintain and periodically test backups for persistent data.
6. Document deployment and security-relevant configuration changes.

## Supported Components

The Python project currently requires Python 3.14 or later. The planned remote environment targets RHEL 9 and Podman. A release support schedule has not yet been established; published releases will be listed on the [repository releases page](https://github.com/FSLobao/webAppBoilerPlate/releases).
