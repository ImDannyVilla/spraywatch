"""The label reader model: Qwen3.6 behind an OpenAI-compatible server, or a fake for laptop tests.

Standard library only. The real client reads `MODEL_URL`, `MODEL_NAME` and
`MODEL_API_KEY` from the environment or an env file. The URL is the local model
server; nothing here calls anything off the box.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Reply:
    text: str
    seconds: float
    # The server's finish_reason; "length" means max_tokens cut the reply off.
    finish_reason: str = ""


class ModelError(RuntimeError):
    """The model server failed or sent something that isn't a chat reply."""


class Model(Protocol):
    name: str

    def ask(self, content: list[dict]) -> Reply: ...


def read_env_file(path: Path) -> dict[str, str]:
    """`KEY=VALUE` lines; blank lines and `#` comments skipped."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class ChatClient:
    """Chat completions on the local model server. Thinking off and temperature 0: the reply is data."""

    def __init__(self, url: str, model: str, api_key: str = "", timeout: float = 600.0, max_tokens: int = 4096):
        self.url = url.rstrip("/") + "/chat/completions"
        self.name = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "ChatClient":
        env = dict(os.environ)
        if env_file is not None and env_file.is_file():
            env = {**read_env_file(env_file), **env}
        missing = [key for key in ("MODEL_URL", "MODEL_NAME") if not env.get(key)]
        if missing:
            raise ModelError(f"set {' and '.join(missing)} (see docs/gb10.md)")
        return cls(env["MODEL_URL"], env["MODEL_NAME"], env.get("MODEL_API_KEY", ""))

    def payload(self, content: list[dict]) -> dict:
        return {
            "model": self.name,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }

    def ask(self, content: list[dict]) -> Reply:
        body = json.dumps(self.payload(content)).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        started = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url, data=body, headers=headers),
                                        timeout=self.timeout) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise ModelError(f"model server answered {error.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ModelError(f"model server unreachable or bad reply: {error}") from None
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ModelError("model server reply has no choices[0].message") from None
        return Reply(text, round(time.monotonic() - started, 3), str(choice.get("finish_reason") or ""))


class FakeModel:
    """Replies with a fixed text, as the model would, so laptop tests need no model."""

    def __init__(self, reply: str, name: str = "fake"):
        self.name = name
        self.reply = reply
        self.asked: list[list[dict]] = []

    @classmethod
    def from_file(cls, path: Path) -> "FakeModel":
        return cls(path.read_text(encoding="utf-8"), name=f"fake:{path.name}")

    def ask(self, content: list[dict]) -> Reply:
        self.asked.append(content)
        return Reply(self.reply, 0.0, "stop")


class FakeReplies:
    """Fake replies picked by the label's file name (`<stem>.json` in a folder), for the demo without a model."""

    def __init__(self, folder: Path):
        self.folder = folder

    def for_label(self, path: Path) -> FakeModel:
        reply = self.folder / f"{path.stem}.json"
        if not reply.is_file():
            raise ModelError(f"no fake reply {reply.name} in {self.folder}")
        return FakeModel.from_file(reply)
