"""
tool_registry.py — D8-9
Allow-listed tool registry with:
  • Registration of ToolDefinition entries only.
  • Argument presence + type validation on every ToolCall.
  • Permission-scope enforcement against the scopes granted to a Plan.
  • No unknown tool is ever executable.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from schemas import (
    PermissionScope,
    Plan,
    ToolCall,
    ToolDefinition,
    ValidationResult,
)

_PYTHON_TYPE_MAP: Dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
}


class ToolRegistry:
    """Central registry.  Only tools explicitly registered here may run."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    # ------------------------------------------------------------------ public

    def register(self, tool: ToolDefinition) -> None:
        """Add a tool to the allow-list.  Raises if name is duplicate."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    def validate_call(
        self,
        call: ToolCall,
        granted_scopes: List[PermissionScope],
    ) -> ValidationResult:
        """
        Validate one ToolCall against the registry and granted scopes.
        Returns ValidationResult(valid=True) iff:
          - tool is allow-listed
          - all required args are present with the correct type
          - no undeclared args are supplied
          - the plan's granted_scopes cover all required_scopes of the tool
        """
        errors: List[str] = []

        # 1. Tool must be allow-listed
        defn = self._tools.get(call.tool_name)
        if defn is None:
            return ValidationResult(
                valid=False,
                errors=[f"Tool '{call.tool_name}' is not in the allow-list."],
            )

        # 2. Scope enforcement
        missing_scopes = [
            s for s in defn.required_scopes if s not in granted_scopes
        ]
        for scope in missing_scopes:
            errors.append(
                f"Tool '{call.tool_name}' requires scope '{scope.value}' "
                f"which is not granted to this plan."
            )

        # 3. No undeclared arguments
        declared_arg_names = {spec.name for spec in defn.args}
        for supplied_name in call.arguments:
            if supplied_name not in declared_arg_names:
                errors.append(
                    f"Tool '{call.tool_name}': unknown argument '{supplied_name}'."
                )

        # 4. Required arguments present and correctly typed
        for spec in defn.args:
            if spec.name not in call.arguments:
                if spec.required:
                    errors.append(
                        f"Tool '{call.tool_name}': missing required argument '{spec.name}'."
                    )
                continue
            value: Any = call.arguments[spec.name]
            expected_type = _PYTHON_TYPE_MAP.get(spec.type)
            if expected_type is not None and not isinstance(value, expected_type):
                errors.append(
                    f"Tool '{call.tool_name}': argument '{spec.name}' must be "
                    f"type '{spec.type}', got '{type(value).__name__}'."
                )

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_plan_tools(self, plan: Plan) -> ValidationResult:
        """Validate every ToolCall in a plan against the registry."""
        all_errors: List[str] = []
        for step in plan.steps:
            result = self.validate_call(step.tool_call, plan.granted_scopes)
            all_errors.extend(result.errors)
        return ValidationResult(valid=len(all_errors) == 0, errors=all_errors)

