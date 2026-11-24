"""
FastAPI Application for Academia - AI Voice Co-Pilot
Backend API Layer (PDF 03 Technical Architecture Section 1 & SDD Section 4-6)
"""

from fastapi import FastAPI, HTTPException
from app.schemas import (
    ContextItem,
    ReasoningRequest,
    ReasoningResult,
    RiskLevel,
    ScreenContext,
    SourceReference,
    ExecutionStatus,
)

app = FastAPI(
    title="Academia - AI Voice Co-Pilot API",
    description=(
        "Backend API service for AI Voice Co-Pilot. "
        "Provides endpoints for Context Management, Screen Understanding, "
        "and Multimodal AI Reasoning & Orchestration."
    ),
    version="0.1.0",
)


@app.get("/", tags=["Health"])
async def root():
    return {
        "product": "Academia - AI Voice Co-Pilot",
        "phase": "Week 1 Foundation (Day 1 Architecture)",
        "status": "online",
        "interactive_docs": "/docs",
        "schemas": [
            "SourceReference",
            "ScreenContext",
            "ContextItem",
            "ReasoningRequest",
            "ReasoningResult",
        ],
    }


@app.post(
    "/api/context",
    response_model=dict,
    tags=["Context Engine"],
    summary="Ingest and curate context (SDD Section 4.4)",
)
async def ingest_context(context_item: ContextItem):
    """
    Collects and validates a contextual item (Screen OCR, active file, terminal, etc.)
    and registers it with the Context Engine.
    """
    return {
        "status": "accepted",
        "item_id": context_item.item_id,
        "context_type": context_item.context_type,
        "relevance_score": context_item.relevance_score,
    }


@app.post(
    "/api/reason",
    response_model=ReasoningResult,
    tags=["Multimodal AI & Orchestrator"],
    summary="Execute multimodal reasoning over user query and active context",
)
async def reason(request: ReasoningRequest):
    """
    Multimodal reasoning endpoint (PRD Section 16, SDD Section 5 & 6).
    Evaluates user prompt with screen context, context items, and returns
    response text, intent, and safety-classified action plan.
    """
    # Prompt‑injection guardrail
    from .prompt_injection import is_prompt_injection
    if is_prompt_injection(request.user_query):
        raise HTTPException(status_code=400, detail="Prompt injection detected")
    # Demonstration mock logic fulfilling the schema contract
    return ReasoningResult(
        response_id=f"resp-{request.request_id}",
        request_id=request.request_id,
        session_id=request.session_id,
        user_intent="demonstration_intent",
        response_text=f"Processed query: '{request.user_query}' with {len(request.context_items)} context items.",
        reasoning_summary="Evaluated context items and user query against safety policies.",
        tool_call_required=False,
        risk_level=RiskLevel.CATEGORY_A_INFORMATIONAL,
        requires_user_approval=False,
        confidence_score=0.98,
        processing_time_ms=120.0,
        status=ExecutionStatus.SUCCESS,
    )
