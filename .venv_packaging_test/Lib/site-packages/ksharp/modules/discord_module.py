from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from urllib.parse import quote

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
        self._music_commands: dict[str, dict[str, str]] = {}
        self._on_ready_handler: Any = None
        self._on_message_handler: Any = None
        self._cookie_file: str | None = None
        self._last_music_error: str | None = None
        self._scopes: set[str] = {"bot", "applications.commands"}
        self._intents: dict[str, bool] = {
            "guilds": True,
            "guild_messages": True,
            "message_content": True,
        }

    def available_scopes(self) -> list[str]:
        return sorted(
            {
                "activities.read",
                "activities.write",
                "applications.builds.read",
                "applications.builds.upload",
                "applications.commands",
                "applications.commands.permissions.update",
                "applications.entitlements",
                "applications.store.update",
                "bot",
                "connections",
                "dm_channels.messages.read",
                "dm_channels.messages.write",
                "dm_channels.read",
                "email",
                "gdm.join",
                "gateway.connect",
                "guilds",
                "guilds.channels.read",
                "guilds.join",
                "guilds.members.read",
                "identify",
                "identify.premium",
                "messages.read",
                "openid",
                "relationships.read",
                "relationships.write",
                "role_connections.write",
                "rpc",
                "rpc.activities.write",
                "rpc.notifications.read",
                "rpc.screenshare.read",
                "rpc.screenshare.write",
                "rpc.video.read",
                "rpc.video.write",
                "rpc.voice.read",
                "rpc.voice.write",
                "sdk.social_layer",
                "sdk.social_layer_presence",
                "voice",
                "webhook.incoming",
            }
        )

    def available_intents(self) -> list[str]:
        return sorted(
            {
                "guilds",
                "members",
                "moderation",
                "emojis_and_stickers",
                "integrations",
                "webhooks",
                "invites",
                "voice_states",
                "presences",
                "guild_messages",
                "dm_messages",
                "guild_reactions",
                "dm_reactions",
                "guild_typing",
                "dm_typing",
                "message_content",
                "scheduled_events",
                "auto_moderation_configuration",
                "auto_moderation_execution",
            }
        )

    def scope(self, name: str, enabled: bool = True) -> list[str]:
        normalized = str(name).strip()
        if not normalized:
            raise self._interpreter.runtime_error("discord.scope requires a non-empty scope name.")
        if bool(enabled):
            self._scopes.add(normalized)
        else:
            self._scopes.discard(normalized)
        return self.scopes()

    def scopes(self) -> list[str]:
        return sorted(self._scopes)

    def scope_all(self) -> list[str]:
        for scope_name in self.available_scopes():
            self._scopes.add(scope_name)
        return self.scopes()

    def intent(self, name: str, enabled: bool = True) -> dict[str, bool]:
        key = self._normalize_intent_name(name)
        if not key:
            raise self._interpreter.runtime_error("discord.intent requires a non-empty intent name.")
        self._intents[key] = bool(enabled)
        return self.intents()

    def intents(self) -> dict[str, bool]:
        return dict(sorted(self._intents.items()))

    def intent_defaults(self) -> dict[str, bool]:
        self._intents = {
            "guilds": True,
            "guild_messages": True,
            "message_content": True,
        }
        return self.intents()

    def intent_all(self) -> dict[str, bool]:
        for intent_name in self.available_intents():
            self._intents[self._normalize_intent_name(intent_name)] = True
        return self.intents()

    def intent_disable_all(self) -> dict[str, bool]:
        for key in list(self._intents.keys()):
            self._intents[key] = False
        return self.intents()

    def intent_enabled(self, name: str) -> bool:
        key = self._normalize_intent_name(name)
        return bool(self._intents.get(key, False))

    def required_portal_intents(self) -> list[str]:
        required: list[str] = []
        if self.intent_enabled("message_content"):
            required.append("MESSAGE_CONTENT")
        if self.intent_enabled("members"):
            required.append("GUILD_MEMBERS")
        if self.intent_enabled("presences"):
            required.append("GUILD_PRESENCES")
        return required

    def portal_checklist(self) -> dict[str, Any]:
        return {
            "scopes": self.scopes(),
            "enabled_intents": self.intents(),
            "required_portal_intents": self.required_portal_intents(),
        }

    def enable_message_content(self, enabled: bool = True) -> dict[str, bool]:
        self._intents["message_content"] = bool(enabled)
        return self.intents()

    def enable_voice(self, enabled: bool = True) -> dict[str, bool]:
        value = bool(enabled)
        self._intents["voice_states"] = value
        if value:
            self._scopes.add("voice")
        else:
            self._scopes.discard("voice")
        return self.intents()

    def set_cookie_file(self, path: str) -> str:
        candidate = str(path).strip()
        if not candidate:
            raise self._interpreter.runtime_error("discord.set_cookie_file requires a path.")
        self._cookie_file = candidate
        ytdlp_runtime = self._ytdlp_runtime()
        if ytdlp_runtime is not None:
            ytdlp_runtime.set_cookie_file(candidate)
        return candidate

    def clear_cookie_file(self) -> None:
        self._cookie_file = None
        ytdlp_runtime = self._ytdlp_runtime()
        if ytdlp_runtime is not None:
            ytdlp_runtime.clear_cookie_file()

    def command(self, name: str, handler: Any) -> str:
        command_name = str(name).strip()
        if not command_name:
            raise self._interpreter.runtime_error("discord.command requires a command name.")
        self._commands[command_name] = DiscordCommand(command_name, handler)
        return command_name

    def music(self, name: str, audio_path: str) -> str:
        command_name = str(name).strip()
        if not command_name:
            raise self._interpreter.runtime_error("discord.music requires a command name.")
        path = str(audio_path).strip()
        if not path:
            raise self._interpreter.runtime_error("discord.music requires an audio path.")
        self._music_commands[command_name] = {"mode": "file", "value": path}
        self.enable_voice(True)
        return command_name

    def music_url(self, name: str, default_query: str = "") -> str:
        command_name = str(name).strip()
        if not command_name:
            raise self._interpreter.runtime_error("discord.music_url requires a command name.")
        self._music_commands[command_name] = {
            "mode": "url",
            "value": str(default_query).strip(),
        }
        self.enable_voice(True)
        self.enable_message_content(True)
        return command_name

    def music_commands(self) -> dict[str, str]:
        return {
            key: value.get("mode", "unknown")
            for key, value in sorted(self._music_commands.items())
        }

    def ytdlp_installed(self) -> bool:
        ytdlp_runtime = self._ytdlp_runtime()
        if ytdlp_runtime is not None:
            profile = ytdlp_runtime.profile()
            return bool(profile.get("has_yt_dlp", False))
        try:
            import yt_dlp  # type: ignore  # noqa: F401

            return True
        except Exception:
            return False

    def ytdlp_resolve(self, query: str) -> dict[str, Any]:
        stream_url, title, error_detail = self._resolve_stream_with_ytdlp(str(query))
        if not stream_url:
            message = self._music_error_message(error_detail)
            raise self._interpreter.runtime_error(message)
        return {"title": title or "Unknown title", "stream_url": stream_url}

    def ytdlp_stream_url(self, query: str) -> str:
        stream_url, _title, error_detail = self._resolve_stream_with_ytdlp(str(query))
        if not stream_url:
            message = self._music_error_message(error_detail)
            raise self._interpreter.runtime_error(message)
        return stream_url

    def on_ready(self, handler: Any) -> None:
        self._on_ready_handler = handler

    def on_message(self, handler: Any) -> None:
        self._on_message_handler = handler

    def invite_url(self, client_id: str, permissions: int = 8) -> str:
        cid = str(client_id).strip()
        if not cid:
            raise self._interpreter.runtime_error("discord.invite_url requires client_id.")
        scope_text = quote(" ".join(self.scopes()), safe="")
        perms = int(permissions)
        return (
            f"https://discord.com/oauth2/authorize?client_id={quote(cid, safe='')}"
            f"&permissions={perms}&scope={scope_text}"
        )

    def simulate(self, message: str) -> str:
        text = str(message)
        if self._on_message_handler is not None:
            self._invoke_handler(self._on_message_handler, [text], ignore_errors=True)
        if not text.startswith(self.prefix):
            return ""
        name, trailing = self._parse_command(text)
        music_payload = self._music_commands.get(name)
        if music_payload is not None:
            mode = music_payload.get("mode", "file")
            default_value = music_payload.get("value", "")
            chosen = trailing.strip() or default_value
            if mode == "url":
                return f"music-url-command:{chosen}"
            return f"music-command:{chosen}"
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

        intents = self._build_intents(discord)
        client = discord.Client(intents=intents)
        tree = discord.app_commands.CommandTree(client)

        @client.event
        async def on_ready() -> None:  # type: ignore
            if self._on_ready_handler is not None:
                await self._invoke_handler_async(self._on_ready_handler, [], ignore_errors=True)
            try:
                await tree.sync()
            except Exception:
                pass

        @client.event
        async def on_message(message_obj) -> None:  # type: ignore
            if getattr(message_obj.author, "bot", False):
                return

            content = str(getattr(message_obj, "content", ""))
            if self._on_message_handler is not None:
                await self._invoke_handler_async(
                    self._on_message_handler,
                    [content],
                    ignore_errors=True,
                )
            if not content.startswith(self.prefix):
                return

            command_name, trailing = self._parse_command(content)
            music_payload = self._music_commands.get(command_name)
            if music_payload is not None:
                mode = music_payload.get("mode", "file")
                default_value = music_payload.get("value", "")
                if mode == "url":
                    query = trailing.strip() or default_value
                    await self._run_music_url_message(discord, message_obj, query)
                else:
                    selected_path = trailing.strip() or default_value
                    await self._run_music_source(discord, message_obj, selected_path)
                return

            cmd = self._commands.get(command_name)
            if cmd is None:
                return

            result = await self._invoke_handler_async(cmd.handler, [content], ignore_errors=True)
            if result is not None:
                await message_obj.channel.send(str(result))

        for slash_name, payload in sorted(self._music_commands.items()):
            if payload.get("mode") != "url":
                continue

            async def _slash_play(interaction, url: str, _name: str = slash_name) -> None:
                query = str(url).strip()
                if not query:
                    await self._interaction_send(
                        interaction,
                        f"Usage: /{_name} <url>",
                    )
                    return
                await self._run_music_url_interaction(discord, interaction, query)

            try:
                tree.command(
                    name=slash_name,
                    description=f"Play music from URL/query ({slash_name})",
                )(_slash_play)
            except Exception:
                continue

        try:
            client.run(token)
        except Exception as exc:
            raise self._interpreter.runtime_error(f"discord.run failed: {exc}") from exc

    async def _run_music_source(
        self,
        discord_module,
        message_obj,
        source_url: str,
        *,
        display_title: str | None = None,
    ) -> bool:
        channel = self._author_voice_channel(message_obj)
        if channel is None:
            await message_obj.channel.send("Join a voice channel first.")
            return False

        guild = getattr(message_obj, "guild", None)
        voice_client = getattr(guild, "voice_client", None) if guild is not None else None
        try:
            if voice_client is None:
                voice_client = await channel.connect()
            elif getattr(voice_client, "channel", None) != channel:
                await voice_client.move_to(channel)
            if voice_client.is_playing():
                voice_client.stop()

            source = discord_module.FFmpegPCMAudio(str(source_url))
            voice_client.play(source)
            await message_obj.channel.send(f"Playing: {display_title or source_url}")
            self._last_music_error = None
            return True
        except Exception as exc:
            await message_obj.channel.send(
                f"Voice playback error: {exc}. Install FFmpeg + PyNaCl for music support."
            )
            self._last_music_error = str(exc)
            return False

    async def _run_music_url_message(self, discord_module, message_obj, query: str) -> None:
        if not query:
            await message_obj.channel.send(f"Usage: {self.prefix}play <url>")
            return

        stream_url, title, error_detail = await self._resolve_stream_with_ytdlp_async(query)
        if not stream_url:
            await message_obj.channel.send(self._music_error_message(error_detail))
            return

        await self._run_music_source(
            discord_module,
            message_obj,
            stream_url,
            display_title=title or query,
        )

    async def _run_music_url_interaction(self, discord_module, interaction, query: str) -> None:
        guild = getattr(interaction, "guild", None)
        if guild is None:
            await self._interaction_send(interaction, "This command only works in servers.")
            return

        member = getattr(interaction, "user", None)
        channel = self._member_voice_channel(member)
        if channel is None:
            await self._interaction_send(interaction, "Join a voice channel first.")
            return

        stream_url, title, error_detail = await self._resolve_stream_with_ytdlp_async(query)
        if not stream_url:
            await self._interaction_send(interaction, self._music_error_message(error_detail))
            return

        voice_client = getattr(guild, "voice_client", None)
        try:
            if voice_client is None:
                voice_client = await channel.connect()
            elif getattr(voice_client, "channel", None) != channel:
                await voice_client.move_to(channel)
            if voice_client.is_playing():
                voice_client.stop()
            source = discord_module.FFmpegPCMAudio(str(stream_url))
            voice_client.play(source)
            self._last_music_error = None
            await self._interaction_send(
                interaction,
                f"Playing: {title or query}",
            )
        except Exception as exc:
            self._last_music_error = str(exc)
            await self._interaction_send(
                interaction,
                f"Voice playback error: {exc}. Install FFmpeg + PyNaCl.",
            )

    async def _interaction_send(self, interaction, message: str) -> None:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message)
            else:
                await interaction.response.send_message(message)
        except Exception:
            pass

    def _author_voice_channel(self, message_obj):
        author = getattr(message_obj, "author", None)
        return self._member_voice_channel(author)

    @staticmethod
    def _member_voice_channel(member):
        state = getattr(member, "voice", None)
        return getattr(state, "channel", None)

    async def _resolve_stream_with_ytdlp_async(
        self,
        query: str,
    ) -> tuple[str | None, str | None, str | None]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._resolve_stream_with_ytdlp(query))

    def _resolve_stream_with_ytdlp(self, query: str) -> tuple[str | None, str | None, str | None]:
        ytdlp_runtime = self._ytdlp_runtime()
        if ytdlp_runtime is None:
            message = (
                "ytdlp runtime is unavailable. Install with kar install ytdlp.ksharp "
                "(or kar install yt-dlp --global)."
            )
            self._last_music_error = message
            return None, None, message

        if self._cookie_file:
            try:
                ytdlp_runtime.set_cookie_file(self._cookie_file)
            except Exception as exc:
                message = self._error_summary(exc)
                self._last_music_error = message
                return None, None, message

        target = str(query).strip()
        if not target:
            message = "Query/URL is empty."
            self._last_music_error = message
            return None, None, message

        try:
            payload = ytdlp_runtime.stream(target)
        except Exception as exc:
            message = self._error_summary(exc)
            self._last_music_error = message
            return None, None, message

        if not isinstance(payload, dict):
            message = "ytdlp returned an unexpected payload."
            self._last_music_error = message
            return None, None, message

        stream_url = str(payload.get("stream_url") or "").strip()
        title = str(payload.get("title") or "Unknown title")
        if not stream_url:
            message = "ytdlp resolved metadata but stream URL is empty."
            self._last_music_error = message
            return None, title, message

        self._last_music_error = None
        return stream_url, title, None

    def _ytdlp_runtime(self) -> Any | None:
        try:
            runtime = self._interpreter.globals.get("ytdlp")
        except Exception:
            return None
        if runtime is None or not hasattr(runtime, "stream"):
            return None
        return runtime

    def _music_error_message(self, error_detail: str | None) -> str:
        base = (
            "Could not resolve playable audio. "
            "Try a direct URL or clearer keywords. "
            "If a video is restricted, set a cookie file with discord_set_cookie_file(...) "
            "or ytdlp_set_cookie_file(...)."
        )
        detail = (error_detail or self._last_music_error or "").strip()
        if detail:
            return f"{base} Reason: {detail}"
        return base

    @staticmethod
    def _error_summary(exc: Exception) -> str:
        text = str(exc).strip()
        if not text:
            return "unknown error"
        if "\n" in text:
            return text.splitlines()[0].strip()
        return text

    def _build_intents(self, discord_module):
        intents = discord_module.Intents.default()
        for name, enabled in self._intents.items():
            self._apply_intent_setting(intents, name, enabled)
        return intents

    def _apply_intent_setting(self, intents_obj, name: str, enabled: bool) -> None:
        normalized = self._normalize_intent_name(name)
        for attr in self._intent_attr_candidates(normalized):
            if hasattr(intents_obj, attr):
                setattr(intents_obj, attr, bool(enabled))

    def _intent_attr_candidates(self, normalized_name: str) -> list[str]:
        mapping: dict[str, list[str]] = {
            "guild_messages": ["guild_messages", "messages"],
            "dm_messages": ["dm_messages", "messages"],
            "guild_reactions": ["guild_reactions", "reactions"],
            "dm_reactions": ["dm_reactions", "reactions"],
            "guild_typing": ["guild_typing", "typing"],
            "dm_typing": ["dm_typing", "typing"],
            "message_content": ["message_content"],
            "voice_states": ["voice_states"],
            "members": ["members"],
            "presences": ["presences"],
            "scheduled_events": ["guild_scheduled_events", "scheduled_events"],
            "moderation": ["moderation", "guild_moderation"],
            "emojis_and_stickers": ["emojis_and_stickers", "guild_emojis_and_stickers"],
        }
        return mapping.get(normalized_name, [normalized_name])

    @staticmethod
    def _normalize_intent_name(name: str) -> str:
        raw = str(name).strip().lower()
        for token in (" ", "-", "."):
            raw = raw.replace(token, "_")
        aliases = {
            "messages": "guild_messages",
            "voice": "voice_states",
            "guild_message_reactions": "guild_reactions",
            "dm_message_reactions": "dm_reactions",
            "guild_message_typing": "guild_typing",
            "dm_message_typing": "dm_typing",
            "guild_members": "members",
            "guild_presences": "presences",
        }
        return aliases.get(raw, raw)

    def _parse_command(self, content: str) -> tuple[str, str]:
        raw = content[len(self.prefix) :].strip()
        if not raw:
            return "", ""
        parts = raw.split(" ", maxsplit=1)
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], parts[1]

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

    async def _invoke_handler_async(
        self,
        handler: Any,
        args: list[Any],
        *,
        ignore_errors: bool = False,
    ) -> Any:
        try:
            if handler is None:
                return None
            if isinstance(handler, str):
                return handler
            if _is_async_callable(handler):
                return await handler(*args)
            if callable(handler):
                return handler(*args)
            result = self._interpreter.call(handler, args)
            if inspect.isawaitable(result):
                return await result
            return result
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
            raise self._interpreter.runtime_error(
                "Cannot invoke async handler from sync context. Use runtime events."
            )
        if callable(handler):
            return handler(*args)
        return self._interpreter.call(handler, args)


class DiscordRuntimeModule:
    def __init__(self, interpreter: "Interpreter") -> None:
        self._interpreter = interpreter

    def create(self, prefix: str = "!") -> DiscordBotBridge:
        return DiscordBotBridge(self._interpreter, prefix=prefix)
