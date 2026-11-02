"""
Unit tests for Bounded Context Builder with Recency and Relevance Selection,
Token-Budget Approximation, and Stale Filtering.
Compatible with pytest and standard standalone runners.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    import pytest
except ImportError:
    class _PytestCompat:
        class raises:
            def __init__(self, expected_exc):
                self.expected_exc = expected_exc
                self.value = None
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    raise AssertionError(f"Expected exception {self.expected_exc.__name__} not raised.")
                if not issubclass(exc_type, self.expected_exc):
                    return False
                self.value = exc_val
                return True
        @staticmethod
        def fixture(fn):
            return fn
    pytest = _PytestCompat()

from app.schemas.common import ContextType, SourceType
from app.schemas.context import ContextItem, ScreenContext, SourceReference
from app.context.builder import (
    BoundedContextBuilder,
    BoundedContextConfig,
    BoundedContextResult,
    ContextScorerConfig,
    StaleFilterConfig,
    TokenEstimator,
)


def create_sample_item(
    item_id: str,
    context_type: ContextType,
    title: str,
    content: str,
    relevance_score: float = 1.0,
    age_seconds: float = 0.0,
    base_time: Optional[datetime] = None,
    source: Optional[SourceReference] = None,
) -> ContextItem:
    """Helper creating a test ContextItem with specific age."""
    now = base_time or datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    ts = now - timedelta(seconds=age_seconds)
    return ContextItem(
        item_id=item_id,
        context_type=context_type,
        title=title,
        content=content,
        relevance_score=relevance_score,
        timestamp=ts,
        source=source,
    )


# =========================================================================
# Token Estimator Tests
# =========================================================================

def test_token_estimator_text_and_code():
    """Verify deterministic token estimation across prose and code."""
    prose = "This is a clean English documentation sentence explaining context selection."
    prose_tokens = TokenEstimator.estimate_text(prose)
    assert prose_tokens > 0
    assert 10 <= prose_tokens <= 25

    code = "def calculate_average(items):\n    return sum(items) / len(items)"
    code_tokens = TokenEstimator.estimate_text(code)
    assert code_tokens > 0
    assert 12 <= code_tokens <= 30

    assert TokenEstimator.estimate_text("") == 0
    assert TokenEstimator.estimate_text(None) == 0


def test_token_estimator_context_item():
    """Verify token estimation populates item.token_count field."""
    item = create_sample_item("ctx-tok-1", ContextType.CODE_SNIPPET, "Code snippet", "print('hello world')")
    assert item.token_count is None

    tokens = TokenEstimator.estimate_item(item)
    assert tokens > 0
    assert item.token_count == tokens


# =========================================================================
# Stale Filtering Tests
# =========================================================================

def test_stale_filter_expiration_default_ttl():
    """Verify items exceeding TTL are pruned from the context pool."""
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    config = BoundedContextConfig(stale_config=StaleFilterConfig(default_ttl_seconds=300.0, type_specific_ttl={}))
    builder = BoundedContextBuilder(config=config)

    # Item 1: 60 seconds old (Fresh)
    fresh_item = create_sample_item("fresh-01", ContextType.CODE_SNIPPET, "Recent edit", "x = 10", age_seconds=60, base_time=now)
    # Item 2: 400 seconds old (> 300s TTL -> Stale)
    stale_item = create_sample_item("stale-01", ContextType.CODE_SNIPPET, "Old edit", "x = 5", age_seconds=400, base_time=now)

    builder.add_item(fresh_item).add_item(stale_item)
    result = builder.build(now=now)

    selected_ids = [it.item_id for it in result.selected_items]
    stale_ids = [it.item_id for it in result.discarded_stale_items]

    assert "fresh-01" in selected_ids
    assert "stale-01" in stale_ids
    assert "stale-01" not in selected_ids


def test_stale_filter_type_specific_ttl():
    """Verify terminal outputs expire faster than documents."""
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    builder = BoundedContextBuilder()

    # Terminal output 150 seconds old (type TTL is 120s -> Stale)
    term_item = create_sample_item("term-01", ContextType.TERMINAL_OUTPUT, "Log output", "Build failed", age_seconds=150, base_time=now)
    # Document excerpt 150 seconds old (type TTL is 1800s -> Fresh)
    doc_item = create_sample_item("doc-01", ContextType.DOCUMENT_EXCERPT, "Architecture PDF", "Section 4.1", age_seconds=150, base_time=now)

    builder.add_items([term_item, doc_item])
    result = builder.build(now=now)

    selected_ids = [it.item_id for it in result.selected_items]
    stale_ids = [it.item_id for it in result.discarded_stale_items]

    assert "doc-01" in selected_ids
    assert "term-01" in stale_ids


def test_stale_filter_superseded_items():
    """Verify newer items from the exact same document/window supersede older ones."""
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    builder = BoundedContextBuilder()

    src = SourceReference(
        source_id="src-file-1",
        source_type=SourceType.DOCUMENT,
        document_uri="/workspace/main.py",
        timestamp=now,
    )

    # Older version (age 100s)
    v1 = create_sample_item("code-v1", ContextType.CODE_SNIPPET, "main.py v1", "def foo(): pass", age_seconds=100, base_time=now, source=src)
    # Newer version (age 10s)
    v2 = create_sample_item("code-v2", ContextType.CODE_SNIPPET, "main.py v2", "def foo(): return 42", age_seconds=10, base_time=now, source=src)

    builder.add_items([v1, v2])
    result = builder.build(now=now)

    selected_ids = [it.item_id for it in result.selected_items]
    stale_ids = [it.item_id for it in result.discarded_stale_items]

    assert "code-v2" in selected_ids
    assert "code-v1" in stale_ids  # Superseded


# =========================================================================
# Recency & Relevance Selection Tests
# =========================================================================

def test_recency_scoring_time_decay():
    """Verify recent items receive strictly higher recency scores."""
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    builder = BoundedContextBuilder()

    new_item = create_sample_item("new-1", ContextType.CODE_SNIPPET, "Title", "content", age_seconds=10, base_time=now)
    mid_item = create_sample_item("mid-1", ContextType.CODE_SNIPPET, "Title", "content", age_seconds=120, base_time=now)
    old_item = create_sample_item("old-1", ContextType.CODE_SNIPPET, "Title", "content", age_seconds=240, base_time=now)

    score_new = builder.compute_recency_score(new_item, now)
    score_mid = builder.compute_recency_score(mid_item, now)
    score_old = builder.compute_recency_score(old_item, now)

    assert score_new > score_mid > score_old
    assert 0.0 <= score_old <= 1.0


def test_relevance_selection_keyword_overlap():
    """Verify items matching user query terms score higher relevance and rank first."""
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    builder = BoundedContextBuilder()

    # Item matching query words
    matching_item = create_sample_item(
        "match-01", ContextType.CODE_SNIPPET, "ZeroDivisionError traceback",
        "Division by zero occurring in calculate_average", relevance_score=0.9, base_time=now,
    )
    # Item unrelated to query
    unrelated_item = create_sample_item(
        "unrelated-01", ContextType.CODE_SNIPPET, "HTML colors",
        "Background color is #07090e", relevance_score=0.9, base_time=now,
    )

    builder.add_items([unrelated_item, matching_item])
    result = builder.build(query="Why does ZeroDivisionError occur?", now=now)

    assert len(result.selected_items) == 2
    # Matching item should rank at index 0
    assert result.selected_items[0].item_id == "match-01"
    assert result.item_scores["match-01"] > result.item_scores["unrelated-01"]


def test_priority_weighting():
    """Verify active error traces and screen OCR outrank generic dialogue history."""
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    builder = BoundedContextBuilder()

    term_error = create_sample_item(
        "term-err", ContextType.TERMINAL_OUTPUT, "Crash stack", "Exception in thread", age_seconds=30, base_time=now,
    )
    dialogue = create_sample_item(
        "diag-hist", ContextType.DIALOGUE_HISTORY, "Past chat", "User asked about weather", age_seconds=30, base_time=now,
    )

    builder.add_items([dialogue, term_error])
    result = builder.build(now=now)

    assert result.selected_items[0].item_id == "term-err"


# =========================================================================
# Token Budget Fitting Tests
# =========================================================================

def test_token_budget_packing_strict_ceiling():
    """Verify context builder fits items up to token budget and discards overflow."""
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    # Configure tiny budget of 20 tokens
    config = BoundedContextConfig(token_budget=20)
    builder = BoundedContextBuilder(config=config)

    # Item 1: ~15 tokens
    item1 = create_sample_item("item-1", ContextType.CODE_SNIPPET, "Snippet 1", "x = [1, 2, 3]", relevance_score=0.95, base_time=now)
    # Item 2: ~15 tokens
    item2 = create_sample_item("item-2", ContextType.CODE_SNIPPET, "Snippet 2", "y = sum(x) * 2", relevance_score=0.85, base_time=now)
    # Item 3: ~40 tokens (Cannot fit in remaining ~20 tokens)
    item3 = create_sample_item(
        "item-3", ContextType.DOCUMENT_EXCERPT, "Large paragraph",
        "This long document excerpt contains substantial technical documentation that exceeds the tiny budget ceiling.",
        relevance_score=0.75, base_time=now,
    )

    builder.add_items([item1, item2, item3])
    result = builder.build(now=now)

    assert result.total_tokens <= 20
    selected_ids = [it.item_id for it in result.selected_items]
    discarded_ids = [it.item_id for it in result.discarded_budget_items]

    assert "item-1" in selected_ids
    assert "item-2" in selected_ids
    assert "item-3" in discarded_ids
    assert result.remaining_budget >= 0


def test_screen_context_dynamic_ingestion():
    """Verify active ScreenContext OCR is seamlessly ingested and curated."""
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    builder = BoundedContextBuilder()

    screen = ScreenContext(
        capture_id="cap-screen-test",
        width=1920,
        height=1080,
        application_name="VS Code",
        window_title="main.py",
        ocr_text="ZeroDivisionError: division by zero on line 2",
        timestamp=now,
    )

    result = builder.build(query="fix error", screen_context=screen, now=now)
    assert len(result.selected_items) == 1
    assert "ZeroDivisionError" in result.selected_items[0].content
    assert result.selected_items[0].context_type == ContextType.SCREEN_OCR


def test_deterministic_reproducibility():
    """Verify identical inputs and fixed timestamp produce 100% deterministic results."""
    now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
    builder = BoundedContextBuilder()

    items = [
        create_sample_item(f"item-{i}", ContextType.CODE_SNIPPET, f"Title {i}", f"code payload {i}", age_seconds=i * 20, base_time=now)
        for i in range(10)
    ]
    builder.add_items(items)

    res1 = builder.build(query="code payload", now=now)
    res2 = builder.build(query="code payload", now=now)

    assert [it.item_id for it in res1.selected_items] == [it.item_id for it in res2.selected_items]
    assert res1.total_tokens == res2.total_tokens
    assert res1.item_scores == res2.item_scores
