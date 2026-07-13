# HASTE - High-speed Assessment and Satellite Tracking for Emergencies

Welcome to the HASTE (High-speed Assessment and Satellite Tracking for Emergencies) documentation.

HASTE is an AI-powered disaster assessment framework that leverages satellite imagery and remote sensing data to provide rapid assessment capabilities for humanitarian response teams.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/microsoft/haste/blob/main/LICENSE.txt)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Features

- **Automated Disaster Assessment**: AI-powered analysis of satellite imagery for damage assessment
- **Multi-Source Imagery Support**: Compatible with various satellite imagery providers (Vantor, Planet)
- **Real-time Processing**: Fast processing of pre and post-event imagery with Cloud Optimized GeoTIFF (COG) output
- **Web Interface**: User-friendly React-based interface for project management, labeling, and visualization
- **Azure Cloud Integration**: Scalable cloud-based processing with Azure Functions, Azure Batch, Blob Storage, and Data Lake
- **ML Training & Inference**: End-to-end model training and inference pipelines with GPU support via Azure Batch
- **Tile Serving**: Built-in TiTiler-based tile server for serving Cloud Optimized GeoTIFFs

## System Components

| Component | Technology | Description |
|-----------|-----------|-------------|
| **UI** | React + Vite | Single-page app for project management, labeling, and visualization |
| **REST API** (`hastefuncapi`) | Python Azure Functions | HTTP endpoints for CRUD operations |
| **Queue Workers** (`hastefuncqueues`) | Python Azure Functions | Queue-triggered functions for async processing |
| **Tile Server** (`titilerfuncapi`) | TiTiler + FastAPI | Cloud Optimized GeoTIFF tile serving |
| **Core Library** (`hastegeo`) | Python package | Shared models, processors, data layers, runners, and utilities |

## Where to start

- **New to HASTE?** Start with the {doc}`User Guide <usage/overview>` to see how the
  application works end to end — creating projects, adding imagery, labeling, training a
  model, and viewing results.
- **Want to run it locally?** Follow {doc}`Local Development <setup/local-dev>` to bring up
  the full stack with Docker Compose.
- **Deploying to Azure?** See the {doc}`Deployment Guide <deployment>` for the one-step
  `azd up` deployment, and the {doc}`Configuration Guide <configuration>` for the full
  settings matrix.
