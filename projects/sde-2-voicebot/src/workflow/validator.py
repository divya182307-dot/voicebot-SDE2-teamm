"""
Plan Validator for Academiaai AI Voicebot Agentic Workflow Engine.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Week 2 (Days 8-9 Deliverable):
Validates WorkflowPlan dependencies, cycle detection, allow-listed tools,
argument schemas, and permission scopes before or during execution.
"""

from typing import Any, Dict, Iterable, List, Optional, Set
from src.workflow.schemas import WorkflowPlan, WorkflowStep
from src.workflow.tools import ToolRegistry


class PlanValidationError(Exception):
    """Raised when a WorkflowPlan violates dependency, tool allow-list, argument, or permission rules."""
    def __init__(self, message: str, step_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.step_id = step_id
        self.details = details or {}


class PlanValidator:
    """
    Validates WorkflowPlan specifications against structural rules, DAG integrity,
    allow-listed tools, argument specifications, and caller permission scopes.
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        granted_permissions: Optional[Iterable[str]] = None,
    ):
        self.registry = registry or ToolRegistry.get_default_registry()
        self.granted_permissions: Optional[Set[str]] = (
            set(granted_permissions) if granted_permissions is not None else None
        )

    def validate_dependencies_and_cycles(self, plan: WorkflowPlan) -> None:
        """
        Validates:
        1. Duplicate step IDs
        2. Non-existent dependencies
        3. Self-dependencies
        4. Cyclic dependencies (direct and multi-step cycles via DFS)
        """
        step_ids = set()
        for step in plan.steps:
            if step.step_id in step_ids:
                raise PlanValidationError(
                    f"Duplicate step_id detected in plan: '{step.step_id}'",
                    step_id=step.step_id,
                )
            step_ids.add(step.step_id)

        # Check dependency existence and self-dependency
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' depends on non-existent step '{dep}'",
                        step_id=step.step_id,
                        details={"missing_dependency": dep},
                    )
                if dep == step.step_id:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' cannot depend on itself",
                        step_id=step.step_id,
                    )

        # Cycle detection using 3-color DFS
        # 0: unvisited, 1: visiting (in current stack), 2: visited
        visit_state: Dict[str, int] = {}
        adj: Dict[str, List[str]] = {s.step_id: s.depends_on for s in plan.steps}
        cycle_path: List[str] = []

        def dfs(node: str, stack: List[str]) -> bool:
            visit_state[node] = 1
            stack.append(node)
            for neighbor in adj.get(node, []):
                state = visit_state.get(neighbor, 0)
                if state == 1:
                    cycle_start_idx = stack.index(neighbor)
                    cycle_nodes = stack[cycle_start_idx:] + [neighbor]
                    cycle_path.extend(cycle_nodes)
                    return True
                if state == 0 and dfs(neighbor, stack):
                    return True
            stack.pop()
            visit_state[node] = 2
            return False

        for step in plan.steps:
            if visit_state.get(step.step_id, 0) == 0:
                if dfs(step.step_id, []):
                    cycle_str = " -> ".join(cycle_path)
                    raise PlanValidationError(
                        f"Cyclic dependency detected involving step '{step.step_id}': {cycle_str}",
                        step_id=step.step_id,
                        details={"cycle": cycle_path},
                    )

    def validate_tools_and_arguments(self, plan: WorkflowPlan) -> None:
        """
        Validates:
        1. Tool is present in the allow-list registry
        2. Tool arguments satisfy required fields and types
        """
        for step in plan.steps:
            if not self.registry.has(step.tool_name):
                raise PlanValidationError(
                    f"Step '{step.step_id}' references unknown tool '{step.tool_name}' not in allow-list",
                    step_id=step.step_id,
                    details={"tool_name": step.tool_name, "allowed_tools": self.registry.list_tools()},
                )
            tool = self.registry.get(step.tool_name)
            try:
                tool.validate_arguments(step.arguments)
            except ValueError as ve:
                raise PlanValidationError(
                    f"Invalid arguments for step '{step.step_id}' with tool '{step.tool_name}': {str(ve)}",
                    step_id=step.step_id,
                    details={"arguments": step.arguments, "error": str(ve)},
                ) from ve

    def validate_permission_scopes(self, plan: WorkflowPlan) -> None:
        """
        Validates that the caller holds all required permissions for every tool in the plan.
        """
        if self.granted_permissions is None:
            return
        for step in plan.steps:
            if not self.registry.has(step.tool_name):
                continue
            tool = self.registry.get(step.tool_name)
            try:
                tool.check_permissions(self.granted_permissions)
            except PermissionError as pe:
                raise PlanValidationError(
                    f"Permission check failed for step '{step.step_id}' ({step.tool_name}): {str(pe)}",
                    step_id=step.step_id,
                    details={"tool_name": step.tool_name, "error": str(pe)},
                ) from pe

    def validate_plan(self, plan: WorkflowPlan) -> None:
        """
        Comprehensive validation of plan:
        1. Dependencies and cycle checks
        2. Allow-list tool verification and argument checking
        3. Permission scope verification
        """
        self.validate_dependencies_and_cycles(plan)
        self.validate_tools_and_arguments(plan)
        self.validate_permission_scopes(plan)

