"""
Deterministic Mock Reasoning Engine
Task 2: Implement deterministic mock reasoning that produces consistent results for the same input.

Complies with:
- PRD Section 16: Multimodal AI Requirements (Intent, context combination, tool requirement)
- PRD Section 18: Human-in-the-Loop Safety (Category A, B, C, D)
- SDD Section 6: Agent Orchestrator & Action Planning
- PRD Section 24 (Risk 2 Mitigation): Confidence-aware, validated deterministic responses
"""

import hashlib
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from app.schemas.common import ExecutionStatus, RiskLevel, SourceType
from app.schemas.context import SourceReference
from app.schemas.reasoning import ActionStep, ReasoningRequest, ReasoningResult


class DeterministicMockReasoningEngine:
    """
    Mock reasoning engine providing 100% deterministic, reproducible outputs
    for identical ReasoningRequest inputs.
    
    Guarantees:
    - Same input query + context -> exactly the same intent, plan, risk classification,
      response text, confidence score, and approval requirements every single run.
    """

    def __init__(self, fixed_timestamp: Optional[datetime] = None):
        # Optional fixed timestamp for deterministic testing
        self._fixed_timestamp = fixed_timestamp

    def _compute_digest(self, request: ReasoningRequest) -> str:
        """
        Creates a stable SHA-256 digest from all input factors:
        query, modality, application name, window title, OCR text, and context items.
        """
        hasher = hashlib.sha256()
        hasher.update(request.user_query.strip().lower().encode("utf-8"))
        hasher.update(request.modality.value.encode("utf-8"))

        if request.screen_context:
            sc = request.screen_context
            hasher.update((sc.application_name or "").encode("utf-8"))
            hasher.update((sc.window_title or "").encode("utf-8"))
            hasher.update((sc.ocr_text or "").encode("utf-8"))

        for item in sorted(request.context_items, key=lambda x: x.item_id):
            hasher.update(item.item_id.encode("utf-8"))
            hasher.update(item.content.encode("utf-8"))

        return hasher.hexdigest()

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        """
        Executes deterministic multimodal reasoning on the given request.
        """
        digest = self._compute_digest(request)
        query_norm = request.user_query.strip().lower()

        # Deterministic IDs and metrics derived from digest
        response_id = f"resp-{digest[:16]}"
        int_seed = int(digest[:8], 16)
        confidence = round(0.88 + ((int_seed % 110) / 1000.0), 3)  # Stable 0.880 - 0.990
        proc_time = round(120.0 + ((int_seed % 800) / 10.0), 1)    # Stable 120.0 - 200.0 ms

        ts = self._fixed_timestamp or datetime.now(timezone.utc)

        # -------------------------------------------------------------
        # Scenario UC-01: "What am I looking at?" / Screen Understanding
        # -------------------------------------------------------------
        if any(k in query_norm for k in ["what am i looking at", "what is on my screen", "describe screen"]):
            app_name = request.screen_context.application_name if request.screen_context else "your active window"
            win_title = request.screen_context.window_title if request.screen_context else "Desktop"
            ocr_snippet = (
                request.screen_context.ocr_text[:120]
                if request.screen_context and request.screen_context.ocr_text
                else "No text detected."
            )

            return ReasoningResult(
                response_id=response_id,
                request_id=request.request_id,
                session_id=request.session_id,
                user_intent="describe_active_screen",
                response_text=(
                    f"You are currently viewing {app_name} with window title '{win_title}'. "
                    f"The screen content includes: {ocr_snippet}"
                ),
                reasoning_summary="Identified active application and visible screen OCR content.",
                tool_call_required=False,
                action_plan=[],
                risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
                requires_user_approval=False,
                approval_prompt=None,
                sources_used=self._extract_sources(request),
                confidence_score=confidence,
                processing_time_ms=proc_time,
                status=ExecutionStatus.SUCCESS,
                timestamp=ts,
            )

        # -------------------------------------------------------------
        # Scenario UC-02: "Why is this failing?" / Error Explanation
        # -------------------------------------------------------------
        elif any(k in query_norm for k in ["why is this failing", "why is this error", "explain error", "what is wrong", "exception", "failing", "error"]):
            ocr_text = (
                request.screen_context.ocr_text if request.screen_context and request.screen_context.ocr_text else ""
            )
            # Check context items for error content
            for item in request.context_items:
                ocr_text += f"\n{item.content}"

            if "zerodivisionerror" in ocr_text.lower():
                explanation = (
                    "The application failed due to a ZeroDivisionError. An operation is dividing by zero, "
                    "likely because a sequence or list passed to the average or division function was empty."
                )
            elif "typeerror" in ocr_text.lower():
                explanation = (
                    "A TypeError occurred because an operation or function received an unexpected argument type."
                )
            else:
                explanation = (
                    "The visible error indicates a runtime exception in your active script. "
                    "Review the highlighted traceback lines to correct the argument types or values."
                )

            return ReasoningResult(
                response_id=response_id,
                request_id=request.request_id,
                session_id=request.session_id,
                user_intent="explain_technical_error",
                response_text=explanation,
                reasoning_summary="Extracted error traceback from terminal/screen OCR and formulated fix recommendation.",
                tool_call_required=False,
                action_plan=[],
                risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
                requires_user_approval=False,
                approval_prompt=None,
                sources_used=self._extract_sources(request),
                confidence_score=confidence,
                processing_time_ms=proc_time,
                status=ExecutionStatus.SUCCESS,
                timestamp=ts,
            )

        # -------------------------------------------------------------
        # Scenario UC-03: "Explain this section" / Document Explanation
        # -------------------------------------------------------------
        elif any(k in query_norm for k in ["explain this section", "methodology", "summarize document", "explain paper"]):
            return ReasoningResult(
                response_id=response_id,
                request_id=request.request_id,
                session_id=request.session_id,
                user_intent="explain_document_section",
                response_text=(
                    "This section describes the methodological framework used in the research paper. "
                    "It introduces residual learning mappings to simplify network optimization and address degradation."
                ),
                reasoning_summary="Parsed document excerpt from active viewer and summarized core academic contribution.",
                tool_call_required=False,
                action_plan=[],
                risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
                requires_user_approval=False,
                approval_prompt=None,
                sources_used=self._extract_sources(request),
                confidence_score=confidence,
                processing_time_ms=proc_time,
                status=ExecutionStatus.SUCCESS,
                timestamp=ts,
            )

        # -------------------------------------------------------------
        # Scenario UC-04: "Trends" / Spreadsheet Analysis
        # -------------------------------------------------------------
        elif any(k in query_norm for k in ["trends", "analyze spreadsheet", "important trends"]):
            return ReasoningResult(
                response_id=response_id,
                request_id=request.request_id,
                session_id=request.session_id,
                user_intent="analyze_tabular_trends",
                response_text=(
                    "The spreadsheet shows strong quarter-over-quarter growth in the North (+28.8%) "
                    "and West (+26.0%) regions, while the South region contracted by -9.3%."
                ),
                reasoning_summary="Calculated growth metrics across regional tabular columns.",
                tool_call_required=False,
                action_plan=[],
                risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
                requires_user_approval=False,
                approval_prompt=None,
                sources_used=self._extract_sources(request),
                confidence_score=confidence,
                processing_time_ms=proc_time,
                status=ExecutionStatus.SUCCESS,
                timestamp=ts,
            )

        # -------------------------------------------------------------
        # Scenario High-Risk / Destructive: "Delete files" / Category D
        # -------------------------------------------------------------
        elif any(k in query_norm for k in ["delete file", "delete files", "remove directory", "rm -rf"]):
            step = ActionStep(
                step_number=1,
                tool_name="delete_files",
                tool_parameters={"target": "identified_files"},
                step_description="Permanently delete the specified files from the file system.",
                risk_level=RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE,
                requires_approval=True,
            )
            return ReasoningResult(
                response_id=response_id,
                request_id=request.request_id,
                session_id=request.session_id,
                user_intent="destructive_file_action",
                response_text=(
                    "You have requested to delete files. Because this is a destructive operation (Category D), "
                    "explicit authorization is required."
                ),
                reasoning_summary="Classified destructive request under Category D safety controls.",
                tool_call_required=True,
                action_plan=[step],
                risk_level=RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE,
                requires_user_approval=True,
                approval_prompt="HIGH RISK: Are you sure you want to permanently delete these files?",
                sources_used=[],
                confidence_score=confidence,
                processing_time_ms=proc_time,
                status=ExecutionStatus.NEEDS_APPROVAL,
                timestamp=ts,
            )

        # -------------------------------------------------------------
        # Scenario UC-08: "Move these files" / Category C (Sensitive)
        # -------------------------------------------------------------
        elif (
            any(k in query_norm for k in ["move file", "move files", "move these files", "move", "organize files", "copy to project"])
            and "delete" not in query_norm
            and "rm -rf" not in query_norm
        ):
            step = ActionStep(
                step_number=1,
                tool_name="move_file",
                tool_parameters={"source": "downloads/report.pdf", "destination": "project/"},
                step_description="Move identified files into the designated project directory.",
                risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
                requires_approval=True,
            )
            return ReasoningResult(
                response_id=response_id,
                request_id=request.request_id,
                session_id=request.session_id,
                user_intent="organize_files_action",
                response_text="I identified the files to move. Should I proceed with moving them into the project folder?",
                reasoning_summary="Generated multi-step file operation plan requiring Category C user confirmation.",
                tool_call_required=True,
                action_plan=[step],
                risk_level=RiskLevel.CATEGORY_C_SENSITIVE,
                requires_user_approval=True,
                approval_prompt="Shall I move the requested files into your project folder?",
                sources_used=[],
                confidence_score=confidence,
                processing_time_ms=proc_time,
                status=ExecutionStatus.NEEDS_APPROVAL,
                timestamp=ts,
            )

        # -------------------------------------------------------------
        # Default Deterministic Fallback
        # -------------------------------------------------------------
        else:
            return ReasoningResult(
                response_id=response_id,
                request_id=request.request_id,
                session_id=request.session_id,
                user_intent=f"general_inquiry_{digest[:8]}",
                response_text=f"Processed your request '{request.user_query}' consistently using active context.",
                reasoning_summary=f"Deterministic evaluation for signature {digest[:8]}.",
                tool_call_required=False,
                action_plan=[],
                risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
                requires_user_approval=False,
                approval_prompt=None,
                sources_used=self._extract_sources(request),
                confidence_score=confidence,
                processing_time_ms=proc_time,
                status=ExecutionStatus.SUCCESS,
                timestamp=ts,
            )

    @staticmethod
    def _extract_sources(request: ReasoningRequest) -> List[SourceReference]:
        """Collects relevant source references from the request."""
        sources: List[SourceReference] = []
        if request.screen_context:
            sources.append(
                SourceReference(
                    source_id=f"src-{request.screen_context.capture_id}",
                    source_type=SourceType.SCREEN,
                    application_name=request.screen_context.application_name,
                    window_title=request.screen_context.window_title,
                )
            )
        for item in request.context_items:
            if item.source:
                sources.append(item.source)
        return sources
