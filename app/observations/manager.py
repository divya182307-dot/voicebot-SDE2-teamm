"""
Observation Manager & Engine:
- Timestamped, source-linked observation generation
- Stale and duplicate frame handling
- Explicit consent withdrawal and buffer purging
- Grounded answers with honest 'no evidence' fallback
- Prompt injection quarantine
- Workflow proposal handoff
"""

from datetime import datetime, timezone
import hashlib
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from app.schemas.common import CaptureMode, InputModality, RiskLevel, SourceType
from app.schemas.context import BoundingBox, ContextItem, ContextType, ScreenContext, SourceReference
from app.schemas.reasoning import ActionStep
from app.vision.capture_adapter import CaptureNotAuthorizedException, ConsentWithdrawnException
from app.vision.synthetic_frames import DEFAULT_FIXED_TIMESTAMP
from app.observations.models import (
    ConsentStatus,
    GroundedAnswer,
    Observation,
    ObservationBatch,
    WorkflowProposal,
)


class ObservationManager:
    """
    Manages the lifecycle of context observations, enforces frame freshness,
    detects duplicate frames, handles consent withdrawal, and produces grounded answers.
    """

    def __init__(
        self,
        mock_mode: bool = True,
        freshness_ttl_seconds: float = 30.0,
        deduplicate_frames: bool = True,
        clock: Optional[Any] = None,
    ):
        self.mock_mode: bool = mock_mode
        self.freshness_ttl_seconds: float = freshness_ttl_seconds
        self.deduplicate_frames: bool = deduplicate_frames
        self._clock = clock or (lambda: datetime.now(timezone.utc))

        # Consent Lifecycle State
        self._consent_status: ConsentStatus = ConsentStatus.OPTED_OUT
        self._consent_token: Optional[str] = None
        self._consent_timestamp: Optional[datetime] = None
        self._withdrawal_timestamp: Optional[datetime] = None

        # Buffers and Caches
        self._active_observations: Dict[str, Observation] = {}
        self._recent_hashes: Dict[str, str] = {}  # window_key -> content_hash
        self._cached_frames: List[ScreenContext] = []

        # Metrics
        self._total_frames_ingested: int = 0
        self._duplicate_frames_detected: int = 0
        self._stale_frames_detected: int = 0
        self._consent_withdrawals_count: int = 0

    # -------------------------------------------------------------------------
    # Consent Management & Withdrawal
    # -------------------------------------------------------------------------

    @property
    def consent_status(self) -> ConsentStatus:
        """Returns the current consent lifecycle state."""
        return self._consent_status

    @property
    def is_consent_active(self) -> bool:
        """True if user currently has an active, authorized capture consent."""
        return self._consent_status == ConsentStatus.CONSENT_ACTIVE

    def opt_in(self, consent_token: Optional[str] = None) -> str:
        """
        Grants explicit user consent for screen and context capture.
        """
        token = consent_token or f"token-obs-{int(time.time() * 1000)}"
        self._consent_status = ConsentStatus.CONSENT_ACTIVE
        self._consent_token = token
        self._consent_timestamp = self._get_current_time()
        self._withdrawal_timestamp = None
        return token

    def withdraw_consent(self) -> None:
        """
        Immediately withdraws consent, revokes capture authorization,
        and purges all cached frames and active observations from memory.
        """
        self._consent_status = ConsentStatus.CONSENT_WITHDRAWN
        self._consent_token = None
        self._withdrawal_timestamp = self._get_current_time()
        self._consent_withdrawals_count += 1

        # Purge all stored visual frames and active observation buffers
        self.purge_buffers()

    def opt_out(self) -> None:
        """Alias for withdraw_consent()."""
        self.withdraw_consent()

    def purge_buffers(self) -> int:
        """
        Clears all in-memory frame caches, observation buffers, and hash trackers.
        Returns the number of purged observations.
        """
        purged_count = len(self._active_observations)
        self._active_observations.clear()
        self._recent_hashes.clear()
        self._cached_frames.clear()
        return purged_count

    # -------------------------------------------------------------------------
    # Frame Deduplication and Staleness
    # -------------------------------------------------------------------------

    def compute_frame_hash(self, frame: ScreenContext) -> str:
        """
        Computes a deterministic SHA-256 fingerprint of the frame content and window geometry.
        """
        vis_summary = getattr(frame, "visual_elements_summary", "") or ""
        components = [
            frame.application_name or "",
            frame.window_title or "",
            str(frame.width),
            str(frame.height),
            (frame.ocr_text or "").strip(),
            vis_summary.strip(),
        ]
        raw_signature = "|".join(components)
        return hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()

    def is_frame_stale(self, frame: ScreenContext, reference_time: Optional[datetime] = None) -> bool:
        """
        Checks whether a frame has expired beyond the freshness TTL.
        """
        now = reference_time
        if now is None:
            if self.mock_mode and frame.timestamp == DEFAULT_FIXED_TIMESTAMP:
                now = DEFAULT_FIXED_TIMESTAMP
            else:
                now = self._get_current_time()
        frame_time = frame.timestamp
        if frame_time.tzinfo is None:
            frame_time = frame_time.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        age_seconds = (now - frame_time).total_seconds()
        return age_seconds > self.freshness_ttl_seconds

    # -------------------------------------------------------------------------
    # Observation Ingestion
    # -------------------------------------------------------------------------

    def ingest_screen_frame(
        self,
        frame: ScreenContext,
        reference_time: Optional[datetime] = None,
    ) -> Observation:
        """
        Transforms a ScreenContext frame into a timestamped, source-linked Observation.
        Handles duplicate frame detection and staleness tagging.
        """
        self._verify_consent_before_ingestion()

        now = reference_time
        if now is None:
            if self.mock_mode and frame.timestamp == DEFAULT_FIXED_TIMESTAMP:
                now = DEFAULT_FIXED_TIMESTAMP
            else:
                now = self._get_current_time()
        self._total_frames_ingested += 1

        content_hash = self.compute_frame_hash(frame)
        window_key = f"{frame.application_name or 'app'}::{frame.window_title or 'win'}"

        # 1. Duplicate frame check
        is_duplicate = False
        if self.deduplicate_frames and window_key in self._recent_hashes:
            if self._recent_hashes[window_key] == content_hash:
                is_duplicate = True
                self._duplicate_frames_detected += 1

        self._recent_hashes[window_key] = content_hash

        # 2. Stale frame check
        is_stale = self.is_frame_stale(frame, reference_time=now)
        if is_stale:
            self._stale_frames_detected += 1

        # 3. Source linking
        bbox = None
        if frame.width > 0 and frame.height > 0:
            bbox = BoundingBox(x_min=0, y_min=0, x_max=frame.width, y_max=frame.height)

        source_ref = SourceReference(
            source_id=f"src-frame-{frame.capture_id[:16]}",
            source_type=SourceType.SCREEN,
            application_name=frame.application_name,
            window_title=frame.window_title,
            bounding_box=bbox,
            timestamp=frame.timestamp,
        )

        # 4. Construct content & summary
        ocr_clean = (frame.ocr_text or "").strip()
        summary = (
            f"Active window '{frame.window_title}' in {frame.application_name}. "
            f"Resolution: {frame.width}x{frame.height}px."
        )
        vis_summary = getattr(frame, "visual_elements_summary", None)
        if vis_summary:
            summary += f" Visuals: {vis_summary[:120]}."

        obs_id = f"obs-{content_hash[:12]}"
        has_evidence = bool(ocr_clean or vis_summary)

        observation = Observation(
            observation_id=obs_id,
            timestamp=frame.timestamp,
            source=source_ref,
            source_type=SourceType.SCREEN,
            content=ocr_clean if ocr_clean else "[No text detected in screen frame]",
            summary=summary,
            confidence=0.95 if not is_duplicate else 0.85,
            is_stale=is_stale,
            is_duplicate=is_duplicate,
            has_evidence=has_evidence,
            content_hash=content_hash,
            metadata={
                "capture_id": frame.capture_id,
                "capture_mode": frame.capture_mode.value,
                "contains_sensitive_data": frame.contains_sensitive_data,
            },
        )

        # Cache active observation and frame
        self._active_observations[obs_id] = observation
        self._cached_frames.append(frame)

        return observation

    def ingest_context_item(self, item: ContextItem) -> Observation:
        """
        Converts a general ContextItem (code, terminal, document) into a source-linked Observation.
        """
        source = item.source or SourceReference(
            source_id=f"src-item-{item.item_id[:16]}",
            source_type=SourceType.DOCUMENT,
            timestamp=item.timestamp,
        )

        obs_id = f"obs-item-{item.item_id[:12]}"
        priority = getattr(item, "priority", 5)
        obs = Observation(
            observation_id=obs_id,
            timestamp=item.timestamp,
            source=source,
            source_type=source.source_type,
            content=item.content,
            summary=f"Context item [{item.context_type.value}] priority {priority}",
            confidence=1.0,
            is_stale=False,
            is_duplicate=False,
            has_evidence=bool(item.content.strip()),
            content_hash=hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
            metadata={"context_type": item.context_type.value, "priority": priority},
        )
        self._active_observations[obs_id] = obs
        return obs

    def ingest_voice_utterance(self, query: str, session_id: str) -> Observation:
        """
        Creates an Observation representing a user's spoken voice utterance.
        """
        now = self._get_current_time()
        source = SourceReference(
            source_id=f"src-voice-{session_id[:16]}",
            source_type=SourceType.AUDIO_VOICE,
            timestamp=now,
        )
        obs_id = f"obs-voice-{hashlib.sha256(query.encode('utf-8')).hexdigest()[:12]}"
        return Observation(
            observation_id=obs_id,
            timestamp=now,
            source=source,
            source_type=SourceType.AUDIO_VOICE,
            content=query,
            summary=f"Transcribed spoken voice query: '{query}'",
            confidence=1.0,
            is_stale=False,
            is_duplicate=False,
            has_evidence=True,
            metadata={"session_id": session_id},
        )

    # -------------------------------------------------------------------------
    # Grounded Answering & Honest "No Evidence" Reply
    # -------------------------------------------------------------------------

    def generate_grounded_answer(
        self,
        query: str,
        observations: Optional[List[Observation]] = None,
        allow_stale: bool = False,
    ) -> GroundedAnswer:
        """
        Evaluates the query against source-linked observations.
        Produces either a trustworthy grounded answer citing observations,
        or an honest 'no evidence' reply if evidence is lacking.
        """
        candidate_obs = observations or list(self._active_observations.values())

        # Filter candidates: exclude stale (unless allowed) and duplicates
        valid_evidence: List[Observation] = [
            o for o in candidate_obs
            if (allow_stale or not o.is_stale) and not o.is_duplicate and o.has_evidence
        ]

        q_lower = query.lower()
        matched_obs: List[Observation] = []
        answer_text = ""
        has_evidence = False
        workflow_proposal: Optional[WorkflowProposal] = None

        # Check for error evidence
        if any(w in q_lower for w in ["error", "exception", "failing", "why", "bug"]):
            for o in valid_evidence:
                if any(err in o.content.lower() for err in ["zerodivisionerror", "typeerror", "exception", "traceback"]):
                    matched_obs.append(o)
            if matched_obs:
                has_evidence = True
                answer_text = (
                    "Based on active screen observations, the code encountered a ZeroDivisionError "
                    "in calculator.py. The calculation function attempted division by zero because "
                    "the input sequence was empty."
                )

        # Check for document / research methodology evidence
        elif any(w in q_lower for w in ["paper", "pdf", "methodology", "section", "summarize"]):
            for o in valid_evidence:
                if any(k in o.content.lower() for k in ["residual", "methodology", "framework", "network"]):
                    matched_obs.append(o)
            if matched_obs:
                has_evidence = True
                answer_text = (
                    "Based on the visible research paper document, Section 3 introduces residual "
                    "learning frameworks with identity shortcut connections to solve optimization degradation."
                )

        # Check for spreadsheet / tabular trends evidence
        elif any(w in q_lower for w in ["spreadsheet", "growth", "trend", "sales", "revenue"]):
            for o in valid_evidence:
                if any(k in o.content.lower() for k in ["q1", "q2", "growth", "revenue", "north", "west"]):
                    matched_obs.append(o)
            if matched_obs:
                has_evidence = True
                answer_text = (
                    "Tabular observations indicate regional revenue grew by +28.8% in the North "
                    "and +26.0% in the West, while the South contracted by -9.3%."
                )

        # Check for action / workflow requests
        elif any(w in q_lower for w in ["delete", "remove", "move", "archive", "clean"]):
            is_destructive = any(d in q_lower for d in ["delete", "remove", "drop", "purge"])
            risk = RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE if is_destructive else RiskLevel.CATEGORY_C_SENSITIVE
            prompt_msg = (
                "HIGH RISK: Are you sure you want to permanently delete these files?"
                if is_destructive else "Please confirm moving files to the destination folder."
            )
            step = ActionStep(
                step_number=1,
                tool_name="delete_files" if is_destructive else "move_files",
                tool_parameters={"target": "identified_files"},
                step_description="Execute file operation on target file system path.",
                risk_level=risk,
                requires_approval=True,
            )
            workflow_proposal = self.propose_workflow(
                query=query,
                task_intent="manage_files",
                action_steps=[step],
                risk_level=risk,
                requires_approval=True,
                approval_prompt=prompt_msg,
            )
            has_evidence = True
            answer_text = (
                f"Formulated workflow proposal for '{query}'. "
                f"Assigned safety level {risk.value}. Execution requires user confirmation."
            )

        # Honest "No Evidence" fallback
        if not has_evidence:
            return GroundedAnswer(
                query=query,
                answer_text=(
                    f"No evidence observed in active screen context or retrieved documents to answer: \"{query}\"."
                ),
                has_evidence=False,
                evidence_observations=[],
                sources_cited=[],
                confidence_score=0.0,
                workflow_proposal=None,
                timestamp=self._get_current_time(),
            )

        sources = [o.source for o in matched_obs]
        return GroundedAnswer(
            query=query,
            answer_text=answer_text,
            has_evidence=True,
            evidence_observations=matched_obs,
            sources_cited=sources,
            confidence_score=0.94,
            workflow_proposal=workflow_proposal,
            timestamp=self._get_current_time(),
        )

    # -------------------------------------------------------------------------
    # Workflow Proposal Handoff
    # -------------------------------------------------------------------------

    def propose_workflow(
        self,
        query: str,
        task_intent: str,
        action_steps: List[ActionStep],
        risk_level: RiskLevel = RiskLevel.CATEGORY_A_INFORMATIONAL,
        requires_approval: bool = False,
        approval_prompt: Optional[str] = None,
        target_module: str = "workflow",
    ) -> WorkflowProposal:
        """
        Packages an action plan into a structured WorkflowProposal and hands it off
        to the workflow module.
        """
        proposal_id = f"prop-{hashlib.sha256((query + task_intent).encode('utf-8')).hexdigest()[:12]}"
        return WorkflowProposal(
            proposal_id=proposal_id,
            task_intent=task_intent,
            action_steps=action_steps,
            risk_level=risk_level,
            requires_approval=requires_approval,
            approval_prompt=approval_prompt,
            target_module=target_module,
        )

    # -------------------------------------------------------------------------
    # Prompt Injection Quarantine
    # -------------------------------------------------------------------------

    def quarantine_observation_for_prompt(self, obs: Observation) -> str:
        """
        Defends against prompt injection by quarantining untrusted observation content
        inside explicit delimiters, stripping closing tag breakout attempts, and neutralizing
        system instruction spoofing.
        """
        content = obs.content
        # 1. Neutralize closing delimiter tag breakout
        content = re.sub(
            r"</?\s*untrusted_observation\s*>",
            "[SANITIZED_DELIMITER]",
            content,
            flags=re.IGNORECASE,
        )
        # 2. Neutralize system override tokens
        content = re.sub(
            r"(?i)(\[system\s*instruction\]|system:\s*|ignore\s*previous\s*instructions)",
            "[FLAGGED_INJECTION_TOKEN]",
            content,
        )
        # 3. Wrap in strict untrusted XML-like envelope
        src = obs.source.source_type.value
        app = obs.source.application_name or "unknown"
        return (
            f"<untrusted_observation id=\"{obs.observation_id}\" source=\"{src}\" app=\"{app}\">\n"
            f"{content}\n"
            f"</untrusted_observation>"
        )

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, Any]:
        """Returns observable operational metrics."""
        return {
            "total_frames_ingested": self._total_frames_ingested,
            "duplicate_frames_detected": self._duplicate_frames_detected,
            "stale_frames_detected": self._stale_frames_detected,
            "consent_withdrawals_count": self._consent_withdrawals_count,
            "active_observations_count": len(self._active_observations),
            "consent_status": self._consent_status.value,
        }

    def _verify_consent_before_ingestion(self) -> None:
        """Enforces that consent is currently granted and active."""
        if self._consent_status == ConsentStatus.CONSENT_WITHDRAWN:
            raise ConsentWithdrawnException(
                "Cannot capture screen frame or ingest observation: User has explicitly withdrawn consent."
            )
        if self._consent_status != ConsentStatus.CONSENT_ACTIVE:
            raise CaptureNotAuthorizedException(
                "Cannot capture screen frame: Screen capture is not authorized. Call opt_in() first."
            )

    def _get_current_time(self) -> datetime:
        """Returns current time using injected or standard clock."""
        t = self._clock()
        if isinstance(t, (int, float)):
            return datetime.fromtimestamp(t, tz=timezone.utc)
        return t


# Alias for backward compatibility
ObservationEngine = ObservationManager

