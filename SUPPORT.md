# Support

## Getting Help

This repository is an architectural baseline with a minimal Python scaffold. Use these resources for questions and project feedback:

### Documentation

- **README:** [Architecture overview and current project status](./README.md)
- **Architecture plan:** [Technical and operational contract](./docs/plans/WEB_APP_BOILERPLATE_ARCHITECTURE.md)
- **Contribution guide:** [CONTRIBUTING.md](./CONTRIBUTING.md)

### Reporting Issues

1. Search the [existing repository issues](https://github.com/FSLobao/webAppBoilerPlate/issues).
2. Include steps to reproduce, expected and actual behavior, and relevant environment details.
3. Remove passwords, tokens, private keys, and sensitive data from logs or configuration before sharing.
4. [Open an issue](https://github.com/FSLobao/webAppBoilerPlate/issues/new) for reproducible bugs or missing documentation.

### Feature Requests

Check existing [issues](https://github.com/FSLobao/webAppBoilerPlate/issues) first. Describe the need, the proposed behavior, and how it fits the architecture. Submit the request through the repository issue tracker.

### Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidance on proposing changes, adding tests, and submitting pull requests.

### Community

Use [GitHub Discussions](https://github.com/FSLobao/webAppBoilerPlate/discussions) for general questions if Discussions are enabled. Use pull requests for proposed changes.

## Testing and Current Limitations

An application API, deployment stack, and automated test suite have not been implemented yet. The current command `uv run python -m src.main` runs only the Python scaffold; it does not validate the planned application architecture or containers.

## FAQ

### The Python scaffold does not run

Check that Python 3.14 or later and UV are available, then run `uv sync` followed by `uv run python -m src.main`.

### How do I deploy the application?

Deployment scripts and container definitions are not available yet. Review the [architecture plan](./docs/plans/WEB_APP_BOILERPLATE_ARCHITECTURE.md) for the intended deployment model.

### Where should I report a security issue?

Do not open a public issue. Follow the private reporting instructions in [SECURITY.md](./SECURITY.md).

## Code of Conduct

This project follows the [Code of Conduct](./CODE_OF_CONDUCT.md). By participating, you are expected to uphold it.
