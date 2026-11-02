"""
Bounded Context Builder with Recency and Relevance Selection,
Token-Budget Approximation, and Stale Filtering.

Complies with:
- SDD Section 4.4 & Tech Arch Section 5: Context Engine Curation.
- PRD Section 16 & Section 19: Multimodal Context Boundaries and Privacy Minimization.
"""

from collections import OrderedDict
from datetime import datetime, timezone
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from app.schemas.common import ContextType
from app.schemas.context import ContextItem, ScreenContext


class TokenEstimator:
    """
    Fast, deterministic token estimator approximating BPE/SentencePiece tokenizers
    for modern LLMs (Gemini, Claude, GPT) without external binary dependencies.
    """

    # Typical character-to-token ratios for multimodal code & language models
    CHARS_PER_TOKEN_PROSE: float = 3.8
    CHARS_PER_TOKEN_CODE: float = 3.2

    @classmethod
    def estimate_text(cls, text: Optional[str]) -> int:
        """
        Estimates the token count for a text string.
        Takes into account code blocks, indentation, punctuation, and word splits.
        """
        if not text:
            return 0

        stripped = text.strip()
        if not stripped:
            return 0

        # Heuristic detection for code or structured data (newlines, braces, colons, defs)
        is_code = bool(re.search(r"[{};()=\[\]]|^\s{2,}|(?:def|class|function|import|SELECT)\b", stripped, re.MULTILINE))
        ratio = cls.CHARS_PER_TOKEN_CODE if is_code else cls.CHARS_PER_TOKEN_PROSE

        char_estimate = len(stripped) / ratio
        # Word split approximation (average 1.25 tokens per word)
        word_count = len(stripped.split())
        word_estimate = word_count * 1.25

        # Blended estimate
        blended = (char_estimate * 0.7) + (word_estimate * 0.3)
        return max(1, math.ceil(blended))

    @classmethod
    def estimate_item(cls, item: ContextItem) -> int:
        """
        Estimates total token budget consumed by a ContextItem including its title and payload.
        Caches the estimated value in item.token_count if not already set.
        """
        if item.token_count is not None and item.token_count > 0:
            return item.token_count

        title_tokens = cls.estimate_text(item.title)
        content_tokens = cls.estimate_text(item.content)
        total = title_tokens + content_tokens

        # Populate schema field
        item.token_count = total
        return total


class StaleFilterConfig(BaseModel):
    """
    Configuration for detecting and dropping expired or superseded context items.
    """
    default_ttl_seconds: float = Field(
        default=300.0,
        ge=1.0,
        description="Default expiration threshold for context items in seconds (default 5 minutes)."
    )
    type_specific_ttl: Dict[ContextType, float] = Field(
        default_factory=lambda: {
            ContextType.TERMINAL_OUTPUT: 120.0,    # Terminal changes rapidly (2 minutes)
            ContextType.SCREEN_OCR: 180.0,         # Screen context active window (3 minutes)
            ContextType.VISUAL_SUMMARY: 180.0,     # Visual summary freshness (3 minutes)
            ContextType.CODE_SNIPPET: 600.0,       # Active code file snippet (10 minutes)
            ContextType.DOCUMENT_EXCERPT: 1800.0,  # PDF/paper reference excerpt (30 minutes)
            ContextType.USER_QUERY: 3600.0,        # Prior session user queries (60 minutes)
            ContextType.DIALOGUE_HISTORY: 3600.0,  # Multi-turn history (60 minutes)
        },
        description="Type-specific TTL overrides."
    )
    deduplicate_by_source: bool = Field(
        default=True,
        description="If True, older items sharing the exact same source document/window are superseded."
    )


class ContextScorerConfig(BaseModel):
    """
    Weighting configuration for composite recency, relevance, and priority ranking.
    """
    weight_relevance: float = Field(default=0.50, ge=0.0, le=1.0, description="Weight for semantic/keyword relevance.")
    weight_recency: float = Field(default=0.35, ge=0.0, le=1.0, description="Weight for time-decay recency.")
    weight_priority: float = Field(default=0.15, ge=0.0, le=1.0, description="Weight for type/source priority.")
    recency_half_life_seconds: float = Field(
        default=180.0,
        ge=10.0,
        description="Exponential decay half-life in seconds (reaches 0.5 score after half-life)."
    )


class BoundedContextConfig(BaseModel):
    """
    Master configuration for the Bounded Context Builder.
    """
    token_budget: int = Field(
        default=2048,
        ge=16,
        le=32768,
        description="Maximum token ceiling allocated for curated context items."
    )
    max_items: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Maximum count of items allowed in context (matches ReasoningRequest constraint)."
    )
    stale_config: StaleFilterConfig = Field(default_factory=StaleFilterConfig)
    scorer_config: ContextScorerConfig = Field(default_factory=ContextScorerConfig)


class BoundedContextResult(BaseModel):
    """
    Outcome of bounded context curation.
    """
    selected_items: List[ContextItem] = Field(default_factory=list, description="Items chosen within token budget.")
    discarded_stale_items: List[ContextItem] = Field(default_factory=list, description="Items pruned due to expiration.")
    discarded_budget_items: List[ContextItem] = Field(default_factory=list, description="Items dropped due to token budget.")
    total_tokens: int = Field(default=0, ge=0, description="Total estimated tokens of chosen items.")
    token_budget: int = Field(default=2048, ge=0, description="Allocated token budget ceiling.")
    remaining_budget: int = Field(default=0, ge=0, description="Unused token capacity.")
    item_scores: Dict[str, float] = Field(default_factory=dict, description="Final composite scores by item_id.")


class BoundedContextBuilder:
    """
    Curates a prioritized, size-bounded set of context items from raw event streams.
    
    Guarantees:
    1. Stale Filtering: Drops expired and superseded items according to configured TTLs.
    2. Recency & Relevance Selection: Combines semantic relevance, exponential time-decay recency,
       and source priority into a unified composite ranking score.
    3. Token-Budget Approximation: Enforces a strict token budget ceiling, packing the highest-ranked
       items and discarding lower-ranked overflow items.
    """

    def __init__(self, config: Optional[BoundedContextConfig] = None):
        self._config = config or BoundedContextConfig()
        self._pool: OrderedDict[str, ContextItem] = OrderedDict()

    @property
    def config(self) -> BoundedContextConfig:
        return self._config

    def add_item(self, item: ContextItem) -> "BoundedContextBuilder":
        """Adds an item into the builder's pool."""
        self._pool[item.item_id] = item
        return self

    def add_items(self, items: Iterable[ContextItem]) -> "BoundedContextBuilder":
        """Adds multiple items into the builder's pool."""
        for item in items:
            self.add_item(item)
        return self

    def clear(self) -> None:
        """Empties the candidate item pool."""
        self._pool.clear()

    def is_stale(self, item: ContextItem, now: datetime) -> bool:
        """
        Checks if an item exceeds its expiration TTL threshold relative to current time.
        """
        ttl = self._config.stale_config.type_specific_ttl.get(
            item.context_type,
            self._config.stale_config.default_ttl_seconds,
        )
        # Ensure timezone compatibility
        item_ts = item.timestamp
        if item_ts.tzinfo is None:
            item_ts = item_ts.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        age_seconds = (now - item_ts).total_seconds()
        return age_seconds > ttl

    def compute_recency_score(self, item: ContextItem, now: datetime) -> float:
        """
        Computes normalized exponential decay recency score in [0.0, 1.0].
        Score = exp(-ln(2) * age / half_life)
        """
        item_ts = item.timestamp
        if item_ts.tzinfo is None:
            item_ts = item_ts.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        age = max(0.0, (now - item_ts).total_seconds())
        half_life = self._config.scorer_config.recency_half_life_seconds
        decay_constant = math.log(2.0) / half_life
        score = math.exp(-decay_constant * age)
        return max(0.0, min(1.0, score))

    def compute_relevance_score(self, item: ContextItem, query: Optional[str]) -> float:
        """
        Computes relevance score using base item relevance and query keyword overlap.
        """
        base_rel = max(0.0, min(1.0, item.relevance_score))
        if not query or not query.strip():
            return base_rel

        query_terms = set(re.findall(r"\w+", query.lower()))
        if not query_terms:
            return base_rel

        # Match query terms against title and content
        target_text = f"{item.title} {item.content[:1000]}".lower()
        matched_terms = sum(1 for term in query_terms if term in target_text)
        overlap_score = matched_terms / len(query_terms)

        # 60% base relevance weight, 40% lexical query overlap
        blended = (base_rel * 0.6) + (overlap_score * 0.4)
        return max(0.0, min(1.0, blended))

    def compute_priority_weight(self, item: ContextItem) -> float:
        """
        Calculates normalized source priority weight based on context modality.
        Active error traces and screen OCR get highest priority.
        """
        type_weights = {
            ContextType.TERMINAL_OUTPUT: 1.0,
            ContextType.CODE_SNIPPET: 0.95,
            ContextType.SCREEN_OCR: 0.90,
            ContextType.VISUAL_SUMMARY: 0.85,
            ContextType.DOCUMENT_EXCERPT: 0.80,
            ContextType.USER_QUERY: 0.70,
            ContextType.APPLICATION_METADATA: 0.65,
            ContextType.DIALOGUE_HISTORY: 0.60,
            ContextType.RETRIEVED_DOC: 0.75,
        }
        return type_weights.get(item.context_type, 0.5)

    def compute_composite_score(self, item: ContextItem, query: Optional[str], now: datetime) -> float:
        """
        Calculates unified composite score combining relevance, recency, and priority.
        """
        cfg = self._config.scorer_config
        rel_score = self.compute_relevance_score(item, query)
        rec_score = self.compute_recency_score(item, now)
        prio_score = self.compute_priority_weight(item)

        composite = (
            (cfg.weight_relevance * rel_score)
            + (cfg.weight_recency * rec_score)
            + (cfg.weight_priority * prio_score)
        )
        return round(max(0.0, min(1.0, composite)), 4)

    def filter_stale_and_superseded(
        self,
        items: List[ContextItem],
        now: datetime,
    ) -> Tuple[List[ContextItem], List[ContextItem]]:
        """
        Filters out items that have exceeded TTL or are superseded by newer items from same source.
        
        Returns:
            Tuple of (fresh_items, stale_items)
        """
        fresh: List[ContextItem] = []
        stale: List[ContextItem] = []
        seen_source_keys: Set[str] = set()

        # Sort items newest first for deduplication check
        sorted_by_recency = sorted(items, key=lambda x: x.timestamp, reverse=True)

        for item in sorted_by_recency:
            # 1. TTL Check
            if self.is_stale(item, now):
                stale.append(item)
                continue

            # 2. Source Deduplication
            if self._config.stale_config.deduplicate_by_source and item.source:
                src_key = f"{item.context_type.value}:{item.source.document_uri or item.source.window_title}"
                if src_key in seen_source_keys:
                    # Superseded by newer item from same document/window
                    stale.append(item)
                    continue
                seen_source_keys.add(src_key)

            fresh.append(item)

        return fresh, stale

    def build(
        self,
        query: Optional[str] = None,
        screen_context: Optional[ScreenContext] = None,
        token_budget: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> BoundedContextResult:
        """
        Constructs the bounded context payload:
        1. Stale Filtering: Discards expired and superseded items.
        2. Recency & Relevance Ranking: Computes composite scores and sorts candidates.
        3. Token-Budget Packing: Selects highest-value items conforming to token budget ceiling.
        """
        evaluation_time = now or datetime.now(timezone.utc)
        budget = token_budget if token_budget is not None else self._config.token_budget

        candidate_items = list(self._pool.values())

        # If ScreenContext has OCR text, create candidate ContextItem if not present
        if screen_context and screen_context.ocr_text:
            sc_item_id = f"ctx-screen-{screen_context.capture_id[:16]}"
            if sc_item_id not in self._pool:
                sc_item = ContextItem(
                    item_id=sc_item_id,
                    context_type=ContextType.SCREEN_OCR,
                    title=f"Screen OCR ({screen_context.application_name or 'Active Window'})",
                    content=screen_context.ocr_text,
                    relevance_score=0.95,
                    timestamp=screen_context.timestamp,
                )
                candidate_items.append(sc_item)

        # Step 1: Stale Filtering
        fresh_items, stale_items = self.filter_stale_and_superseded(candidate_items, evaluation_time)

        # Step 2: Scoring and Ranking
        scores: Dict[str, float] = {}
        for item in fresh_items:
            scores[item.item_id] = self.compute_composite_score(item, query, evaluation_time)

        # Rank items descending by composite score (highest first)
        ranked_items = sorted(fresh_items, key=lambda it: scores[it.item_id], reverse=True)

        # Step 3: Token Budget Fitting
        selected: List[ContextItem] = []
        discarded_budget: List[ContextItem] = []
        accumulated_tokens = 0

        for item in ranked_items:
            if len(selected) >= self._config.max_items:
                discarded_budget.append(item)
                continue

            item_tokens = TokenEstimator.estimate_item(item)
            if accumulated_tokens + item_tokens <= budget:
                selected.append(item)
                accumulated_tokens += item_tokens
            else:
                discarded_budget.append(item)

        remaining = max(0, budget - accumulated_tokens)

        return BoundedContextResult(
            selected_items=selected,
            discarded_stale_items=stale_items,
            discarded_budget_items=discarded_budget,
            total_tokens=accumulated_tokens,
            token_budget=budget,
            remaining_budget=remaining,
            item_scores=scores,
        )
