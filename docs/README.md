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
- `architecture.md` - System architecture overview
- `getting-started.md` - Installation and setup guide
- `api-overview.md` - API overview and reference
- `deployment.md` - Deployment guide
- `development.md` - Development practices
- `contributing.md` - Contribution guidelines
- `api/` - API reference documentation (hastefuncapi, hastefuncqueues, titilerfuncapi)
- `hasteutils/` - Core library documentation (config, models, processors, data layers, runners, utils, workflows)
- `azure_functions_simple.py` - Custom Sphinx extension for Azure Functions documentation
- `requirements.txt` - Documentation dependencies
