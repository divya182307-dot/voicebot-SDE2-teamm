"""Week 3 workflow gateway with safe mock tools."""

import logging

from src.workflow.executor import WorkflowExecutor

from src.workflow.schemas import (
    WorkflowPlan,
    WorkflowStep,
    RiskLevel,
    ToolSpec
)

from src.workflow.tools import BaseTool, ToolRegistry


logger = logging.getLogger("voicebot.workflow_gateway")


class MockFileActionTool(BaseTool):

    def __init__(self, name, risk, properties, required):
        super().__init__(
            ToolSpec(
                name=name,
                purpose="Simulate a file action without modifying files.",
                risk_level=risk,
                input_schema={
                    "type": "object",
                    "properties": properties,
                    "required": required
                },
                permission_requirements=["mock:file_action"]
            )
        )

    def execute(self, arguments):
        self.validate_arguments(arguments)

        return {
            "status": "success",
            "tool": self.name,
            "mock_mode": True,
            "files_modified": False
        }


def build_mock_registry():

    registry = ToolRegistry.get_default_registry()

    registry.register(
        MockFileActionTool(
            name="move_file",
            risk=RiskLevel.SENSITIVE,
            properties={
                "source": {"type": "string"},
                "destination": {"type": "string"}
            },
            required=["source", "destination"]
        )
    )

    registry.register(
        MockFileActionTool(
            name="delete_files",
            risk=RiskLevel.DESTRUCTIVE,
            properties={
                "target": {"type": "string"}
            },
            required=["target"]
        )
    )

    return registry


RISK_MAPPING = {
    "category_a_informational": RiskLevel.INFORMATIONAL,
    "category_b_low_risk": RiskLevel.LOW_RISK,
    "category_c_sensitive": RiskLevel.SENSITIVE,
    "category_d_high_risk_destructive": RiskLevel.DESTRUCTIVE
}


def build_workflow_plan(
    reasoning_result,
    session_id,
    correlation_id
):

    registry = build_mock_registry()
    steps = []

    for action in reasoning_result.action_plan:

        risk = RISK_MAPPING.get(
            action.risk_level.value,
            RiskLevel.DESTRUCTIVE
        )

        tool = registry.get(action.tool_name)

        registry.validate_tool_call(
            action.tool_name,
            action.tool_parameters,
            caller_permissions=[
                "kb:read",
                "schedule:read",
                "mock:file_action"
            ]
        )

        if tool.risk_level == RiskLevel.DESTRUCTIVE:
            risk = RiskLevel.DESTRUCTIVE

        elif (
            tool.risk_level == RiskLevel.SENSITIVE
            and risk != RiskLevel.DESTRUCTIVE
        ):
            risk = RiskLevel.SENSITIVE

        step = WorkflowStep(
            tool_name=action.tool_name,
            arguments=action.tool_parameters,
            description=action.step_description,
            risk_level=risk,
            requires_approval=(
                action.requires_approval
                or reasoning_result.requires_user_approval
                or risk in (
                    RiskLevel.SENSITIVE,
                    RiskLevel.DESTRUCTIVE
                )
            ),
            depends_on=(
                [steps[-1].step_id] if steps else []
            ),
            is_idempotent=False
        )

        steps.append(step)

    return WorkflowPlan(
        session_id=session_id,
        correlation_id=correlation_id,
        title="Mock reasoning action plan",
        steps=steps
    )


class WorkflowGateway:

    def __init__(self, plan: WorkflowPlan):

        self.plan = plan

        self.executor = WorkflowExecutor(
            plan,
            registry=build_mock_registry(),
            caller_permissions=[
                "kb:read",
                "schedule:read",
                "mock:file_action"
            ]
        )

        self.log_context = {
            "session_id": plan.session_id,
            "correlation_id": plan.correlation_id
        }

    def execute(self):

        logger.info(
            "Workflow started",
            extra=self.log_context
        )

        return self.executor.run()

    def pending_approvals(self):
        return self.executor.pending_approvals

    def approve(self, approval_id):

        logger.info(
            "Workflow approval received",
            extra=self.log_context
        )

        return self.executor.approve_request(
            approval_id=approval_id,
            approver="human_operator",
            resume=True
        )

    def reject(self, approval_id):

        logger.info(
            "Workflow approval rejected",
            extra=self.log_context
        )

        return self.executor.reject_request(
            approval_id=approval_id,
            reason="Rejected by user"
        )
