from __future__ import annotations

from .tokens import KEYWORDS, Token


class KSharpLexerError(Exception):
    pass


class Lexer:
    def __init__(self, source: str, filename: str = "<memory>") -> None:
        self.source = source
        self.filename = filename
        self._tokens: list[Token] = []
        self._start = 0
        self._current = 0
        self._line = 1
        self._column = 1
        self._start_line = 1
        self._start_column = 1

    def tokenize(self) -> list[Token]:
        while not self._is_at_end():
            self._start = self._current
            self._start_line = self._line
            self._start_column = self._column
            self._scan_token()
        self._tokens.append(Token("EOF", "", None, self._line, self._column))
        return self._tokens

    def _scan_token(self) -> None:
        char = self._advance()
        if char in (" ", "\t", "\r"):
            return
        if char == "\n":
            self._add_token("NEWLINE", "\n")
            return
        if char == "#":
            self._consume_line_comment()
            return

        single_char_tokens = {
            "(": "LEFT_PAREN",
            ")": "RIGHT_PAREN",
            "{": "LEFT_BRACE",
            "}": "RIGHT_BRACE",
            "[": "LEFT_BRACKET",
            "]": "RIGHT_BRACKET",
            ",": "COMMA",
            ".": "DOT",
            "+": "PLUS",
            "*": "STAR",
            "%": "PERCENT",
            ";": "SEMICOLON",
            ":": "COLON",
        }
        if char in single_char_tokens:
            self._add_token(single_char_tokens[char], char)
            return

        if char == "-":
            token_type = "ARROW" if self._match(">") else "MINUS"
            self._add_token(token_type, "->" if token_type == "ARROW" else "-")
            return

        if char == "/":
            if self._match("/"):
                self._consume_line_comment()
                return
            if self._match("*"):
                self._consume_block_comment()
                return
            self._add_token("SLASH", "/")
            return

        if char == "!":
            token_type = "BANG_EQUAL" if self._match("=") else "BANG"
            self._add_token(token_type, "!=" if token_type == "BANG_EQUAL" else "!")
            return

        if char == "=":
            if self._match(">"):
                self._add_token("FAT_ARROW", "=>")
                return
            token_type = "EQUAL_EQUAL" if self._match("=") else "EQUAL"
            self._add_token(token_type, "==" if token_type == "EQUAL_EQUAL" else "=")
            return

        if char == "<":
            token_type = "LESS_EQUAL" if self._match("=") else "LESS"
            self._add_token(token_type, "<=" if token_type == "LESS_EQUAL" else "<")
            return

        if char == ">":
            token_type = "GREATER_EQUAL" if self._match("=") else "GREATER"
            self._add_token(token_type, ">=" if token_type == "GREATER_EQUAL" else ">")
            return

        if char in ('"', "'"):
            self._string(char)
            return

        if char.isdigit():
            self._number()
            return

        if char.isalpha() or char == "_":
            self._identifier()
            return

        raise self._error(f"Unexpected character {char!r}.")

    def _consume_line_comment(self) -> None:
        while not self._is_at_end() and self._peek() != "\n":
            self._advance()

    def _consume_block_comment(self) -> None:
        while not self._is_at_end():
            if self._peek() == "*" and self._peek_next() == "/":
                self._advance()
                self._advance()
                return
            self._advance()
        raise self._error("Unterminated block comment.")

    def _string(self, quote: str) -> None:
        value_chars: list[str] = []
        while not self._is_at_end():
            char = self._advance()
            if char == quote:
                lexeme = self.source[self._start : self._current]
                self._add_token("STRING", lexeme, "".join(value_chars))
                return
            if char == "\\":
                if self._is_at_end():
                    raise self._error("Unterminated escape sequence.")
                esc = self._advance()
                escape_table = {
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    "\\": "\\",
                    "'": "'",
                    '"': '"',
                }
                if esc in escape_table:
                    value_chars.append(escape_table[esc])
                else:
                    value_chars.append(esc)
                continue
            value_chars.append(char)
        raise self._error("Unterminated string literal.")

    def _number(self) -> None:
        while self._peek().isdigit():
            self._advance()
        if self._peek() == "." and self._peek_next().isdigit():
            self._advance()
            while self._peek().isdigit():
                self._advance()
        lexeme = self.source[self._start : self._current]
        literal = float(lexeme) if "." in lexeme else int(lexeme)
        self._add_token("NUMBER", lexeme, literal)

    def _identifier(self) -> None:
        while self._peek().isalnum() or self._peek() == "_":
            self._advance()
        lexeme = self.source[self._start : self._current]
        token_type = "KEYWORD" if lexeme in KEYWORDS else "IDENTIFIER"
        self._add_token(token_type, lexeme, lexeme if token_type == "KEYWORD" else None)

    def _add_token(self, token_type: str, lexeme: str, literal: object = None) -> None:
        self._tokens.append(
            Token(token_type, lexeme, literal, self._start_line, self._start_column)
        )

    def _advance(self) -> str:
        char = self.source[self._current]
        self._current += 1
        if char == "\n":
            self._line += 1
            self._column = 1
        else:
            self._column += 1
        return char

    def _match(self, expected: str) -> bool:
        if self._is_at_end():
            return False
        if self.source[self._current] != expected:
            return False
        self._advance()
        return True

    def _peek(self) -> str:
        if self._is_at_end():
            return "\0"
        return self.source[self._current]

    def _peek_next(self) -> str:
        if self._current + 1 >= len(self.source):
            return "\0"
        return self.source[self._current + 1]

    def _is_at_end(self) -> bool:
        return self._current >= len(self.source)

    def _error(self, message: str) -> KSharpLexerError:
        return KSharpLexerError(
            f"{self.filename}:{self._start_line}:{self._start_column} LexerError: {message}"
        )
