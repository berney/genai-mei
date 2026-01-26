# genai-mei

**genai-mei** is a collection of ready‑to‑run generative‑AI services packaged as Docker images and orchestrated with Docker‑Compose.
The repository bundles a handful of popular models and utilities – LLaMA‑Swap, Perplexica, and a SearXNG search front‑end – providing a single, reproducible environment for experimenting with and deploying AI workloads.

Heavily inspired by https://github.com/VonSnickety/framework-ai-cachyos

Optimized for AMD Strix Halo w/ Radeon 8060S (gfx1151).
Runs 70B+ models using the 128GB unified memory.

---


## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation & Quick Start](#installation--quick-start)
- [Configuration](#configuration)
-   - [Docker Compose](#docker-compose)
-   - [Service‑specific config files](#service-specific-config-files)
- [Running the Services](#running-the-services)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---


## Overview

The repository is organised around a **Docker‑Compose** stack that brings together the following components:

| Component/Service    | Purpose                                                                  | Notes            |
|----------------------|--------------------------------------------------------------------------|------------------|
| `docker-compose.yml` | Orchestrates all services, defines networks and volumes                  | Orchestration    |
| `huggingface`        | HuggingFace `hf` CLI, used to download models, etc.                      | Bootstrapping    |
| `llama-swap`         | LLaMA‑Swap – a lightweight model‑swap utility for LLaMA families         | Default          |
| `perplexica`         | Perplexica is an AI-powered answering engine                             | Default          |
| `searxng`            | Self‑hosted meta‑search engine used by the AI agents (mainly Perplexica) | Default          |
| `open-webui`         | User-friendly AI Interface                                               | Non default      |
| `mistral-vibe`       | Mistral Vibe – a CLI‑driven coding‑assistant built on Devstral models    | Manual           |

All services expose HTTP APIs (or CLI entry points) that can be consumed by downstream applications or by the other services in the stack.

---


## Features

- **Modular Docker images** – each AI component lives in its own folder with a minimal Dockerfile.
- **Unified orchestration** – a single `docker-compose.yml` brings up the whole stack with one command.
- **Configurable per‑service** – YAML/TOML configuration files are mounted as volumes, making it easy to tweak model paths, ports, and runtime flags without rebuilding images.
- **Persisted data** – SQLite DB for Perplexica and volume mounts for model caches ensure data survives container restarts.
- **Ready for extension** – add new services by dropping a folder with a Dockerfile and updating `docker-compose.yml`.

---


## Prerequisites

- Docker Engine (>= 20.10) (or Podman)
- Docker‑Compose (v2 syntax, bundled with recent Docker releases)
- Optional: `git` for cloning the repository

---


## Installation & Quick Start

```bash
# Clone the repository
git clone https://github.com/your‑org/genai‑mei.git
cd genai‑mei

# Build and start all services (detached mode)
docker compose up
```

The command will:
1. Pull, falling back to building, each Docker image from its respective `Dockerfile`.
2. Start containers and expose the ports defined in `docker-compose.yml`.

You can verify that everything is running with:

```bash
docker compose ps
```

---


## Configuration

### Docker Compose

The top‑level `docker-compose.yml` defines the services, networks, and volumes.
Most runtime options (ports, environment variables, bind‑mounts) are declared there.
Feel free to edit the file to change host ports or to add extra environment variables.


### Service‑specific config files

- **HuggingFace** – this is ran manually to get the `hf` CLI to download models, etc. used for bootstrapping.
- **LLaMA‑Swap** – configuration lives in `llama-swap/config.yaml` - this defines models available.
- **Mistral‑Vibe** – primary settings are in `mistral-vibe/config.toml`.  Adjust the `model_path`, `api_key`, or logging options as needed.
- **Perplexica** – The config file `perplexica/data/config.json` has the base URL for SearxNG. Chat history etc stored in `perplexica/data/` is not tracked by git.
- **SearXNG** – tweak the search behaviour in `searxng/settings.yml`.

All config files are mounted read‑only into the containers, so changes take effect after a container restart (`docker compose restart <service>`).

---


## Running the Services

Below are the default ports (as defined in `docker-compose.yml`). Adjust them in the compose file if they clash with existing services on your host.

| Service         | Purpose          | Profile         | URL (containers)        | URL (host) |
|-----------------|------------------|-----------------|-------------------------|------------------------|
| `llama-swap`    | LLaMA‑Swap API   | default         | http://llama-swap:8080/ | http://localhost:8090/ |
| `perplexica`    | Perplexica UI    | default         | http://perplexica:3001/ | http://localhost:3001/ |
| `searxng`       | SearXNG UI       | default         | http://searxng:8080/    | http://localhost:8185/ |
| `open-webui`    | Open WebUI       | `open-webui`    | http://open-webui:8080/ | http://localhost:8080/ |
| `huggingface`   | Bootstrapping    | `huggingface`   | N/A                     | N/A                    |
| `minstral-vibe` | Mistral‑Vibe CLI | `minstral-vibe` | N/A                     | N/A                    |

You can interact with the HTTP services using your web browser, `xh`, `curl`, etc.

---


## Project Structure

```
genai-mei/
├── huggingface/            # HuggingFace CLI container
│   └── Dockerfile
├── llama-swap/             # LLaMA‑Swap service
│   ├── config.default.yaml
│   ├── config.jesse.yaml
│   ├── config.yaml
│   └── Dockerfile
├── mistral-vibe/           # Mistral Vibe coding‑assistant
│   ├── config.docker-compose.toml
│   ├── config.toml
│   └── Dockerfile
├── perplexica/             # AI powered answering engine
│   └── data/
│       ├── config.json
│       └── db.sqlite
├── searxng/                # Self‑hosted meta‑search engine
│   └── settings.yml
├── docker-compose.yml      # Orchestrates all services
└── LICENSE                 # Project license
```

---


## Architecture

* I've tried to capture everything as code (Infrastructure as Code).
* I've tried to containerise everything to make it agonostic to the host OS.
* Centralised on docker-compose - the models are services in docker-compose, and llama-swap starts and stops docker-compose services.
  This means you can start and stop models via `docker compose` yourself - you could drop llama-swap.
  Using llama-swap gives niceness like shutdown unused models, freeing resources, and saving energy.
* The podman user socket is mounted into `llama-swap` container.
  The `podman` and `docker-compose` binaries have been installed.
  The parent directory of the docker-compose.yml on the host should match inside the container (e.g. both `genai-mei`), as the container names are based on the parent.
* Built on a podman system.
  Intend in future to support docker engine, but some changes probably needed atm to get it working.



## Contributing

This repo mainlys serves myself and to share with others what I did and how I did it.
Ideas are welcomed, I'm always looking to improve things, if it fits my vision.

---


## License

This project is licensed under the **AGPL-3.0 License** – see the `LICENSE` file for details.

---
