"""Drive the real hook pipeline in-process with Claude Code-shaped payloads."""

from __future__ import annotations

import io
import json
import uuid
from typing import Dict, List, Optional, Tuple

from skill_spotter import hookrunner


class Session:
    """One fake Claude Code session in a project directory."""

    def __init__(self, cwd: str, session_id: Optional[str] = None):
        self.cwd = cwd
        self.session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"

    def _send(self, hook_event: str, **fields) -> str:
        payload = {
            "session_id": self.session_id,
            "transcript_path": "/tmp/t.jsonl",
            "cwd": self.cwd,
            "permission_mode": "default",
            "hook_event_name": hook_event,
            **fields,
        }
        out = io.StringIO()
        hookrunner.run(hook_event, stdin=io.StringIO(json.dumps(payload)), stdout=out)
        return out.getvalue()

    def turn(
        self,
        prompt: str,
        actions: List[Tuple[str, Dict]] = (),
        failed: Tuple[int, ...] = (),
        crons: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Prompt -> tool calls -> Stop. Returns each hook's stdout."""
        prompt_id = str(uuid.uuid4())
        outputs = {"prompt": self._send("UserPromptSubmit", prompt_id=prompt_id, prompt=prompt)}
        action_out = []
        for i, (tool, tool_input) in enumerate(actions):
            event = "PostToolUseFailure" if i in failed else "PostToolUse"
            action_out.append(
                self._send(
                    event,
                    prompt_id=prompt_id,
                    tool_name=tool,
                    tool_input=tool_input,
                    tool_use_id=f"toolu_{uuid.uuid4().hex[:12]}",
                )
            )
        outputs["actions"] = "".join(action_out)
        outputs["stop"] = self._send(
            "Stop",
            prompt_id=prompt_id,
            stop_hook_active=False,
            last_assistant_message="done",
            background_tasks=[],
            session_crons=[
                {"id": "c", "schedule": "* * * * *", "recurring": True, "prompt": p}
                for p in (crons or [])
            ],
        )
        outputs["prompt_id"] = prompt_id
        return outputs

    def expand(self, command_name: str, args: str = "") -> str:
        return self._send(
            "UserPromptExpansion",
            prompt_id=str(uuid.uuid4()),
            expansion_type="slash_command",
            command_name=command_name,
            command_args=args,
            command_source="project",
            prompt=f"/{command_name} {args}".strip(),
        )

    def skill_changed(self, file_path: str) -> str:
        return self._send("ConfigChange", source="skills", file_path=file_path)

    def end(self, reason: str = "prompt_input_exit") -> str:
        return self._send("SessionEnd", reason=reason)


def bash(cmd: str) -> Tuple[str, Dict]:
    return ("Bash", {"command": cmd})


def edit(path: str) -> Tuple[str, Dict]:
    return ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"})


def read(path: str) -> Tuple[str, Dict]:
    return ("Read", {"file_path": path})


def system_message(stdout: str) -> Optional[str]:
    return json.loads(stdout)["systemMessage"] if stdout else None
