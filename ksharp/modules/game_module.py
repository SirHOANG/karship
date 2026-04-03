from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ksharp.runtime import Interpreter


class InputState:
    def __init__(self) -> None:
        self._keys: dict[str, bool] = {}

    def key_down(self, key: str) -> None:
        self._keys[str(key).lower()] = True

    def key_up(self, key: str) -> None:
        self._keys[str(key).lower()] = False

    def is_pressed(self, key: str) -> bool:
        return bool(self._keys.get(str(key).lower(), False))

    def snapshot(self) -> dict[str, bool]:
        return dict(self._keys)


@dataclass(slots=True)
class GameStats:
    frames: int = 0
    elapsed_seconds: float = 0.0
    average_fps: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "frames": self.frames,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "average_fps": round(self.average_fps, 3),
        }


class GameLoopBridge:
    def __init__(self, interpreter: "Interpreter", *, fps: int, input_state: InputState) -> None:
        self._interpreter = interpreter
        self._fps = max(1, int(fps))
        self._input = input_state
        self._update_handler: Any = None
        self._render_handler: Any = None
        self._running = False
        self._stats = GameStats()

    def on_update(self, handler: Any) -> None:
        self._update_handler = handler

    def on_render(self, handler: Any) -> None:
        self._render_handler = handler

    def set_fps(self, fps: int) -> int:
        self._fps = max(1, int(fps))
        return self._fps

    def get_fps(self) -> int:
        return self._fps

    def run(self, seconds: float = 3.0, max_frames: int | None = None) -> dict[str, float]:
        self._running = True
        target_frame_time = 1.0 / float(self._fps)
        start = time.perf_counter()
        last = start
        frames = 0

        while self._running:
            now = time.perf_counter()
            delta = now - last
            if delta < target_frame_time:
                time.sleep(target_frame_time - delta)
                now = time.perf_counter()
                delta = now - last
            last = now

            if self._update_handler is not None:
                self._invoke(self._update_handler, [delta, self._input.snapshot()])
            if self._render_handler is not None:
                self._invoke(self._render_handler, [delta, self._input.snapshot()])

            frames += 1
            elapsed = now - start
            if max_frames is not None and frames >= int(max_frames):
                break
            if elapsed >= float(seconds):
                break

        self._running = False
        total_elapsed = max(time.perf_counter() - start, 1e-9)
        self._stats = GameStats(
            frames=frames,
            elapsed_seconds=total_elapsed,
            average_fps=(frames / total_elapsed),
        )
        return self._stats.as_dict()

    def stop(self) -> None:
        self._running = False

    def stats(self) -> dict[str, float]:
        return self._stats.as_dict()

    def _invoke(self, handler: Any, args: list[Any]) -> Any:
        if callable(handler):
            try:
                return handler(*args)
            except TypeError:
                return handler()
        return self._interpreter.call(handler, args)


class GameRuntimeModule:
    def __init__(self, interpreter: "Interpreter", *, default_fps: int = 60) -> None:
        self._interpreter = interpreter
        self._input = InputState()
        self._default_fps = default_fps

    def create_loop(self, fps: int | None = None) -> GameLoopBridge:
        return GameLoopBridge(
            self._interpreter,
            fps=self._default_fps if fps is None else fps,
            input_state=self._input,
        )

    def key_down(self, key: str) -> None:
        self._input.key_down(key)

    def key_up(self, key: str) -> None:
        self._input.key_up(key)

    def is_pressed(self, key: str) -> bool:
        return self._input.is_pressed(key)

    def input(self) -> InputState:
        return self._input
