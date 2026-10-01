"""Generate shell completion scripts for the command line tools from their argparse parser."""

import argparse
import os

SHELLS = ("bash", "zsh")

# Completers that cannot be derived from the parser and must be declared per option.
SSH_HOST = "ssh_host"
FILE = "file"

# Completer names derived from the parser itself.
FLAG = "flag"
CHOICES = "choices"
VALUE = "value"
HELP = "help"

HOST_LIST_FLAG = "--list-ssh-hosts"

BASH_TEMPLATE = """\
@FUNC@() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    case "$prev" in
@ARMS@    esac

    COMPREPLY=($(compgen -W "@FLAGS@" -- "$cur"))
}
complete -F @FUNC@ @PROG@
"""

ZSH_HEADER = """\
#compdef @PROG@
if (( ! $+functions[compdef] )); then
    autoload -Uz compinit
    compinit
fi
"""


def function_name(prog):
    return "_" + "".join(c if c.isalnum() else "_" for c in prog)


def option_specs(parser, completers=None):
    """Describe every option of a parser as (flags, completer, help, metavar, choices)."""
    completers = completers or {}
    specs = []
    for action in parser._actions:
        if not action.option_strings:
            continue

        flags = list(action.option_strings)
        override = next((completers[flag] for flag in flags if flag in completers), None)
        if isinstance(action, argparse._HelpAction):
            completer = HELP
        elif override:
            completer = override
        elif action.nargs == 0:
            completer = FLAG
        elif action.choices:
            completer = CHOICES
        else:
            completer = VALUE

        specs.append(
            {
                "flags": flags,
                "completer": completer,
                "help": action.help or "",
                "metavar": (action.metavar or action.dest).lower(),
                "choices": [str(choice) for choice in action.choices or ()],
            }
        )
    return specs


def render_bash_arm(pattern, body):
    lines = [f"        {pattern})"]
    lines.extend(f"            {line}" for line in body)
    lines.append("            ;;")
    return "\n".join(lines) + "\n"


def render_bash_script(prog, specs):
    arms = []

    def flags_of(*completers):
        return [flag for spec in specs if spec["completer"] in completers for flag in spec["flags"]]

    ssh_host_flags = flags_of(SSH_HOST)
    if ssh_host_flags:
        arms.append(
            render_bash_arm(
                "|".join(ssh_host_flags),
                [
                    f'COMPREPLY=($(compgen -W "$({prog} {HOST_LIST_FLAG} 2>/dev/null)" -- "$cur"))',
                    "return",
                ],
            )
        )

    file_flags = flags_of(FILE)
    if file_flags:
        arms.append(
            render_bash_arm("|".join(file_flags), ['COMPREPLY=($(compgen -f -- "$cur"))', "return"])
        )

    for spec in specs:
        if spec["completer"] == CHOICES:
            arms.append(
                render_bash_arm(
                    "|".join(spec["flags"]),
                    [
                        'COMPREPLY=($(compgen -W "{}" -- "$cur"))'.format(" ".join(spec["choices"])),
                        "return",
                    ],
                )
            )

    value_flags = flags_of(VALUE)
    if value_flags:
        arms.append(render_bash_arm("|".join(value_flags), ["return"]))

    all_flags = [flag for spec in specs for flag in spec["flags"]]
    return (
        BASH_TEMPLATE.replace("@ARMS@", "".join(arms))
        .replace("@FLAGS@", " ".join(all_flags))
        .replace("@FUNC@", function_name(prog))
        .replace("@PROG@", prog)
    )


def escape_zsh(text):
    for character in ("\\", "[", "]", ":"):
        text = text.replace(character, "\\" + character)
    return text.replace("'", "'\\''")


def render_zsh_spec(spec):
    if spec["completer"] == SSH_HOST:
        value = ":host:->ssh_host"
    elif spec["completer"] == FILE:
        value = ":file:_files"
    elif spec["completer"] == CHOICES:
        value = ":{}:({})".format(spec["metavar"], " ".join(spec["choices"]))
    elif spec["completer"] == VALUE:
        value = f":{spec['metavar']}:"
    else:
        value = ""

    description = f"[{escape_zsh(spec['help'])}]{value}"
    if len(spec["flags"]) == 1:
        body = f"'{spec['flags'][0]}{description}'"
    else:
        body = "{{{}}}'{}'".format(",".join(spec["flags"]), description)

    return f"'(- *)'{body}" if spec["completer"] == HELP else body


def render_zsh_script(prog, specs):
    ordered = [spec for spec in specs if spec["completer"] != HELP]
    ordered += [spec for spec in specs if spec["completer"] == HELP]
    needs_ssh_hosts = any(spec["completer"] == SSH_HOST for spec in specs)

    lines = [ZSH_HEADER.replace("@PROG@", prog), f"{function_name(prog)}() {{"]
    lines.append("    local context state state_descr line")
    if needs_ssh_hosts:
        lines.append("    local -a ssh_hosts")
    lines.append("    typeset -A opt_args")
    lines.append("")
    lines.append("    _arguments -C \\")
    for index, spec in enumerate(ordered):
        suffix = "" if index == len(ordered) - 1 else " \\"
        lines.append(f"        {render_zsh_spec(spec)}{suffix}")

    if needs_ssh_hosts:
        lines.extend(
            [
                "",
                "    if [[ $state == ssh_host ]]; then",
                f'        ssh_hosts=(${{(f)"$({prog} {HOST_LIST_FLAG} 2>/dev/null)"}})',
                "        if [[ -n $ssh_hosts[1] ]]; then",
                "            _describe -t ssh-hosts 'ssh host' ssh_hosts",
                "        fi",
                "    fi",
            ]
        )

    lines.append("}")
    lines.append(f"compdef {function_name(prog)} {prog}")
    return "\n".join(lines) + "\n"


def render_completion_script(shell, prog, parser, completers=None):
    specs = option_specs(parser, completers)
    if shell == "bash":
        return render_bash_script(prog, specs)
    return render_zsh_script(prog, specs)


def rc_file_path(shell, home=None):
    home = home or os.path.expanduser("~")
    if shell == "zsh":
        return os.path.join(os.path.expanduser(os.environ.get("ZDOTDIR") or home), ".zshrc")

    for name in (".bashrc", ".bash_profile"):
        path = os.path.join(home, name)
        if os.path.exists(path):
            return path
    return os.path.join(home, ".bashrc")


def install_completion(shell, prog, parser, config_dir, completers=None, home=None):
    """Write the completion script and make the shell rc file source it."""
    script_path = os.path.join(config_dir, f"completion.{prog}.{shell}")
    os.makedirs(config_dir, exist_ok=True)
    with open(script_path, "w") as f:
        f.write(render_completion_script(shell, prog, parser, completers))

    rc_path = rc_file_path(shell, home)
    already_sourced = False
    if os.path.exists(rc_path):
        with open(rc_path, "r") as f:
            already_sourced = script_path in f.read()

    if not already_sourced:
        with open(rc_path, "a") as f:
            f.write(f'\n# {prog} shell completion\n[ -f "{script_path}" ] && source "{script_path}"\n')

    return script_path, rc_path, already_sourced
