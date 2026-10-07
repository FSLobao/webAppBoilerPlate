# Contributing to Web App Boilerplate

Thanks for taking the time to contribute to this foundation for web applications.

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](./CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

Before creating a bug report, search the [repository issues](https://github.com/FSLobao/webAppBoilerPlate/issues) for an existing report. Include as many details as possible:

* **Use a clear and descriptive title**
* **Describe the exact steps which reproduce the problem**
* **Provide specific examples to demonstrate the steps**
* **Describe the behavior you observed after following the steps**
* **Explain which behavior you expected to see instead and why**
* **Include screenshots and animated GIFs if possible**
* **Include your configuration file** (with sensitive information removed)
* **Include log files** (with sensitive information removed)

### Suggesting Enhancements

Enhancement suggestions are tracked as [GitHub issues](https://github.com/FSLobao/webAppBoilerPlate/issues). Please include:

* **Use a clear and descriptive title**
* **Provide a step-by-step description of the suggested enhancement**
* **Provide specific examples to demonstrate the steps**
* **Describe the current behavior and expected behavior**
* **Explain why this enhancement would be useful**

### Pull Requests

* Fill in the pull request template, if one is provided
* Follow the Python style guide (PEP 8)
* Include appropriate test cases
* Document new code with docstrings
* End all files with a newline
* Use meaningful commit messages

## Development Setup

1. Clone the repository
2. Install [UV](https://docs.astral.sh/uv/)
3. Run `uv sync` to install dependencies
4. Create a feature branch: `git checkout -b feature/your-feature`
5. Make your changes and add tests
6. Run the tests and checks available for the components you changed
7. Commit with clear messages: `git commit -am 'Add some feature'`
8. Push to the branch: `git push origin feature/your-feature`
9. Open a Pull Request

## Testing

This repository currently contains an architectural proposal and a minimal Python scaffold; it does not yet have an application test suite. Add focused tests when introducing behavior, and run the checks configured for the affected components before submitting a pull request.

## Style Guide

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) for Python code
- Use type hints in function signatures
- Write descriptive docstrings for functions and classes
- Use meaningful variable names

## Additional Notes

### Issue and Pull Request Labels

These are common labels for organizing issues and pull requests, when available.

* `bug` - Something isn't working
* `enhancement` - New feature or request
* `documentation` - Improvements or additions to documentation
* `good first issue` - Good for newcomers
* `help wanted` - Extra attention is needed
* `question` - Further information is requested

## Recognition

Contributors will be recognized in the project and release notes.

Thank you for contributing to Web App Boilerplate!
