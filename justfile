default:
    @just --list

build env:
    uv run python -m dotgen build {{env}}
    @just package {{env}}

build-all:
    uv run python -m dotgen build-all
    @just package-all

package env:
    COPYFILE_DISABLE=1 tar --no-xattrs -C dist -czf dist/{{env}}.tar.gz {{env}}

package-all:
    for e in $(uv run python -m dotgen list-envs); do just package "$e"; done

install env:
    bash dist/{{env}}/setup.sh deploy

deploy env target:
    just build "{{env}}"
    scp -- "dist/{{env}}.tar.gz" "{{target}}:"
    ssh -t -- "{{target}}" 'set -e; rm -rf -- "{{env}}"; tar xzf "{{env}}.tar.gz"; bash "{{env}}/setup.sh" deploy; rm -f -- "{{env}}.tar.gz"'

send-secrets env target:
    uv run python -m dotgen send-secrets "{{env}}" "{{target}}" --from-env

list:
    uv run python -m dotgen list-envs

lint:
    uv run ruff check src tests

fmt:
    uv run ruff format src tests

typecheck:
    uv run ty check src

test:
    uv run pytest

_vm-test-preflight:
    @if [ "${DOTGEN_PI_SANDBOX:-}" = 1 ]; then echo "VM tests require host virtualization access and cannot run inside pi-sandbox. Rerun from a regular terminal or start Pi with pi-unsafe." >&2; exit 2; fi

# env: debian | debian-docker | macos
test-vm env="debian": _vm-test-preflight
    case "{{env}}" in debian) selector=debian ;; debian-docker) selector=docker ;; macos) selector=macos ;; *) echo "unknown VM environment: {{env}}" >&2; exit 2 ;; esac; uv run pytest tests/test_vm_integration.py -v -m vm -k "$selector"

test-vm-all: _vm-test-preflight
    uv run pytest tests/test_vm_integration.py -v -m vm

clean:
    rm -rf dist

shellcheck:
    shellcheck -s bash --exclude=SC1090,SC1091 dist/*/*.sh dist/*/.bashrc dist/debian/config/tmuxinator/dotgen-agent-session dist/*/config/herdr/herd-agent

ci: lint typecheck test build-all shellcheck
