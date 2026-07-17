default:
    @just build-all

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

# env: debian | macos
test-vm env="debian":
    uv run pytest tests/test_vm_integration.py -v -m vm -k {{env}}

test-vm-all:
    uv run pytest tests/test_vm_integration.py -v -m vm

clean:
    rm -rf dist

shellcheck:
    shellcheck -s bash --exclude=SC1090,SC1091 dist/*/*.sh dist/*/.bashrc

ci: lint typecheck test build-all shellcheck
