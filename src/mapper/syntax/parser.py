from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from lark import Lark, Token, Tree
from lark.exceptions import (
    UnexpectedCharacters,
    UnexpectedEOF,
    UnexpectedInput,
    UnexpectedToken,
)
from lark.indenter import Indenter

from mapper.ast import Node
from mapper.errors import DslSyntaxError

INDENT_WIDTH: Final[int] = 2


class DslIndenter(Indenter):
    """Turns the `_NL` tokens into `_INDENT` / `_DEDENT` tokens."""

    @property
    def NL_type(self) -> str:
        return "_NL"

    @property
    def OPEN_PAREN_types(self) -> list[str]:
        return ["LPAR"]

    @property
    def CLOSE_PAREN_types(self) -> list[str]:
        return ["RPAR"]

    @property
    def INDENT_type(self) -> str:
        return "_INDENT"

    @property
    def DEDENT_type(self) -> str:
        return "_DEDENT"

    @property
    def tab_len(self) -> int:
        return 8


class MappinParser:
    """Parses .mapping scripts. Raises DslSyntaxError on any syntax problem."""

    def __init__(self, grammar_path: Path | None = None) -> None:
        if grammar_path is None:
            grammar_path = Path(__file__).with_name("mapping.lark")
        if not grammar_path.is_file():
            raise FileNotFoundError(f"grammar file not found: {grammar_path}")

        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).parent

        self._parser = Lark(
            grammar_path.read_text(encoding="utf-8"),
            parser="lalr",
            postlex=DslIndenter(),
            propagate_positions=True,
            cache=str(base / "grammar.cache"),
        )

    def parse(self, text: str) -> Tree[Token]:
        self._check_indentation(text)
        normalized = text.rstrip() + "\n"
        try:
            return self._parser.parse(normalized)  # type: ignore
        except UnexpectedInput as exc:
            raise self._to_syntax_error(exc, normalized) from exc

    @staticmethod
    def _check_indentation(text: str) -> None:
        """Enforce: block indentation uses multiples of INDENT_WIDTH spaces, no tabs."""
        for lnmbr, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue

            leading = line[: len(line) - len(line.lstrip(" \t"))]
            if "\t" in leading:
                raise DslSyntaxError(
                    "Tabs are not allowed for indentation",
                    node=Node(line=lnmbr, column=1),
                )

            width = len(leading)
            if width % INDENT_WIDTH != 0:
                raise DslSyntaxError(
                    f"Indentation must be a multiple of {INDENT_WIDTH} spaces, got {width}",
                    node=Node(line=lnmbr, column=1),
                )

    @staticmethod
    def _to_syntax_error(exc: UnexpectedInput, text: str) -> DslSyntaxError:
        """Translate Lark's exceptions into self defined error type with a position."""
        last_line = max(1, len(text.splitlines()))
        line = exc.line if exc.line >= 1 else last_line
        column = exc.column if exc.column >= 1 else 1
        if isinstance(exc, UnexpectedToken):
            expected = ", ".join(sorted(exc.expected))
            message = f"unexpected {exc.token.type} {str(exc.token)!r}; expected one of: {expected}"
        elif isinstance(exc, UnexpectedCharacters):
            position = exc.pos_in_stream
            found = text[position] if position is not None and position < len(text) else "?"
            message = f"unexpected character {found!r}"
        elif isinstance(exc, UnexpectedEOF):
            message = "unexpected end of file"
        else:
            message = "unexpected input"
        return DslSyntaxError(message, node=Node(line=line, column=column))


def main() -> None:
    from pathlib import Path

    content = (Path.cwd() / "example.mapping").read_text("utf-8-sig")
    parser = MappinParser()
    text = parser.parse(content)
    print(text)


if __name__ == "__main__":
    import sys

    sys.exit(main())
