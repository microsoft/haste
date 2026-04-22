# Contributing to HASTE

We welcome contributions to the HASTE (High-speed Assessment and Satellite Tracking for Emergencies) project!

## Getting Started

Before you begin, please:

1. Read the [README.md](README.md) for project setup instructions
2. Review the [Code of Conduct](https://opensource.microsoft.com/codeofconduct/)
3. Check existing [issues](../../issues) and [pull requests](../../pulls)

## Development Setup

Follow the setup instructions in the README.md to get your development environment running:

1. Install prerequisites (Node.js, Python 3.11+, Azure CLI, etc.)
2. Set up the conda environment: `conda env create -f env.yml`
3. Install the haste utilities: `pip install -e hastelib/`
4. Set up the UI: `cd ui && npm install`

## How to Contribute

### Reporting Issues

- Use the GitHub issue tracker to report bugs
- Include detailed reproduction steps
- Provide system information (OS, Python version, etc.)
- Include error messages and logs

### Submitting Changes

1. **Fork** the repository
2. **Create a branch** for your changes: `git checkout -b feature/your-feature-name`
3. **Make your changes** following our coding standards
4. **Test your changes** thoroughly
5. **Commit your changes** with clear commit messages
6. **Push to your fork** and create a pull request

### Pull Request Guidelines

- Provide a clear description of the changes
- Reference any related issues
- Include tests for new functionality
- Ensure all existing tests pass
- Update documentation as needed
- Follow the existing code style

## Coding Standards

### Python Code
- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Include docstrings for functions and classes
- Maintain test coverage

### JavaScript/React Code
- Use modern ES6+ syntax
- Follow React best practices
- Include PropTypes for components
- Use meaningful variable and function names

### General Guidelines
- Keep functions small and focused
- Use descriptive commit messages
- Comment complex logic
- Remove unused imports and variables

## Testing

Before submitting a pull request:

1. Run Python tests: `pytest`
2. Run JavaScript tests: `cd ui && npm test`
3. Test the full application locally
4. Verify all functionality works end-to-end

## Documentation

- Update README.md if you change setup instructions
- Update API documentation for new endpoints
- Include inline code comments for complex logic
- Update this CONTRIBUTING.md if you change the contribution process

## Contributor License Agreement

Most contributions require you to agree to a Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant Microsoft the rights to use your contribution. For details, visit [https://cla.opensource.microsoft.com](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions provided by the bot. You only need to do this once across all repos using our CLA.

## License

By contributing to HASTE, you agree that your contributions will be licensed under the MIT License.

## Questions?

If you have questions about contributing, please:

1. Check the existing documentation
2. Search closed issues for similar questions
3. Open a new issue with the "question" label

Thank you for contributing to HASTE!
