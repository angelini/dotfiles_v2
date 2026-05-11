# Plan 09: Debian Docker Support (Trixie)

This plan implements the ability to generate a `Dockerfile` for the `debian` environment, targeting `debian:trixie`.

## Context

We want to allow the Debian build to generate a `Dockerfile` that can be used to build a development container. This container will run the `setup.sh` script during its build phase to provide a consistent CLI environment.

## Container-Specific Logic

1.  **Exclusions**: The following components will be skipped in the Docker build to keep the image lightweight and focused on core CLI productivity:
    - `fonts` (UI-specific)
    - `git_signing` (host-responsibility)
    - `aws`, `gcloud` (Cloud SDKs)
    - `rust`, `node_fnm`, `go_lang` (Language toolchains)
    - `python_tools` (Build toolchains)
    - `claude_code` (AI Agent)
2.  **Environment Variables**: `DEBIAN_FRONTEND=noninteractive` must be set.
3.  **User Management**: The Dockerfile should ideally create a non-root user (e.g., `alex`) to match the home directory assumptions in the components.
4.  **Shim Updates**: The `debian` shim needs to handle cases where `sudo` is missing (common in base images).

## Tasks

### 1. Update `src/dotgen/registry.py`

- Define `_CONTAINER_SKIP = {"fonts", "git_signing", "aws", "gcloud", "rust", "node_fnm", "go_lang", "python_tools", "claude_code"}`.
- Create a helper to filter components for the Docker environment.

### 2. Update `src/dotgen/render.py`

- Add `DOCKERFILE_TEMPLATE` targeting `debian:trixie`.
- Update `build_env` to emit `dist/debian/Dockerfile`.
- Logic for the Dockerfile:
  ```dockerfile
  FROM debian:trixie
  RUN apt-get update && apt-get install -y sudo curl git
  RUN useradd -m -s /bin/bash alex && echo "alex ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
  USER alex
  WORKDIR /home/alex
  COPY --chown=alex:alex . /home/alex/dotgen
  RUN cd /home/alex/dotgen && bash setup.sh deploy
  ```

### 3. Update `src/dotgen/shim.py`

- Update `install_package` to check for `sudo` and use `DEBIAN_FRONTEND=noninteractive`.
- Update `add_repo` for similar robustness.

### 4. Verification

- `just build-all`
- `docker build -t dotgen-trixie dist/debian/`
- `docker run -it dotgen-trixie bash`

## Critical Files

- `src/dotgen/render.py`
- `src/dotgen/shim.py`
- `src/dotgen/registry.py`

## Verification

- `just ci`
- `docker build dist/debian`
