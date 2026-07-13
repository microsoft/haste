# HASTE Documentation

This directory contains the Jupyter Book documentation for the HASTE project.

## Prerequisites

Install the documentation dependencies:

```cmd
cd docs
pip install -r requirements.txt
```

## Building Documentation

```cmd
cd docs
jb build .
```

## Viewing Documentation

After building, open `_build/html/index.html` in your browser.

## Documentation Structure

- `_config.yml` - Jupyter Book configuration
- `_toc.yml` - Table of contents / page structure
- `conf.py` - Extra Sphinx configuration (sys.path, mocks for autodoc)
- `intro.md` - Main landing page
- `usage/` - User Guide: how to use the application (overview, projects, image layers, labeling, model training, results, model catalog)
- `setup/` - Setup guides (`local-dev.md` for the Docker stack)
- `deployment.md` - One-step azd production deployment guide
- `security-configuration.md` - Secure configuration guidance
- `architecture.md` - System architecture overview
- `api-overview.md` - API overview and reference
- `development.md` - Development practices
- `contributing.md` - Contribution guidelines
- `api/` - API reference documentation (hastefuncapi, hastefuncqueues, titilerfuncapi)
- `hastelib/` - Core library documentation (config, models, processors, data layers, runners, utils, workflows)
- `azure_functions_simple.py` - Custom Sphinx extension for Azure Functions documentation
- `requirements.txt` - Documentation dependencies
