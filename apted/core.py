"""Lightweight fallback implementation of the ``apted`` package.

The original project provides the APTED (All Path Tree Edit Distance)
algorithm that PaddleOCR depends on for its table metrics. The upstream
package is not available in this offline environment, so we provide a
focused re-implementation that is compatible with the small subset of the
API PaddleOCR requires: ``Config`` for cost calculation and ``APTED`` with
``compute_edit_distance``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .helpers import Tree


class Config:
    """Cost configuration for edit operations.

    PaddleOCR overrides ``rename`` to plug in custom costs, so we expose the
    same hooks as the original library. Insert/delete default to ``1.0`` which
    matches the behaviour that TEDS expects.
    """

    def __init__(self, insert_cost: float = 1.0, delete_cost: float = 1.0):
        self.insert_cost = insert_cost
        self.delete_cost = delete_cost

    def rename(self, node1: Tree, node2: Tree) -> float:
        return 0.0 if getattr(node1, "tag", None) == getattr(node2, "tag", None) else 1.0

    def insert(self, node: Tree) -> float:
        return float(self.insert_cost)

    def delete(self, node: Tree) -> float:
        return float(self.delete_cost)


@dataclass
class _TreeInfo:
    nodes: List[Tree]
    leftmost: List[int]
    keyroots: List[int]


class APTED:
    """A minimal implementation of the APTED tree edit distance algorithm."""

    def __init__(
        self, tree1: Optional[Tree], tree2: Optional[Tree], config: Optional[Config] = None
    ):
        self.tree1 = tree1
        self.tree2 = tree2
        self.config = config or Config()

    def compute_edit_distance(self) -> float:
        info1 = self._build_tree_info(self.tree1)
        info2 = self._build_tree_info(self.tree2)

        if not info1.nodes:
            return sum(self.config.insert(node) for node in info2.nodes)
        if not info2.nodes:
            return sum(self.config.delete(node) for node in info1.nodes)

        tree_dist: Dict[Tuple[int, int], float] = {}
        for i in info1.keyroots:
            for j in info2.keyroots:
                self._forest_distance(i, j, info1, info2, tree_dist)
        return tree_dist[(len(info1.nodes), len(info2.nodes))]

    def _forest_distance(
        self,
        i: int,
        j: int,
        info1: _TreeInfo,
        info2: _TreeInfo,
        tree_dist: Dict[Tuple[int, int], float],
    ) -> None:
        start_i = info1.leftmost[i]
        start_j = info2.leftmost[j]
        rows = i - start_i + 2
        cols = j - start_j + 2
        forest = [[0.0 for _ in range(cols)] for _ in range(rows)]

        for di in range(1, rows):
            idx = start_i + di - 1
            forest[di][0] = forest[di - 1][0] + self.config.delete(info1.nodes[idx - 1])
        for dj in range(1, cols):
            idx = start_j + dj - 1
            forest[0][dj] = forest[0][dj - 1] + self.config.insert(info2.nodes[idx - 1])

        for di in range(1, rows):
            idx_i = start_i + di - 1
            node_i = info1.nodes[idx_i - 1]
            for dj in range(1, cols):
                idx_j = start_j + dj - 1
                node_j = info2.nodes[idx_j - 1]
                delete_cost = forest[di - 1][dj] + self.config.delete(node_i)
                insert_cost = forest[di][dj - 1] + self.config.insert(node_j)
                if info1.leftmost[idx_i] == start_i and info2.leftmost[idx_j] == start_j:
                    rename_cost = forest[di - 1][dj - 1] + self.config.rename(node_i, node_j)
                    forest[di][dj] = min(delete_cost, insert_cost, rename_cost)
                    tree_dist[(idx_i, idx_j)] = forest[di][dj]
                else:
                    replace_cost = forest[di - 1][dj - 1] + tree_dist[(idx_i, idx_j)]
                    forest[di][dj] = min(delete_cost, insert_cost, replace_cost)

    # Helpers -----------------------------------------------------------------
    def _build_tree_info(self, tree: Optional[Tree]) -> _TreeInfo:
        postorder_nodes = self._postorder(tree)
        if not postorder_nodes:
            return _TreeInfo([], [0], [])

        leftmost = [0] * (len(postorder_nodes) + 1)
        index_map = {node: idx + 1 for idx, node in enumerate(postorder_nodes)}

        def fill_leftmost(node: Tree) -> int:
            for child in getattr(node, "children", []) or []:
                fill_leftmost(child)
            idx = index_map[node]
            children = getattr(node, "children", []) or []
            if not children:
                leftmost[idx] = idx
            else:
                leftmost[idx] = leftmost[index_map[children[0]]]
            return leftmost[idx]

        fill_leftmost(tree)  # populates leftmost array

        keyroots_map: Dict[int, int] = {}
        for idx in range(1, len(leftmost)):
            keyroots_map[leftmost[idx]] = idx
        keyroots = sorted(keyroots_map.values())

        return _TreeInfo(nodes=postorder_nodes, leftmost=leftmost, keyroots=keyroots)

    def _postorder(self, tree: Optional[Tree]) -> List[Tree]:
        nodes: List[Tree] = []
        if tree is None:
            return nodes

        def visit(node: Tree) -> None:
            for child in getattr(node, "children", []) or []:
                visit(child)
            nodes.append(node)

        visit(tree)
        return nodes

