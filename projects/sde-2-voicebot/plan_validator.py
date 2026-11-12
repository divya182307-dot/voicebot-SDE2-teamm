"""
plan_validator.py — D8-9
Validates a Plan for:
  1. Missing dependencies  – a step references a step_id that doesn't exist in the plan.
  2. Cycles               – detects circular dependency chains with DFS.
  3. Duplicate step IDs   – same step_id used more than once.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Set

from schemas import Plan, ValidationResult


class PlanValidator:
    """Stateless validator; call validate() with any Plan."""

    def validate(self, plan: Plan) -> ValidationResult:
        errors: List[str] = []

        # ── 1. Collect all declared step IDs ────────────────────────────────
        declared_ids: List[str] = [s.step_id for s in plan.steps]
        id_set: Set[str] = set()
        duplicates: Set[str] = set()
        for sid in declared_ids:
            if sid in id_set:
                duplicates.add(sid)
            id_set.add(sid)
        for dup in sorted(duplicates):
            errors.append(f"Duplicate step_id: '{dup}'")

        # ── 2. Validate dependency references ───────────────────────────────
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in id_set:
                    errors.append(
                        f"Step '{step.step_id}' depends on unknown step_id '{dep}'"
                    )

        # ── 3. Cycle detection (DFS / Kahn) ─────────────────────────────────
        cycle_errors = self._detect_cycles(plan, id_set)
        errors.extend(cycle_errors)

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    # ------------------------------------------------------------------ private

    def _detect_cycles(self, plan: Plan, id_set: Set[str]) -> List[str]:
        """Kahn's algorithm (topological sort).  O(V + E)."""
        # Build adjacency and in-degree, restricted to known IDs
        graph: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = {sid: 0 for sid in id_set}

        for step in plan.steps:
            for dep in step.depends_on:
                if dep in id_set:          # only consider valid edges
                    graph[dep].append(step.step_id)
                    in_degree[step.step_id] += 1

        queue: deque[str] = deque(
            sid for sid, deg in in_degree.items() if deg == 0
        )
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbour in graph[node]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        if visited != len(id_set):
            # Find the nodes involved in the cycle for a better message
            cyclic = sorted(
                sid for sid, deg in in_degree.items() if deg > 0
            )
            return [
                f"Cycle detected among step(s): {cyclic}"
            ]
        return []

