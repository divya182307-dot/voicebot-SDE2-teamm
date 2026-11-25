"""
Mock Tools and Tool Registry for Academiaai AI Voicebot Agentic Workflow.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Week 1 (Days 3-4): Provides two harmless mock tools with no external sending, and a ToolRegistry.
Week 2 (Days 8-9): Allow-listed tool registry with strict argument validation and permission scope checks.
Everything runs in mock mode (safe, deterministic, sandboxed execution).
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
from uuid import uuid4

from src.workflow.schemas import RiskLevel, ToolFailureBehavior, ToolSpec


class BaseTool(ABC):
    """
    Abstract base class for all tools in the agentic workflow.
    Each tool exposes a ToolSpec, argument validation, permission enforcement, and an execute method.
    """

    def __init__(self, spec: ToolSpec):
        self.spec = spec

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def risk_level(self) -> RiskLevel:
        return self.spec.risk_level

    @property
    def is_consequential(self) -> bool:
        return self.risk_level in (RiskLevel.SENSITIVE, RiskLevel.DESTRUCTIVE)

    def validate_arguments(self, arguments: Dict[str, Any]) -> None:
        """
        Validates arguments against the required properties and expected types in input_schema.
        Raises ValueError if required arguments are missing or argument types are invalid.
        """
        required = self.spec.input_schema.get("required", [])
        for field in required:
            if field not in arguments:
                raise ValueError(
                    f"Tool '{self.name}' missing required argument: '{field}'"
                )

        properties = self.spec.input_schema.get("properties", {})
        for field, value in arguments.items():
            if field in properties:
                prop_info = properties[field]
                expected_type = prop_info.get("type")
                if expected_type == "string" and not isinstance(value, str):
                    raise ValueError(f"Tool '{self.name}' argument '{field}' must be a string, got {type(value).__name__}")
                elif expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                    raise ValueError(f"Tool '{self.name}' argument '{field}' must be an integer, got {type(value).__name__}")
                elif expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                    raise ValueError(f"Tool '{self.name}' argument '{field}' must be a number, got {type(value).__name__}")
                elif expected_type == "boolean" and not isinstance(value, bool):
                    raise ValueError(f"Tool '{self.name}' argument '{field}' must be a boolean, got {type(value).__name__}")
                elif expected_type == "array" and not isinstance(value, list):
                    raise ValueError(f"Tool '{self.name}' argument '{field}' must be a list/array, got {type(value).__name__}")
                elif expected_type == "object" and not isinstance(value, dict):
                    raise ValueError(f"Tool '{self.name}' argument '{field}' must be an object/dict, got {type(value).__name__}")

    def check_permissions(self, granted_permissions: Optional[Iterable[str]]) -> None:
        """
        Enforces permission scopes.
        Raises PermissionError if any required permission is not present in granted_permissions.
        """
        if granted_permissions is None:
            return
        granted_set = set(granted_permissions)
        for req in self.spec.permission_requirements:
            if req not in granted_set:
                raise PermissionError(
                    f"Tool '{self.name}' requires permission '{req}', but caller only holds: {sorted(list(granted_set))}"
                )

    @abstractmethod
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes the tool with provided arguments.
        Runs safely in mock mode.
        """
        pass


class MockKnowledgeSearchTool(BaseTool):
    """
    Harmless Mock Tool 1: Knowledge Search Tool.
    Risk Level: INFORMATIONAL (harmless read-only query).
    Searches course catalogs, academic FAQs, and syllabus information.
    """

    def __init__(self):
        spec = ToolSpec(
            name="knowledge_search",
            purpose="Searches the university academic knowledge base, course schedules, and FAQ articles.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword or query phrase"},
                    "max_results": {"type": "integer", "description": "Maximum entries to return", "default": 3},
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "count": {"type": "integer"},
                    "results": {"type": "array"},
                },
            },
            permission_requirements=["kb:read"],
            risk_level=RiskLevel.INFORMATIONAL,
            failure_behavior=ToolFailureBehavior.FAIL_WORKFLOW,
        )
        super().__init__(spec)

        # Built-in mock knowledge repository
        self._corpus = [
            {
                "id": "KB-101",
                "title": "CS101: Introduction to Computer Science",
                "content": "CS101 lectures occur Mondays and Wednesdays at 10:00 AM. Final project submission due Week 12.",
                "keywords": ["cs101", "computer science", "schedule", "lecture"],
            },
            {
                "id": "KB-102",
                "title": "Semester Registration & Add/Drop Deadline",
                "content": "The Fall semester add/drop deadline is Friday at 11:59 PM. Late registrations require Dean approval.",
                "keywords": ["registration", "deadline", "add/drop", "semester", "date"],
            },
            {
                "id": "KB-103",
                "title": "Tuition Fee Payment and Payment Plans",
                "content": "Tuition fees can be paid online via the student portal. Installment options are available for eligible students.",
                "keywords": ["tuition", "fee", "payment", "scholarship", "finance"],
            },
            {
                "id": "KB-104",
                "title": "Examination Policy & Grading Scale",
                "content": "Exams are strictly proctored. Passing grade is 50%. Grade appeal window closes 7 days post-results.",
                "keywords": ["exam", "grading", "policy", "appeal", "results"],
            },
        ]

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_arguments(arguments)
        query = str(arguments.get("query", "")).lower()
        max_results = int(arguments.get("max_results", 3))

        hits = []
        for item in self._corpus:
            if (
                query in item["title"].lower()
                or query in item["content"].lower()
                or any(k in query for k in item["keywords"])
            ):
                hits.append(item)
            if len(hits) >= max_results:
                break

        # Fallback if no exact keyword matched
        if not hits:
            hits = [
                {
                    "id": "KB-000",
                    "title": f"General Query Match: {arguments.get('query')}",
                    "content": f"Mock knowledge lookup completed for '{arguments.get('query')}'. Standard policies apply.",
                    "keywords": [query],
                }
            ]

        return {
            "status": "success",
            "query": arguments.get("query"),
            "count": len(hits),
            "results": hits,
            "mock_mode": True,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }


class MockCourseScheduleTool(BaseTool):
    """
    Harmless Mock Tool 2: Course Schedule Lookup Tool.
    Risk Level: INFORMATIONAL (harmless read-only schedule lookup).
    Queries course timings, classroom assignments, and instructor info.
    Operates strictly locally in mock mode with no external sending.
    """

    def __init__(self):
        spec = ToolSpec(
            name="course_schedule",
            purpose="Retrieves course schedules, lecture timings, classroom locations, and instructor details.",
            input_schema={
                "type": "object",
                "properties": {
                    "course_code": {
                        "type": "string",
                        "description": "Academic course code (e.g., CS101, MATH201, PHY101)",
                    },
                    "term": {
                        "type": "string",
                        "description": "Academic term or semester (e.g., Fall 2026, Spring 2027)",
                        "default": "Fall 2026",
                    },
                },
                "required": ["course_code"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "course_code": {"type": "string"},
                    "course_name": {"type": "string"},
                    "term": {"type": "string"},
                    "instructor": {"type": "string"},
                    "schedule": {"type": "string"},
                    "location": {"type": "string"},
                    "credits": {"type": "integer"},
                    "mock_mode": {"type": "boolean"},
                },
            },
            permission_requirements=["schedule:read"],
            risk_level=RiskLevel.INFORMATIONAL,
            failure_behavior=ToolFailureBehavior.FAIL_WORKFLOW,
        )
        super().__init__(spec)

        self._schedules = {
            "CS101": {
                "course_name": "Introduction to Computer Science",
                "instructor": "Dr. Alan Turing",
                "schedule": "Mondays and Wednesdays 10:00 AM - 11:30 AM",
                "location": "Turing Hall, Room 101",
                "credits": 4,
            },
            "MATH201": {
                "course_name": "Linear Algebra & Differential Equations",
                "instructor": "Dr. Katherine Johnson",
                "schedule": "Tuesdays and Thursdays 02:00 PM - 03:30 PM",
                "location": "Euler Building, Room 204",
                "credits": 3,
            },
            "PHY101": {
                "course_name": "General Physics I",
                "instructor": "Dr. Richard Feynman",
                "schedule": "Fridays 09:00 AM - 12:00 PM",
                "location": "Newton Science Complex, Lab B",
                "credits": 4,
            },
            "BIO110": {
                "course_name": "Fundamentals of Molecular Biology",
                "instructor": "Dr. Rosalind Franklin",
                "schedule": "Mondays and Wednesdays 01:00 PM - 02:30 PM",
                "location": "Darwin Life Sciences, Room 105",
                "credits": 3,
            },
        }

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_arguments(arguments)
        course_code = str(arguments.get("course_code", "")).strip().upper()
        term = str(arguments.get("term", "Fall 2026"))

        if course_code in self._schedules:
            entry = self._schedules[course_code]
            return {
                "status": "success",
                "course_code": course_code,
                "course_name": entry["course_name"],
                "term": term,
                "instructor": entry["instructor"],
                "schedule": entry["schedule"],
                "location": entry["location"],
                "credits": entry["credits"],
                "mock_mode": True,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }

        return {
            "status": "success",
            "course_code": course_code,
            "course_name": f"Course {course_code}",
            "term": term,
            "instructor": "Staff",
            "schedule": "TBD - Consult Department Office",
            "location": "Main Campus",
            "credits": 3,
            "mock_mode": True,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }


class ToolRegistry:
    """
    Registry maintaining allow-listed tools for the agentic workflow engine.
    Ensures safe tool discovery, schema introspection, permission scope checks,
    and execution routing. Unknown tools are strictly rejected.
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Registers a tool in the registry."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """Retrieves a registered tool by name. Raises KeyError if not registered."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered in the allow-list.")
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Checks if a tool is registered."""
        return name in self._tools

    def list_tools(self) -> List[str]:
        """Returns list of registered tool names."""
        return list(self._tools.keys())

    def list_specs(self) -> List[ToolSpec]:
        """Returns ToolSpec for all registered tools."""
        return [tool.spec for tool in self._tools.values()]

    def validate_tool_call(
        self,
        name: str,
        arguments: Dict[str, Any],
        caller_permissions: Optional[Iterable[str]] = None,
    ) -> None:
        """
        Validates tool presence in allow-list, argument validity, and permission scopes.
        Raises KeyError if tool not registered.
        Raises PermissionError if caller lacks required permissions.
        Raises ValueError if arguments fail schema validation.
        """
        if not self.has(name):
            raise KeyError(f"Tool '{name}' is not registered in the allow-list.")
        tool = self.get(name)
        tool.check_permissions(caller_permissions)
        tool.validate_arguments(arguments)

    def execute(
        self,
        name: str,
        arguments: Dict[str, Any],
        caller_permissions: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """
        Safely executes an allow-listed tool after checking permissions and argument validity.
        """
        self.validate_tool_call(name, arguments, caller_permissions)
        return self.get(name).execute(arguments)

    @classmethod
    def get_default_registry(cls) -> "ToolRegistry":
        """
        Creates and returns a registry populated with the two harmless mock tools:
        - MockKnowledgeSearchTool (Harmless / Informational read-only knowledge query)
        - MockCourseScheduleTool (Harmless / Informational read-only schedule lookup)
        No external sending tools are included.
        """
        registry = cls()
        registry.register(MockKnowledgeSearchTool())
        registry.register(MockCourseScheduleTool())
        return registry
