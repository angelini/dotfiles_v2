# Plan 20 — one-time macOS migration report

## Status

Implemented and independently verified. This plan creates a small, read-only report to support one migration from the legacy dotfiles repository to `dotfiles_v2`. It does not attempt to build a reusable drift-management system.

Host cutover still requires explicit approval.

## Goal

Before migration, answer four practical questions:

1. Which `dotfiles_v2` config files differ from the current host?
2. Which expected commands and applications are missing?
3. Which obvious host-only config directories may be worth keeping?
4. Which legacy aliases and functions should be copied before the old links are replaced?

The report is advisory. It does not need to reproduce the host perfectly, account for every installed application, or prevent loss of unselected configuration.

## Deliberate tradeoffs

This is a one-time migration, so the implementation will favor a short, understandable script over durable infrastructure.

- No managed-state schema or typed resource framework.
- No inventory database or migration policy file.
- No worktree, vendor, stage, or report fingerprints.
- No deployment receipts or historical change tracking.
- No version or provider enforcement when a required command or application is already present.
- No requirement to classify every package, application, or config directory.
- No retained staging artifact or backup requirement.
- No rollback design in this plan.

Unknown or unselected host configuration may be overwritten or abandoned during cutover. That is acceptable for this migration.

## Known host state

The legacy repository is `/Users/alex/repos/dotfiles`. Five host paths currently link into it:

- `~/.aliases`
- `~/.bashrc`
- `~/.gitconfig`
- `~/.gitignore_global`
- `~/.config/starship.toml`

The linked legacy files have local changes, so legacy Git `HEAD` is not the source of truth. Any helper worth keeping must be copied from the live files.

Host-only config review is complete: the duplicate `~/.config/ghostty` and `~/.config/git` trees are dropped, while `~/.config/tcld`, `~/.config/ghosthub`, and `~/.config/kwt` are excluded from migration and left untouched. The btop, cmux, htop, hunk, Kitty, opencode, wt, and Zellij roots are explicitly excluded from migration and may be removed from the host. OrbStack is the required macOS container runtime and replaces Docker Desktop; the two applications must not be installed in parallel. OrbStack and Docker runtime/config roots are not migration inputs. Cloud credentials, Kubernetes state, SSH keys, authentication files, sessions, caches, and histories are runtime state rather than migration inputs.

The complete Gemini-capable Pi `models.json` is now owned by the private `agent-config` repository. It uses Pi's `google-vertex` provider with Application Default Credentials and no Gemini API key. The sandbox maps `GCP_PROJECT_ID` to `GOOGLE_CLOUD_PROJECT`, uses Vertex location `europe-west4`, and exposes only the ADC file from gcloud state. Approved cutover replaces the live file with this canonical version.

Known legacy shell decisions include:

- system helpers: `sct`, `sc`
- gcloud and IAM helpers
- work-specific Kubernetes helpers
- LogCLI and Temporal helpers
- repository/worktree helpers: `cd_tf`, `dev`, `icc`, `cc`, `wtgo`, `wtgo-pi`
- Doppler comparison helpers
- the changed meaning of `ip`
- user-scoped versus project-local Serena registration

## Design

### Add one report command

Add a single command:

```text
dotgen macos-report --stage PATH
```

The caller rebuilds `dist/macos` immediately before running the report and passes that directory as `--stage`. The command does not rebuild, deploy, save inventory state, or write a report file. It prints a concise report to stdout.

The command uses small explicit tables for this migration rather than introducing new declarations across every component.

### Config checks

Use this fixed table rather than discovering resources dynamically:

| Stage path | Host path | Check |
| --- | --- | --- |
| `.bashrc` | `~/.bashrc` | exact |
| `alias.sh` | `~/.aliases` | exact |
| `config/bash/bash_profile` | `~/.bash_profile` | exact |
| `config/git/gitconfig` | `~/.gitconfig` | manual |
| `config/git/gitignore_global` | `~/.gitignore_global` | exact |
| `config/npm/npmrc` | `~/.npmrc` | manual |
| `config/starship/starship.toml` | `~/.config/starship.toml` | exact |
| `config/tmux/tmux.conf` | `~/.tmux.conf` | exact |
| `config/helix/config.toml` | `~/.config/helix/config.toml` | exact |
| `config/gh/config.yml` | `~/.config/gh/config.yml` | exact |
| `config/aws/config` | `~/.aws/config` | exact |
| `config/ghostty/config` | `~/Library/Application Support/com.mitchellh.ghostty/config` | exact |
| `config/zed/settings.json` | `~/.config/zed/settings.json` | exact |
| `config/zed/keymap.json` | `~/.config/zed/keymap.json` | exact |
| `config/claude/` | `~/.claude/` | managed tree, excluding `settings.json` |
| `config/pi/agent/` | `~/.pi/agent/` | managed tree, excluding `settings.json` |
| `config/pi/sandbox/pi-macos.sb` | `~/.config/pi/sandbox/pi-macos.sb` | exact |
| `config/pi/sandbox/pi-sandbox.sh` | `~/.local/bin/pi-sandbox` | exact |
| `config/pi-angelini/` | `~/repos/pi-angelini/` | managed tree |
| `config/managed-settings/claude.json` | `~/.claude/settings.json` | manual |
| `config/managed-settings/pi.json` | `~/.pi/agent/settings.json` | manual |

Exact checks report `match`, `different`, `missing`, or `type conflict`. Managed-tree checks apply those statuses only to files present in the stage and ignore extra host files. Manual checks report `manual review` when the target is a regular file, otherwise `missing` or `type conflict`. Do not compare or report file modes; approved cutover uses the modes currently emitted by the deployment helpers.

The five known legacy destinations (`~/.aliases`, `~/.bashrc`, `~/.gitconfig`, `~/.gitignore_global`, and `~/.config/starship.toml`) are a bounded exception to normal non-following behavior. The report detects each link with `lstat`, follows it only to inspect the live regular-file content, and annotates its ordinary status with `legacy symlink`. A missing target, symlink chain, or non-regular target is a type conflict. All other destination symlinks are type conflicts and must not be followed, including symlinks encountered in managed trees.

At approved cutover, deployment replaces each known legacy destination symlink with a regular copied file, matching the existing `install_config` behavior used for Debian. Replacing the link must not modify its legacy-repository target. Template installs must likewise replace the destination link atomically with the rendered regular file. Managed-tree deployment may replace only leaf symlinks that correspond to staged regular files; destination roots, directory ancestors, directory entries, retired entries, and non-file conflicts remain fail-closed. Add deployment tests covering ordinary, template, and managed-tree leaf replacement while preserving former targets.

Do not compare `setup.sh` or `os_shim.sh`; they have no host config destination. Do not print file contents or unified diffs.

### Confirmed config dispositions

- `~/.bashrc`: adopt the generated v2 file, drop legacy-only behavior, and move the host's OrbStack shell initialization here behind a readability guard.
- `~/.bash_profile`: adopt the generated v2 file so it only sources `~/.bashrc` when readable; the OrbStack initialization moves to `~/.bashrc`.
- `~/.aliases`: adopt the generated v2 file, with the previously selected public and private-overlay helpers added separately.
  - Keep `k8s_secrets` as a value-printing helper; decoding and printing secret values is its intended purpose.
  - Remove `kca`, `kcn`, and `kcr`; their legacy and generated meanings are no longer needed.
- `~/.gitconfig`: adopt the generated v2 file; drop the host-only color setting and GitHub HTTPS-to-SSH URL rewrite.
- `~/.gitignore_global`: adopt the generated v2 file, including its additional Node and Claude local-settings exclusions.
- `~/.npmrc`: adopt the generated secret template; render `NPM_TOKEN` from the target secrets file.
- `~/.config/starship.toml`: keep generated v2 as the public fallback. The private repository installs a complete merged Starship config containing the host-specific Kubernetes context map, and its shell overlay sets `STARSHIP_CONFIG` to that private file because Starship does not support config-fragment imports.
- `~/.tmux.conf`: install the generated v2 config; the host currently has no tmux config.
- `~/.config/helix/config.toml`: adopt the generated v2 config; drop the live-only unmanaged Yazi shortcut.
- `~/.config/gh/config.yml`: adopt the generated v2 config; drop GH-generated metadata, empty fields, and the host-only editor-prompt preference.
- `~/.aws/config`: adopt the generated v2 config; drop the host-only S3 addressing-style setting.
- Ghostty: install the generated macOS config after adding the host candidate's explicit full-opacity, no-blur, and full-unfocused-split-opacity settings; do not migrate the duplicate `~/.config/ghostty` tree.
- Zed: adopt both generated v2 files; drop the host-only remote SSH connection from `settings.json` and the inert empty context block from `keymap.json`.
- Claude: replace managed-tree symlinks with generated regular files and apply the generated settings patch while preserving host-only settings.
- Pi: adopt all generated content—install the canonical managed agent tree as regular files, apply the settings patch while preserving `lastChangelogVersion`, retain the matching `pi-angelini` tree, and install the missing sandbox profile and launcher.
- `~/.config/git`: do not migrate the duplicate directory; its only ignore rule is already present in the adopted generated global ignore file.
- `~/.config/tcld`: exclude the directory from migration because it contains only an empty feature list and credential/runtime token state; leave the existing host directory untouched.
- `~/.config/ghosthub` and `~/.config/kwt`: exclude both unclassified directories from migration and leave them untouched.
- Serena: register the MCP server at user scope. Registration checks and the SessionStart reminder must recognize user scope rather than mistaking an existing local registration for a global one. During approved cutover, add and verify the user-scoped server before removing the two higher-precedence local duplicates.

### Command and application checks

Use a direct `PATH` lookup equivalent to `command -v`, without launching a shell, for these explicitly selected user-facing commands managed by the macOS components:

- shell and core tools: `bash`, `git`, `delta`, `jq`, `yq`, `fzf`, `rg`, `fd`, `eza`, `bat`, `tree`, `vim`, `htop`, `btop`, `cloc`, `gpg`;
- terminal and shell tools: `stinkpot`, `tmux`, `mosh`, `hx`, `starship`, `shellcheck`, `zoxide`;
- Kubernetes tools: `kubectl`, `helm`, `k9s`, `kubectx`, `kubens`, `kubie`;
- language and agent tools: `uv`, `claude`, `gh`, `cargo`, `rustc`, `fnm`, `node`, `npm`, `pi`, `pi-sandbox`, `psql`, `go`;
- cloud and container tools: `gcloud`, `aws`, `doppler`, `docker`.

The list intentionally keeps the `btop` command while leaving its configuration unmanaged. It excludes installer plumbing such as `envsubst`, `unzip`, and `bash-completion`. Mercurial is no longer required: remove the macOS `mercurial` dependency from the Go component and do not check `hg`.

Require these applications with direct `.app` path checks under `/Applications`:

- `Ghostty.app`
- `Zed.app`
- `Supacode.app`
- `OrbStack.app`

Also check that the conflicting `Docker.app` is absent. The Docker CLI supplied through OrbStack is required and does not count as Docker Desktop being installed in parallel.

Presence is otherwise sufficient. Do not inspect Homebrew records, compare versions, or require the same installation provider. For example, an existing Ghostty application or AWS CLI satisfies the report regardless of how it was installed. Keep these explicit lists pinned in focused tests; this one-time report does not derive them dynamically from package names.

### Host-only candidates

List only immediate child directories under `~/.config`. Do not scan `~/Library/Application Support`; its 132 immediate directories produced noise and no selected migration candidate. Direct checks for managed application configs and `/Applications` remain unchanged.

Use these explicit `~/.config` classifications:

- migration-review candidates: none;
- managed, authentication, or runtime exclusions: `1Password`, `argocd`, `configstore`, `docker`, `dotgen`, `gcloud`, `gh`, `ghosthub`, `helix`, `hister`, `kwt`, `orbstack`, `pi`, `tcld`, `zed`;
- explicitly dropped and removable: `btop`, `cmux`, `ghostty`, `git`, `htop`, `hunk`, `kitty`, `opencode`, `wt`, `zellij`.

`hunk` and `opencode` were failed tests and are not migration inputs. The `btop` command remains managed even though its config directory is dropped. List any future immediate `~/.config` directory not covered by these classifications as an unclassified review candidate. The output is a review aid, not an exhaustive inventory. No policy file or formal disposition is required.

### Legacy shell review

Parse only the live `~/.aliases` and `~/.bashrc` files as text; never source them. Recognize `alias name=...`, `name() {`, and `function name` declarations, including hyphenated function names such as `wtgo-pi`. Print the source path, line number, kind, and name so duplicate occurrences remain visible. Do not print bodies, store source hashes, or follow sourced files.

Review the list once and copy only helpers explicitly selected for retention. The confirmed selection is:

- public `dotfiles_v2` helpers: `gcp`, `get_project_roles`, `get_sa_bindings`;
- host-private overlay helpers: `gcn`, `gcd`, `gcg`, `gcr`, `gcs`, `install_optools`, `optools`.

All other legacy-only declarations may be dropped during cutover. For overlapping declarations, retain the live value-printing behavior of `k8s_secrets`; remove `kca`, `kcn`, and `kcr` rather than adopting either their legacy or generated meanings.

Store the private helpers at `~/repos/dotfiles-private/shell/private-aliases.sh`. Create the approved private files and idempotent installer there without initializing Git, configuring a remote, or making a commit. The installer copies the file, rather than symlinking it, to `~/.config/dotgen/private-aliases.sh` with mode `0600`. It must contain private identifiers only, never credential values.

The public generated `alias.sh` conditionally loads the installed overlay:

```bash
[ -r "$HOME/.config/dotgen/private-aliases.sh" ] && source "$HOME/.config/dotgen/private-aliases.sh"
```

A missing overlay is valid on hosts that do not use the private helpers. `dotfiles_v2` neither vendors nor fetches the private repository. Before cutover, install the private overlay and verify the seven selected declarations are available from a fresh shell.

## Implementation steps

### 0. Correct macOS component expectations

Add OrbStack as a required macOS component before cutover. Do not add Docker Desktop to the macOS environment, and do not register the Debian rootless Docker component for macOS. Remove the macOS-only `mercurial` dependency from the Go component; retain the `btop` package while leaving its configuration unmanaged. Make Serena's user-scoped registration check scope-aware and update its SessionStart reminder to recognize the user-scoped server. Add focused registration/render tests for these decisions.

### 1. Implement the one-time report

Add `src/dotgen/macos_report.py` containing:

- the explicit stage-to-host config mapping;
- selected command and application names;
- bounded host-only directory discovery;
- simple legacy alias/function name extraction;
- plain-text report rendering.

Keep the implementation macOS-specific. Do not generalize it for other environments.

### 2. Add the CLI entry point

Extend `src/dotgen/cli.py` with `macos-report --stage PATH`.

Operational failures return nonzero. Missing or different resources are findings, not command failures.

### 3. Add focused tests

Add `tests/test_macos_report.py` with fixtures covering:

- matching, different, missing, and wrong-type config targets;
- bounded comparison through the five known legacy file symlinks;
- rejection without traversal of all other symlinks, including managed-tree entries;
- generated directory files while ignoring extra host runtime files;
- secret-templated targets without content disclosure;
- present and missing commands/applications;
- bounded host-only candidate discovery;
- legacy alias/function name extraction;
- no writes to the inspected fixture home.

Avoid building a broad security, race-detection, policy-validation, or stale-input test matrix for this one-time tool.

### 4. Run the report once

After CI passes:

1. Rebuild the current macOS output with `just build-all`.
2. Run `uv run dotgen macos-report --stage dist/macos`.
3. Review the concise report.
4. Confirm the three public legacy helpers and selected Ghostty settings are present in `dotfiles_v2`, with no host-only review candidates remaining.
5. Confirm the seven private helpers and complete private Starship config exist under `dotfiles-private`, install the regular overlay files, and verify a fresh shell loads them.
6. Rebuild and rerun the report if those choices change generated output.
7. Approve cutover separately, accepting that unselected configuration may be lost.

There is no requirement to retain the report or the exact stage after the migration decision.

## Safety constraints

The report command must not:

- use `sudo`;
- source shell files;
- install, remove, or update anything;
- access the network;
- write beneath the inspected home, `/Applications`, `/Library`, or Homebrew roots;
- print credentials, secret values, private keys, file contents, or content diffs.

Writing build output to `dist/macos` before the report is expected and is outside the inspected host paths.

## Out of scope

- Perfect host reproduction.
- Exhaustive package or application inventory.
- Version and provider drift.
- Formal classifications or migration policy files.
- Backups, rollback, and retained artifacts.
- Deployment, package changes, login-shell changes, key creation, or external service registration.

## Validation

```bash
just ci
git diff --check
git status --short
```

## Open decisions

- When to approve the destructive cutover.

## End state

A small command reports the obvious differences between the freshly built macOS output and the current host. The report supports one manual keep-or-drop review, after which cutover can proceed with no promise of preserving unselected configuration. The proposed long-lived inventory, fingerprinting, policy, and change-tracking machinery is not introduced.
