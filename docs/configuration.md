# Configuration reference

The toolkit loads **JSON only**. This document states which files are read,
by which command, and what each key does.

## Configuration directory

The configuration directory is resolved in this order:

1. the `WORKSTATION_CONFIG` environment variable, when it is set;
2. otherwise the `config/` directory beside the installed package root.

Every path below is relative to that directory.

## Files

| File | Read by | Purpose | In git |
|---|---|---|---|
| `local.json` | the toolkit generally | Device-local settings | No — ignored |
| `repos.json` | `repos`, `toolchain`, `git-identity`, `git-worktrees`, `android-cleanup-plan` | Repository roots and exclusions | No — ignored |
| `projects.json` | `project`, and `loc --project` | Configured project commands | No — ignored |
| `repos.json.example` | nothing | Template for `repos.json` | Yes |
| `projects.json.example` | nothing | Template for `projects.json` | Yes |
| `repos.toml.example` | nothing | Illustrative only | Yes |
| `projects.toml.example` | nothing | Illustrative only | Yes |
| `toolkit.toml.example` | nothing | Illustrative only | Yes |

The three `*.toml.example` files are commented reference material. They are
not parsed, not merged and not read by any command. They exist so that a
reader can see the shape of the settings without a TOML parser being
introduced into the toolkit.

## `repos.json`

```json
{
  "repos": ["/absolute/path/to/project"],
  "exclude_patterns": [".brv", ".gradle", "node_modules", ".venv", "vendor"]
}
```

| Key | Type | Meaning |
|---|---|---|
| `repos` | list of strings | Absolute paths to the repositories to audit |
| `exclude_patterns` | list of strings | Directory names skipped while walking a repository |

`exclude_patterns` matches directory names, not path fragments, so `.venv`
excludes any directory called `.venv` at any depth.

A missing `repos.json` is not an error. The repository-scoped commands then
report that no repositories are configured.

`loc` does not read `repos.json`. It audits either a directory given directly
with `--path`, or a configured project named with `--project`, which is
resolved through `projects.json`.

## `projects.json`

```json
{
  "projects": [
    {
      "name": "example-project",
      "path": "/absolute/path/to/project",
      "commands": {
        "test": {"argv": ["python", "-m", "pytest"]},
        "lint": {"argv": ["python", "-m", "ruff", "check", "."]}
      }
    }
  ]
}
```

| Key | Type | Meaning |
|---|---|---|
| `projects` | list of objects | The configured projects |
| `projects[].name` | string | The name used on the command line |
| `projects[].path` | string | Absolute path to the project directory |
| `projects[].commands` | object | The actions this project exposes |
| `projects[].environment` | object | Extra environment variables for this project's commands |
| `projects[].timeouts` | object | Per-action timeout in seconds. Default 900 |
| `projects[].type` | string | A free-form label reported in the status output |

### Command forms

Each action is one of the following.

**`argv` — an argument list, executed without a shell.** This is the
recommended form.

```json
{"argv": ["python", "-m", "pytest"]}
```

Every element is passed literally to the operating system. A value such as
`"release && rm -rf build"` is therefore data and never syntax.

**`shell` — a shell string, interpreted by the platform shell.**

```json
{"shell": "npm run build && npm test"}
```

This mode requires an explicit trusted-shell opt-in that is deliberately
**not** part of this file, so that somebody able to edit the configuration
cannot grant themselves the right to run arbitrary shell code. The opt-in is
`--allow-shell` on the command line, or `WORKSTATION_ALLOW_SHELL=1` in the
environment for unattended runs. Without it, a shell-mode command is refused
and nothing is executed.

**A legacy plain string** is accepted and classified automatically:

- a string with no shell syntax — for example `"python -m pytest"` — is split
  into an argument list and executed without a shell. The observable result is
  the same as before, but with no shell involved;
- a string that uses shell syntax — pipes, redirects, `&&`, globs, variable
  expansion, and so on — is treated as a shell command and needs the
  `--allow-shell` opt-in. Convert it to `{"argv": [...]}` to avoid the shell.

A command value accepts **only** the keys `argv` and `shell`. Any other key
is a configuration error and is reported as such rather than executed. A
command may not define both keys, and must define at least one.

### Project-level keys

These keys sit alongside `commands`, on the project object itself.

| Key | Type | Meaning |
|---|---|---|
| `environment` | object | Additional environment variables for every command of this project |
| `timeouts` | object | Timeout in seconds, per action |
| `type` | string | A free-form label reported in the project status output |

```json
{
  "name": "example-project",
  "path": "/absolute/path/to/project",
  "environment": {"CI": "1", "RETRIES": 3},
  "timeouts": {"test": 1800, "lint": 300},
  "commands": {
    "test": {"argv": ["python", "-m", "pytest"]}
  }
}
```

`environment` values may be strings, numbers or booleans; a boolean becomes
`true` or `false` and a number becomes its decimal text. Keys must be
non-empty and must not contain `=` or a null byte.

`timeouts` maps an action name to a whole number of seconds. An action with
no entry uses the default of **900 seconds**. A timeout must be a positive
integer.

The command always runs in the project's `path` directory; there is no
separate working-directory key.

Command, environment and timeout values are validated before anything runs.
Malformed configuration is reported as an error rather than executed.

### Actions

The recognised action names are `status`, `test`, `lint`, `clean` and
`web-test`. An action that a project does not define is reported as not
configured; it is never silently ignored.

## `local.json`

Device-local settings. The toolkit loads it when it exists and proceeds
without it when it does not. It is gitignored, so it stays on the machine that
owns those paths.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `WORKSTATION_CONFIG` | the toolkit generally | Configuration directory. Overrides the default `config/` location |
| `HERMES_HOME` | `hermes`, `hermes-maintain`, `kanban` | Hermes installation root, or the active profile directory |
| `HERMES_PROFILE_DIR` | `hermes`, `hermes-maintain`, `kanban` | Exact Hermes profile directory. Takes precedence over `HERMES_HOME` |
| `HERMES_KANBAN_HOME` | `kanban` | Exact Kanban boards directory |
| `WORKSTATION_ALLOW_SHELL` | `project` | Set to `1` to permit shell-mode project commands |
| `JAVA_HOME` | `toolchain` | Java installation root |
| `ANDROID_HOME`, `ANDROID_SDK_ROOT` | `toolchain`, `android-cleanup-plan` | Android SDK root |

### Hermes path resolution

`HERMES_PROFILE_DIR` is used directly when it is set.

Otherwise `HERMES_HOME` is read. It may point either at the Hermes
installation root or at an active profile directory. When it points at a
`profiles/<name>` directory it is used as the profile directory directly.
When it points anywhere else, `profiles/coordinator` is appended.

On Windows the default `HERMES_HOME` is `%LOCALAPPDATA%\hermes`.

## Configuration is not merged

Configuration files are read independently. `local.json` does not override
`repos.json` or `projects.json`, and the `*.toml.example` files contribute
nothing at all. There is no layering and no partial merge, so the effective
configuration for a command is always exactly the one file that command
reads.
