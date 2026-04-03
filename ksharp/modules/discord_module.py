from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ksharp.runtime import Interpreter


def _is_async_callable(value: Any) -> bool:
    return inspect.iscoroutinefunction(value)


@dataclass(slots=True)
class DiscordCommand:
    name: str
    handler: Any


class DiscordBotBridge:
    def __init__(self, interpreter: "Interpreter", prefix: str = "!") -> None:
        self._interpreter = interpreter
        self.prefix = prefix
        self._commands: dict[str, DiscordCommand] = {}
        self._on_ready_handler: Any = None
        self._on_message_handler: Any = None

    def command(self, name: str, handler: Any) -> str:
        command_name = str(name).strip()
        if not command_name:
            raise self._interpreter.runtime_error("discord.command requires a command name.")
        self._commands[command_name] = DiscordCommand(command_name, handler)
        return command_name

    def on_ready(self, handler: Any) -> None:
        self._on_ready_handler = handler

    def on_message(self, handler: Any) -> None:
        self._on_message_handler = handler

    def simulate(self, message: str) -> str:
        text = str(message)
        if self._on_message_handler is not None:
            self._invoke_handler(self._on_message_handler, [text], ignore_errors=True)
        if not text.startswith(self.prefix):
            return ""
        name = text[len(self.prefix) :].strip().split(" ", maxsplit=1)[0]
        cmd = self._commands.get(name)
        if cmd is None:
            return "unknown-command"
        result = self._invoke_handler(cmd.handler, [text], ignore_errors=True)
        return "" if result is None else str(result)

    def run(self, token: str) -> None:
        token = str(token).strip()
        if not token:
            raise self._interpreter.runtime_error("discord.run requires a bot token.")
        try:
            import discord  # type: ignore
        except Exception as exc:
            raise self._interpreter.runtime_error(
                "discord.py not installed. Install with: kar install discord.py"
            ) from exc

        intents = discord.Intents.default()
        if hasattr(intents, "message_content"):
            intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready() -> None:  # type: ignore
            if self._on_ready_handler is not None:
                self._invoke_handler(self._on_ready_handler, [], ignore_errors=True)

        @client.event
        async def on_message(message_obj) -> None:  # type: ignore
            if getattr(message_obj.author, "bot", False):
                return
            content = str(getattr(message_obj, "content", ""))
            if self._on_message_handler is not None:
                self._invoke_handler(self._on_message_handler, [content], ignore_errors=True)
            if not content.startswith(self.prefix):
                return
            command_name = content[len(self.prefix) :].strip().split(" ", maxsplit=1)[0]
            cmd = self._commands.get(command_name)
            if cmd is None:
                return
            result = self._invoke_handler(cmd.handler, [content], ignore_errors=True)
            if result is not None:
                await message_obj.channel.send(str(result))

        try:
            client.run(token)
        except Exception as exc:
            raise self._interpreter.runtime_error(f"discord.run failed: {exc}") from exc

    def _invoke_handler(
        self,
        handler: Any,
        args: list[Any],
        *,
        ignore_errors: bool = False,
    ) -> Any:
        try:
            return self._invoke_handler_inner(handler, args)
        except Exception:
            if ignore_errors:
                return None
            raise

    def _invoke_handler_inner(self, handler: Any, args: list[Any]) -> Any:
        if handler is None:
            return None
        if isinstance(handler, str):
            return handler
        if _is_async_callable(handler):
            return asyncio.run(handler(*args))
        if callable(handler):
            return handler(*args)
        return self._interpreter.call(handler, args)


class DiscordRuntimeModule:
    def __init__(self, interpreter: "Interpreter") -> None:
        self._interpreter = interpreter

    def create(self, prefix: str = "!") -> DiscordBotBridge:
        return DiscordBotBridge(self._interpreter, prefix=prefix)
