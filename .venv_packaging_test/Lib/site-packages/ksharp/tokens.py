from __future__ import annotations

from dataclasses import dataclass
from typing import Any


KEYWORDS = {
    "let",
    "lock",
    "forge",
    "if",
    "elif",
    "else",
    "while",
    "each",
    "in",
    "return",
    "break",
    "continue",
    "and",
    "or",
    "not",
    "true",
    "false",
    "nil",
    "spark",
    "use",
    "class",
    "new",
    "lambda",
    "self",
}


@dataclass(frozen=True)
class Token:
    type: str
    lexeme: str
    literal: Any
    line: int
    column: int

    def location(self) -> str:
        return f"{self.line}:{self.column}"

    def __repr__(self) -> str:
        literal = f", literal={self.literal!r}" if self.literal is not None else ""
        return (
            f"Token(type={self.type!r}, lexeme={self.lexeme!r}"
            f"{literal}, line={self.line}, column={self.column})"
        )
