"""Headless Claude calls for dataset generation, cached so the dataset is reproducible.

Every call is keyed by sha256(model + prompt); the raw response is stored under
``bench/data/raw/<key>.json`` together with the prompt. Re-running the generator replays
the cache and makes no new calls. Development-time only: never send real user data here.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
CALL_LOG = RAW_DIR / "calls.jsonl"


def _key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()[:24]


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating ```json fences and leading prose."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    text = text[start:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _salvage(text)


def _salvage(text: str) -> Any:
    """Recover the complete leading items of a truncated or slightly broken JSON list reply
    shaped like {"key": [ {...}, {...}, ... ]}. Raises if nothing usable is left."""
    key = re.match(r'\s*\{\s*"(\w+)"\s*:\s*\[', text)
    if not key:
        raise json.JSONDecodeError("unsalvageable", text, 0)
    items, depth, start, in_str, esc = [], 0, None, False, False
    body_start = key.end()
    for i in range(body_start, len(text)):
        ch = text[i]
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    items.append(json.loads(text[start : i + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    if not items:
        raise json.JSONDecodeError("unsalvageable", text, 0)
    return {key.group(1): items}


def call(prompt: str, *, model: str = "sonnet", label: str = "", timeout: int = 900) -> Any:
    """Return the parsed JSON reply for ``prompt``, from cache if available."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    key = _key(model, prompt)
    path = RAW_DIR / f"{key}.json"
    if path.exists():
        return extract_json(json.loads(path.read_text())["result"])
    started = time.time()
    proc = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--model",
            model,
            "--tools",
            "",
            "--no-session-persistence",
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd="/tmp",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude failed ({label}): {proc.stderr[:500]}")
    reply = json.loads(proc.stdout)
    result = reply.get("result") or ""
    parsed = extract_json(result)  # raise before caching a reply we can't use
    path.write_text(
        json.dumps({"label": label, "model": model, "prompt": prompt, "result": result}, indent=1)
    )
    with CALL_LOG.open("a") as f:
        f.write(
            json.dumps(
                {
                    "key": key,
                    "label": label,
                    "model": model,
                    "seconds": round(time.time() - started, 1),
                    "cost_usd": reply.get("total_cost_usd"),
                    "output_tokens": (reply.get("usage") or {}).get("output_tokens"),
                }
            )
            + "\n"
        )
    return parsed


def cached(prompt: str, model: str = "sonnet") -> Optional[Any]:
    path = RAW_DIR / f"{_key(model, prompt)}.json"
    return extract_json(json.loads(path.read_text())["result"]) if path.exists() else None
