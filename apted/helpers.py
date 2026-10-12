"""Helper utilities mimicking the public helpers from the original apted."""

from __future__ import annotations

from typing import Iterable, List, Optional


class Tree:
    """Simple ordered tree node used by PaddleOCR's table metric utilities."""

    def __init__(self, label: Optional[str], children: Optional[Iterable["Tree"]] = None):
        self.label = label
        self.children: List["Tree"] = list(children) if children is not None else []

    def add_child(self, child: "Tree") -> None:
        self.children.append(child)

    def __iter__(self):
        return iter(self.children)

    def child_count(self) -> int:
        return len(self.children)

