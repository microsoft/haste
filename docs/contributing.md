# Contributing to HASTE

We welcome contributions to the HASTE project! This guide will help you get started.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:

   ```bash
   git clone https://github.com/your-username/haste.git
   cd haste
   ```

3. **Set up the development environment**:

   ```bash
   conda env create -f env.yml
   conda activate haste_env
   ```

4. **Install pre-commit hooks**:

   ```bash
   pre-commit install
   ```

## Development Workflow

1. **Create a feature branch**:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** with proper documentation
3. **Test your changes** locally
4. **Run pre-commit hooks**:

   ```bash
   pre-commit run --all-files
   ```

5. **Commit your changes**:

   ```bash
   git add .
   git commit -m "Add: Brief description of your changes"
   ```

6. **Push to your fork**:

   ```bash
   git push origin feature/your-feature-name
   ```

7. **Create a pull request** on GitHub

## Code Standards

### Documentation Requirements

All public functions must have comprehensive docstrings:

- **Brief description** of what the function does
- **Detailed explanation** of complex behavior
- **Args section** with type hints and descriptions
- **Returns section** with possible status codes
- **Example usage** for complex functions

### Code Formatting

The project uses automated formatting:

- **Black** for code formatting (79 characters)
- **isort** for import sorting
- **flake8** for linting

These run automatically via pre-commit hooks.

### Testing

- Write **unit tests** for new functionality
- Ensure **existing tests pass**
- Add **integration tests** for API changes

## Pull Request Guidelines

Your pull request should:

1. **Have a clear title** describing the change
2. **Include a detailed description** of what was changed and why
3. **Reference any related issues** using `#issue-number`
4. **Include tests** for new functionality
5. **Update documentation** if needed
6. **Pass all CI checks**

### Example PR Description

```text
## Add comprehensive API documentation

### Changes
- Added detailed docstrings to all main API endpoints
- Set up Sphinx documentation generation
- Created getting started guide

### Testing
- Verified documentation builds successfully
- Tested API examples in docstrings
- All existing tests pass

Fixes #123
```

## Reporting Issues

When reporting bugs or requesting features:

1. **Check existing issues** first
2. **Use clear, descriptive titles**
3. **Provide reproduction steps** for bugs
4. **Include relevant logs** or error messages
5. **Suggest solutions** if you have ideas

## Community Guidelines

- **Be respectful** and inclusive
- **Help others** learn and contribute
- **Follow Microsoft's** Open Source Code of Conduct
- **Ask questions** if you're unsure about anything

## Getting Help

- **Check the documentation** first
- **Search existing issues** for similar problems
- **Ask questions** in GitHub Discussions
- **Tag maintainers** for urgent issues
