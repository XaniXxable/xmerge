from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Node:
    """Position in the .map file, for error messages."""

    line: int
    column: int
