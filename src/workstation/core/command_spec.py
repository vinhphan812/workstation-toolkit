"""Parsing and validation for configured commands.

Configured project commands are *executable code*.  This module turns a
configured command value into an explicit :class:`CommandSpec` so the caller
never has to guess whether a value is a shell string or an argv list.

Two execution modes exist:

``argv``
    The command is a list of arguments.  It is executed without a shell, so
    every element is passed literally to the operating system.  Shell
    metacharacters inside an argument are data, never syntax.

``shell``
    The command is a shell string and needs a shell to be interpreted.
    Executing it requires an explicit trusted-shell opt-in from the caller
    (see :mod:`workstation.modules.projects`).

Legacy plain-string commands are migrated automatically:

* a string without shell syntax is split into an argv list and executed
  without a shell (same observable result for ordinary commands);
* a string containing shell syntax requires the trusted-shell opt-in and is
  reported with a migration hint.
"""
from __future__ import annotations
from dataclasses import dataclass, field

#: Characters that only make sense to a shell.  A configured command that
#: contains one of these (outside of quotes) needs shell interpretation and
#: therefore the explicit trusted-shell opt-in.
#:
#: ``!`` is deliberately absent: it is not expanded by non-interactive shells.
#: ``?``/``*``/``[``/``]``/``{``/``}`` are glob and brace patterns, ``%`` and
#: ``^`` are Windows ``cmd.exe`` expansions, ``~`` is home-directory
#: expansion, ``$``/``\```` are POSIX expansions, and ``(``/``)`` are
#: POSIX subshell operators.
SHELL_METACHARACTERS = frozenset(';|&$><`*?[]{}~%^()\n')

#: Configuration keys accepted inside a structured command value.
COMMAND_KEYS = frozenset({'argv', 'shell'})


class CommandConfigError(ValueError):
    """Raised when a configured command or environment value is malformed."""


@dataclass(frozen=True)
class CommandSpec:
    """A validated, explicitly-typed command ready to be executed."""

    mode: str
    argv: tuple[str, ...] = ()
    shell: str = ''
    source: str = 'legacy'
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def requires_trusted_shell(self) -> bool:
        return self.mode == 'shell'

    @property
    def display(self) -> str:
        if self.mode == 'shell':
            return self.shell
        return ' '.join(self.argv)

    def as_report(self) -> dict:
        report = {
            'mode': self.mode,
            'source': self.source,
            'requires_trusted_shell': self.requires_trusted_shell,
        }
        if self.mode == 'shell':
            report['shell'] = self.shell
        else:
            report['argv'] = list(self.argv)
        if self.notes:
            report['notes'] = list(self.notes)
        return report


def contains_shell_syntax(text: str) -> bool:
    """Return True when *text* uses shell syntax outside of quoted sections."""
    quote = ''
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = ''
            elif char == '\\' and quote == '"':
                index += 1
        elif char in ('"', "'"):
            quote = char
        elif char in SHELL_METACHARACTERS:
            return True
        index += 1
    return False


def split_plain_command(text: str) -> list[str]:
    """Split a plain command string into argv elements without a shell.

    Quoting is honoured, backslashes are preserved (so Windows paths survive
    intact), and no expansion of any kind is performed.  The result is a
    literal argument vector, not a command line for a shell to interpret.
    """
    if not text.strip():
        raise CommandConfigError('command is empty')
    tokens: list[str] = []
    current = ''
    started = False
    quote = ''
    index = 0
    while index < len(text):
        char = text[index]
        if quote == '"':
            # Inside double quotes a backslash escapes a quote or a backslash;
            # every other backslash is a literal character (Windows paths).
            if char == '\\' and index + 1 < len(text) and text[index + 1] in ('"', '\\'):
                current += text[index + 1]
                index += 2
                continue
            if char == '"':
                quote = ''
            else:
                current += char
            index += 1
            continue
        if quote == "'":
            # Single quotes are literal all the way to the closing quote.
            if char == "'":
                quote = ''
            else:
                current += char
            index += 1
            continue
        if char in ('"', "'"):
            quote = char
            started = True
        elif char == '\\' and index + 1 < len(text) and text[index + 1] in ('"', "'"):
            # An escaped quote outside quotes is a literal quote character.
            # Every other backslash stays literal so Windows paths survive.
            current += text[index + 1]
            started = True
            index += 2
            continue
        elif char.isspace():
            if started:
                tokens.append(current)
                current = ''
                started = False
        else:
            current += char
            started = True
        index += 1
    if quote:
        raise CommandConfigError('command has an unterminated quote')
    if started:
        tokens.append(current)
    if not tokens:
        raise CommandConfigError('command is empty')
    return tokens


def parse_command(value: object) -> CommandSpec:
    """Validate a configured command value and return its :class:`CommandSpec`."""
    if isinstance(value, str):
        if contains_shell_syntax(value):
            return CommandSpec(
                mode='shell',
                shell=value,
                source='legacy',
                notes=(
                    'configured command uses shell syntax and runs as executable code',
                    'migrate to {"argv": [...]} to run it without a shell',
                ),
            )
        return CommandSpec(
            mode='argv',
            argv=tuple(split_plain_command(value)),
            source='legacy',
            notes=('configured command was migrated to argv execution (no shell)',),
        )
    if isinstance(value, dict):
        unknown = sorted(set(value) - COMMAND_KEYS)
        if unknown:
            raise CommandConfigError(
                f"unknown command key(s): {', '.join(unknown)}; expected one of {', '.join(sorted(COMMAND_KEYS))}"
            )
        has_argv = 'argv' in value
        has_shell = 'shell' in value
        if has_argv and has_shell:
            raise CommandConfigError('command must use either "argv" or "shell", not both')
        if not has_argv and not has_shell:
            raise CommandConfigError('command must define "argv" or "shell"')
        if has_shell:
            shell = value['shell']
            if not isinstance(shell, str) or not shell.strip():
                raise CommandConfigError('"shell" must be a non-empty string')
            return CommandSpec(
                mode='shell',
                shell=shell,
                source='config',
                notes=('configured command is executable code and requires trusted-shell opt-in',),
            )
        argv = value['argv']
        if not isinstance(argv, (list, tuple)):
            raise CommandConfigError('"argv" must be a list of strings')
        if not argv:
            raise CommandConfigError('"argv" must not be empty')
        elements: list[str] = []
        for element in argv:
            if not isinstance(element, str):
                raise CommandConfigError('"argv" entries must all be strings')
            if not element:
                raise CommandConfigError('"argv" entries must not be empty')
            elements.append(element)
        return CommandSpec(mode='argv', argv=tuple(elements), source='config')
    raise CommandConfigError(
        f'command must be a string or an object with "argv" or "shell", got {type(value).__name__}'
    )


def parse_environment(mapping: object) -> dict[str, str]:
    """Validate a configured environment mapping and return string values."""
    if mapping is None:
        return {}
    if not isinstance(mapping, dict):
        raise CommandConfigError('environment must be an object of string values')
    validated: dict[str, str] = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not key:
            raise CommandConfigError('environment keys must be non-empty strings')
        if '=' in key or '\x00' in key:
            raise CommandConfigError(f'invalid environment key: {key!r}')
        if isinstance(value, bool):
            text = 'true' if value else 'false'
        elif isinstance(value, (int, float)):
            text = str(value)
        elif isinstance(value, str):
            text = value
        else:
            raise CommandConfigError(
                f'environment value for {key!r} must be a string, number or boolean, got {type(value).__name__}'
            )
        if '\x00' in text:
            raise CommandConfigError(f'invalid environment value for {key!r}')
        validated[key] = text
    return validated


def parse_timeout(mapping: object, action: str, default: int = 900) -> int:
    """Validate the timeout configured for *action*."""
    if mapping is None:
        return default
    if not isinstance(mapping, dict):
        raise CommandConfigError('timeouts must be an object of action -> seconds')
    value = mapping.get(action, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandConfigError(f'timeout for {action!r} must be an integer number of seconds')
    if value <= 0:
        raise CommandConfigError(f'timeout for {action!r} must be greater than zero')
    return value
