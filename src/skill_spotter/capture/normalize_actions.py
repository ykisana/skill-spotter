"""Turn one tool call into weighted tokens (SPEC section 5.2).

``normalize_action(tool_name, tool_input, project_root)`` returns an ``Action``:
- ``tokens``: {token: weight}. Bash commands emit three levels, L1 ``bash:git`` (0.1),
  L2 ``bash:git commit`` (0.5) and L3 ``bash:git commit --amend`` (1.0), so similar
  commands get partial credit;
- ``primary``: one key per action, used for order-sensitive bigrams across a turn;
- ``template``: the normalized command(s) as text, e.g. ``git commit -a``;
- ``summary``: a short, redacted description that is safe to store;
- ``danger``, ``low`` (exploration noise), ``values`` (what was stripped, for params).
"""

from __future__ import annotations

import os
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from . import rules
from .redact import redact

L1, L2, L3 = 0.1, 0.5, 1.0
LOW_FACTOR = 0.1
FAILED_FACTOR = 0.5
SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "|&", ";;", "(", ")", "{", "}", "\n"})

_REDIRECT = re.compile(r"(?<![\w$])\d*(?:>>?|<<?|&>)&?\s*(?:\"[^\"]*\"|'[^']*'|[^\s;&|]+)")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9_:+\-]*$")
_SHORT_BUNDLE = re.compile(r"^-[A-Za-z]{2,}$")
_SHORT_WITH_VALUE = re.compile(r"^(-[A-Za-z])(\d.*)$")
_HEXISH = re.compile(r"^(?=.*\d)[0-9a-f]{7,}$")

Action = Dict[str, Any]


def _empty(tool_name: str) -> Action:
    return {
        "tool": tool_name,
        "tokens": {},
        "primary": None,
        "template": "",
        "summary": "",
        "danger": False,
        "low": True,
        "values": [],
    }


def normalize_action(
    tool_name: str,
    tool_input: Any,
    project_root: Optional[str] = None,
    *,
    failed: bool = False,
) -> Action:
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if not isinstance(tool_name, str) or not tool_name or tool_name in rules.IGNORED_TOOLS:
        return _empty(tool_name or "")
    if tool_name == "Bash":
        action = _bash_action(str(tool_input.get("command") or ""))
    elif tool_name in rules.EDIT_TOOLS:
        action = _edit_action(tool_name, tool_input, project_root)
    elif tool_name in rules.READ_TOOLS:
        action = _read_action(tool_name, tool_input, project_root)
    elif tool_name.startswith("mcp__"):
        action = _mcp_action(tool_name, tool_input)
    elif tool_name == "WebFetch":
        domain = _domain(str(tool_input.get("url") or ""))
        action = _simple(tool_name, f"web:{domain}", L3, summary=domain)
    elif tool_name == "WebSearch":
        action = _simple(tool_name, "web:search", L2, summary="search")
    elif tool_name == "Skill":
        name = str(
            tool_input.get("skill") or tool_input.get("command") or tool_input.get("name") or "?"
        )
        action = _simple(tool_name, f"skill:{name.lstrip('/')}", L3, summary=name)
    elif tool_name in ("Agent", "Task"):
        kind = str(tool_input.get("subagent_type") or "general-purpose")
        action = _simple(tool_name, f"agent:{kind}", L2, summary=kind)
    else:
        action = _simple(tool_name, f"tool:{tool_name}", L2, summary=tool_name)
    if failed and action["tokens"]:
        action["tokens"] = {t: w * FAILED_FACTOR for t, w in action["tokens"].items()}
    action["failed"] = failed
    return action


def _simple(tool: str, token: str, weight: float, *, summary: str, low: bool = False) -> Action:
    action = _empty(tool)
    action.update(tokens={token: weight}, primary=token, template=token, summary=summary, low=low)
    return action


# --- Bash -----------------------------------------------------------------------------


_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
# Stands in for a command substitution: an argument value, never a command name.
SUBSTITUTION = "%sub"


def strip_heredocs(command: str) -> str:
    """Drop here-document bodies (``python3 - <<'EOF' ... EOF``): they are data or a script
    for another program, not shell commands."""
    out: List[str] = []
    pending: List[Tuple[str, bool]] = []
    for line in command.split("\n"):
        if pending:
            tag, dash = pending[0]
            if (line.lstrip("\t") if dash else line).strip() == tag:
                pending.pop(0)
            continue
        for m in _HEREDOC.finditer(line):
            pending.append((m.group(3), bool(m.group(1))))
        out.append(_HEREDOC.sub(" ", line))
    return "\n".join(out)


def strip_substitutions(command: str) -> str:
    """Replace ``$(...)`` and backquoted command substitutions with a value placeholder, so
    ``git log $(git describe --tags)..HEAD`` stays one ``git log`` with a value."""
    out, i, n = [], 0, len(command)
    while i < n:
        if command.startswith("$(", i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(command[j], 0)
                j += 1
            out.append(SUBSTITUTION)
            i = j
        elif command[i] == "`":
            j = command.find("`", i + 1)
            out.append(SUBSTITUTION)
            i = n if j < 0 else j + 1
        else:
            out.append(command[i])
            i += 1
    return "".join(out)


def split_commands(command: str) -> List[List[str]]:
    """Shell words of each simple command in a (possibly chained) command line."""
    command = strip_substitutions(strip_heredocs(command))
    command = _REDIRECT.sub(" ", command.replace("\\\n", " "))
    # Newlines separate commands too, so they're punctuation here, not whitespace.
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        words = list(lexer)
    except ValueError:  # unbalanced quotes: fall back to plain splitting
        words = command.replace("&&", " && ").replace(";", " ; ").replace("|", " | ").split()
    parts: List[List[str]] = [[]]
    for word in words:
        if word in SEPARATORS or (word and set(word) <= set("&|;()\n")):
            if parts[-1]:
                parts.append([])
        elif word and set(word) <= set("<>"):
            continue  # leftover redirect operator
        else:
            parts[-1].append(word)
    return [p for p in parts if p]


def normalize_command(words: List[str], depth: int = 0) -> List[Dict[str, Any]]:
    """Normalize one simple command. Returns a list because ``bash -c`` may nest."""
    words = list(words)
    while words and _ENV_ASSIGN.match(words[0]):
        words.pop(0)
    # Strip wrappers like sudo/timeout/xargs.
    while words:
        head = os.path.basename(words[0])
        if head in rules.WRAPPERS:
            words.pop(0)
            while words and (words[0].startswith("-") or _ENV_ASSIGN.match(words[0])):
                words.pop(0)
        elif head in rules.WRAPPERS_WITH_ARGS:
            words.pop(0)
            while words and (
                words[0].startswith("-") or _is_number(words[0]) or words[0] in ("{}", "%")
            ):
                words.pop(0)
        else:
            break
    if not words:
        return []
    cmd = words[0]
    name = cmd if cmd in rules.CLI_RULES else os.path.basename(cmd)
    if name in rules.SHELLS and "-c" in words and depth < 2:
        idx = words.index("-c")
        if idx + 1 < len(words):
            nested = []
            for part in split_commands(words[idx + 1]):
                nested.extend(normalize_command(part, depth + 1))
            return nested
    rule = rules.CLI_RULES.get(name, {})
    runner_words = 1 if name in rules.RUNNERS else 0
    if len(words) > 1 and (name, words[1]) in rules.RUNNER_SUBCOMMANDS:
        runner_words = 2
    if runner_words and depth < 3:
        inner = words[runner_words:]
        while inner and inner[0].startswith("-"):
            flag = inner.pop(0)
            if flag in rule.get("drop_flags", ()) and "=" not in flag and inner:
                inner.pop(0)
        if inner:
            return normalize_command(inner, depth + 1)
    return [_parse(name, words[1:], rule)]


def _parse(name: str, args: List[str], rule: Dict[str, Any]) -> Dict[str, Any]:
    drop_flags = rule.get("drop_flags", set())
    value_flags = rule.get("value_flags", set())
    keep_value_flags = rule.get("keep_value_flags", set())
    no_bundle = rule.get("no_bundle", False)

    subs: List[str] = []
    identity: List[str] = []
    flags: List[str] = []
    values: List[str] = []
    max_sub = rule.get("sub", 0)
    max_identity = rule.get("identity", 0)
    if rule.get("script"):  # script name, plus one subcommand word (manage.py migrate)
        max_identity = max(max_identity, 2)

    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            values.extend(args[i:])
            break
        if arg.startswith("-") and len(arg) > 1 and not _is_number(arg):
            expanded = _expand_flag(arg, no_bundle)
            for j, (flag, attached) in enumerate(expanded):
                last = j == len(expanded) - 1
                takes_value = flag in drop_flags or flag in value_flags or flag in keep_value_flags
                value = attached
                next_is_flag = i < len(args) and args[i].startswith("-") and not _is_number(args[i])
                if takes_value and value is None and last and i < len(args) and not next_is_flag:
                    value = args[i]
                    i += 1
                if flag in keep_value_flags and value is not None:
                    identity.append(f"{flag} {os.path.basename(value)}")
                    continue
                if value is not None:
                    values.append(value)
                if flag in drop_flags or flag in rules.NOISE_FLAGS:
                    continue
                flags.append(flag)
            continue
        # Positional
        if len(subs) < max_sub and _WORD.match(arg) and not identity:
            subs.append(arg.lower())
            if len(subs) == 1 and arg.lower() in rule.get("sub2", ()):
                max_sub = max(max_sub, 2)
            if len(subs) == max_sub or (len(subs) == 1 and max_sub == 1):
                after = rule.get("identity_after", {})
                if subs[-1] in after:
                    max_identity = max(max_identity, after[subs[-1]])
            continue
        if len(identity) < max_identity:
            if rule.get("script") and not identity and _looks_like_path(arg):
                identity.append(os.path.basename(arg))
                continue
            if _WORD.match(arg) or (rule.get("script") and not identity):
                identity.append(arg if not rule.get("script") else os.path.basename(arg))
                continue
        values.append(arg)

    l2_words = [name] + subs + identity
    flags_sorted = sorted(set(flags))
    l1 = f"bash:{name}"
    l2 = "bash:" + " ".join(l2_words)
    l3 = l2 + ("" if not flags_sorted else " " + " ".join(flags_sorted))
    sub_key = " ".join([name] + subs[:1])
    low = name in rules.LOW_VALUE_COMMANDS or sub_key in rules.LOW_VALUE_SUBCOMMANDS
    danger = _is_danger(name, subs, identity, flags_sorted, rule)
    return {
        "cmd": name,
        "l1": l1,
        "l2": l2,
        "l3": l3,
        "template": l3[len("bash:") :],
        "low": low,
        "danger": danger,
        "values": values,
    }


def _expand_flag(arg: str, no_bundle: bool):
    """'-am' -> [('-a', None), ('-m', None)]; '--x=1' -> [('--x', '1')]; '-n5' -> [('-n','5')]."""
    if arg.startswith("--"):
        if "=" in arg:
            flag, value = arg.split("=", 1)
            return [(flag, value)]
        return [(arg, None)]
    if "=" in arg:  # terraform style: -var=x
        flag, value = arg.split("=", 1)
        return [(flag, value)]
    match = _SHORT_WITH_VALUE.match(arg)
    if match:
        return [(match.group(1), match.group(2))]
    if _SHORT_BUNDLE.match(arg) and not no_bundle:
        return [(f"-{c}", None) for c in arg[1:]]
    return [(arg, None)]


def _is_danger(name, subs, identity, flags, rule) -> bool:
    flag_set = set(flags)
    if flag_set & rules.DANGER_FLAGS or flag_set & rule.get("danger_flags", set()):
        return True
    if name == "rm" and flag_set & {"-r", "-R", "--recursive"} and flag_set & {"-f", "--force"}:
        return True
    if any(word in rules.DANGER_WORDS for word in subs + identity):
        return True
    return any((name, sub) in rules.DANGER_SUBCOMMANDS for sub in subs[:1])


def _bash_action(command: str) -> Action:
    action = _empty("Bash")
    parsed = []
    for words in split_commands(command):
        parsed.extend(normalize_command(words))
    if not parsed:
        return action
    tokens: Dict[str, float] = {}
    for p in parsed:
        factor = LOW_FACTOR if p["low"] else 1.0
        for token, weight in ((p["l1"], L1), (p["l2"], L2), (p["l3"], L3)):
            tokens[token] = max(tokens.get(token, 0.0), weight * factor)
    meaningful = [p for p in parsed if not p["low"]]
    first = (meaningful or parsed)[0]
    action.update(
        tokens=tokens,
        primary=first["l2"],
        template=" ; ".join(p["template"] for p in (meaningful or parsed)),
        summary=redact(command)[:500],
        danger=any(p["danger"] for p in parsed),
        low=not meaningful,
        values=[redact(v) for p in (meaningful or parsed) for v in p["values"] if _param_like(v)][
            :20
        ],
    )
    return action


# --- other tools ----------------------------------------------------------------------


def relative_path(path: str, project_root: Optional[str]) -> str:
    if not path:
        return ""
    if project_root:
        try:
            rel = os.path.relpath(path, project_root)
        except ValueError:
            rel = path
        if not rel.startswith(".."):
            return rel.replace(os.sep, "/")
    return "<external>/" + os.path.basename(path.rstrip("/"))


def _edit_action(tool: str, tool_input: Dict[str, Any], project_root: Optional[str]) -> Action:
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    rel = relative_path(path, project_root) or "?"
    directory = rel.rsplit("/", 1)[0] if "/" in rel else "."
    action = _empty(tool)
    action.update(
        tokens={f"edit:{rel}": L3, f"editdir:{directory}": L2},
        primary=f"edit:{rel}",
        template=f"edit {rel}",
        summary=rel,
        low=False,
        values=[rel],
    )
    return action


def _read_action(tool: str, tool_input: Dict[str, Any], project_root: Optional[str]) -> Action:
    path = str(
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("notebook_path")
        or ""
    )
    rel = relative_path(path, project_root) if path else "."
    top = rel.split("/", 1)[0] if "/" in rel else "."
    return _simple(tool, f"read:{top}", L3 * LOW_FACTOR, summary=rel, low=True)


def _mcp_action(tool_name: str, tool_input: Dict[str, Any]) -> Action:
    parts = tool_name.split("__")
    server = parts[1] if len(parts) > 1 else "?"
    tool = "__".join(parts[2:]) if len(parts) > 2 else "?"
    arg_names = ",".join(sorted(str(k) for k in tool_input))
    action = _empty(tool_name)
    l2 = f"mcp:{server}:{tool}"
    action.update(
        tokens={f"mcp:{server}": L1, l2: L2, f"{l2}({arg_names})": L3},
        primary=l2,
        template=f"{server}/{tool}({arg_names})",
        summary=f"{server}/{tool}({arg_names})",
        low=False,
        danger=any(
            word in tool.lower() for word in ("delete", "drop", "destroy", "deploy", "publish")
        ),
    )
    return action


def _domain(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        host = ""
    return host[4:] if host.startswith("www.") else (host or "?")


def _param_like(value: str) -> bool:
    """Short single-line values can become skill arguments; message bodies and code can't."""
    return (
        0 < len(value) <= 60
        and "\n" not in value
        and not value.startswith(("$(", "<<", "`"))
        and value.count(" ") <= 3
    )


def _is_number(text: str) -> bool:
    return bool(re.match(r"^-?\d+(?:\.\d+)?[smhdkKMG%]?$", text))


def _looks_like_path(text: str) -> bool:
    return "/" in text or text.startswith((".", "~")) or bool(re.search(r"\.\w{1,5}$", text))


# --- turn level -------------------------------------------------------------------------

SEQ_WEIGHT = 0.5


def turn_fingerprint(actions: List[Action]) -> Dict[str, float]:
    """Merge a turn's actions into one {token: weight} map, plus order bigrams."""
    tokens: Dict[str, float] = {}
    for action in actions:
        for token, weight in action["tokens"].items():
            tokens[token] = max(tokens.get(token, 0.0), weight)
    primaries = [a["primary"] for a in actions if a["primary"] and not a["low"]]
    deduped = [p for i, p in enumerate(primaries) if i == 0 or p != primaries[i - 1]]
    for a, b in zip(deduped, deduped[1:]):
        key = f"seq:{a}>{b}"
        tokens[key] = max(tokens.get(key, 0.0), SEQ_WEIGHT)
    return tokens


def is_meaningful(action: Action) -> bool:
    return bool(action["tokens"]) and not action["low"]
