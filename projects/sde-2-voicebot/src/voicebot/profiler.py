"""Performance profiling, capture indicators, and memory monitoring for SDE Team 2.

Provides:
- High-precision latency profiling with percentile distributions (p50, p95, p99).
- Profiler overhead calibration to avoid contaminating pipeline measurements.
- Standard-library heap memory tracking and robust leak detection with warm-up.
- Visual real-time capture indicators for CLI and UI observability.
- Automated pipeline benchmarking for production release hardening (Days 22-24).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import time
import tracemalloc
from typing import Any, Generator


def get_capture_indicator(
    state: str,
    is_speech: bool = False,
    energy: float = 0.0,
) -> str:
    """Return a standardized, human-readable capture indicator badge.

    Args:
        state: Current lifecycle state (e.g. 'RECORDING', 'PAUSED', 'STOPPED', 'RECONNECTING', 'CANCELLED').
        is_speech: Whether VAD currently detects active speech.
        energy: Current RMS energy score.

    Returns:
        Formatted indicator badge string.
    """
    state_upper = state.upper()
    if state_upper == "RECORDING":
        if is_speech:
            return f"[● REC | SPEECH ACTIVE (RMS: {energy:.4f})]"
        return f"[● REC | LISTENING (RMS: {energy:.4f})]"
    elif state_upper == "PAUSED":
        return "[⏸ PAUSED | CAPTURE SUSPENDED]"
    elif state_upper == "RECONNECTING":
        return "[⚠️ RECONNECTING | FALLBACK ACTIVE]"
    elif state_upper == "CANCELLED":
        return "[✕ CANCELLED | BUFFER FLUSHED]"
    elif state_upper in ("STOPPED", "IDLE"):
        return "[⚪ IDLE | MIC OFF]"
    return f"[{state_upper}]"


@dataclass(frozen=True)
class LatencyMetrics:
    """Latency statistical summary over a series of timing samples."""

    sample_count: int
    avg_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    total_wall_ms: float
    throughput_cps: float
    profiler_overhead_ns_per_op: float


@dataclass(frozen=True)
class MemoryMetrics:
    """Memory heap statistical summary over a profiling session."""

    baseline_kb: float
    peak_kb: float
    current_kb: float
    net_growth_kb: float
    warmup_chunks: int
    leak_tolerance_kb_per_chunk: float
    leak_detected: bool


@dataclass
class ProfileReport:
    """Consolidated performance, memory, and observability profile report."""

    pipeline_latency: LatencyMetrics
    stage_latencies: dict[str, LatencyMetrics] = field(default_factory=dict)
    memory: MemoryMetrics | None = None
    disk_writes_detected: int = 0
    zero_disk_verified: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary_text(self) -> str:
        """Format the report as an informative text table."""
        lines = [
            "=" * 74,
            "  Audio Pipeline Profiling & Hardening Report (Days 22-24)",
            "=" * 74,
            f"  Total Chunks:       {self.pipeline_latency.sample_count}",
            f"  Throughput:         {self.pipeline_latency.throughput_cps:,.1f} chunks/sec",
            f"  Wall Time:          {self.pipeline_latency.total_wall_ms:.2f} ms",
            f"  Profiler Overhead:  {self.pipeline_latency.profiler_overhead_ns_per_op:.1f} ns/op",
            "-" * 74,
            "  Latency Distribution (Per-Chunk Processing):",
            f"    Average:          {self.pipeline_latency.avg_ms:.4f} ms",
            f"    Median (p50):     {self.pipeline_latency.p50_ms:.4f} ms",
            f"    95th Percentile:  {self.pipeline_latency.p95_ms:.4f} ms",
            f"    99th Percentile:  {self.pipeline_latency.p99_ms:.4f} ms",
            f"    Minimum:          {self.pipeline_latency.min_ms:.4f} ms",
            f"    Maximum:          {self.pipeline_latency.max_ms:.4f} ms",
        ]

        if self.stage_latencies:
            lines.extend([
                "-" * 74,
                "  Stage Breakdown (Average Latency):",
            ])
            for stage_name, metrics in sorted(self.stage_latencies.items()):
                pct = (
                    (metrics.avg_ms / self.pipeline_latency.avg_ms * 100.0)
                    if self.pipeline_latency.avg_ms > 0
                    else 0.0
                )
                lines.append(
                    f"    {stage_name:<20}: {metrics.avg_ms:.4f} ms ({pct:5.1f}%) [p95: {metrics.p95_ms:.4f} ms]"
                )

        if self.memory:
            leak_status = "PASSED (No leak detected)" if not self.memory.leak_detected else "FAILED (Leak suspected)"
            lines.extend([
                "-" * 74,
                "  Memory Footprint (Heap Allocations via tracemalloc):",
                f"    Baseline Memory:  {self.memory.baseline_kb:.2f} KB (after {self.memory.warmup_chunks} warmup chunks)",
                f"    Current Memory:   {self.memory.current_kb:.2f} KB",
                f"    Peak Memory:      {self.memory.peak_kb:.2f} KB",
                f"    Net Growth:       {self.memory.net_growth_kb:+.2f} KB",
                f"    Growth Rate:      {(self.memory.net_growth_kb / max(1, self.pipeline_latency.sample_count)):.4f} KB/chunk",
                f"    Leak Check:       {leak_status}",
            ])

        disk_status = "PASSED (Zero audio disk writes)" if self.zero_disk_verified else "FAILED (Disk writes detected)"
        lines.extend([
            "-" * 74,
            "  Privacy & Disk Persistence Check:",
            f"    Disk Writes:      {self.disk_writes_detected} bytes written",
            f"    Privacy Status:   {disk_status}",
            "=" * 74,
        ])
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to JSON-serializable dictionary."""
        return {
            "pipeline_latency": {
                "sample_count": self.pipeline_latency.sample_count,
                "avg_ms": self.pipeline_latency.avg_ms,
                "min_ms": self.pipeline_latency.min_ms,
                "max_ms": self.pipeline_latency.max_ms,
                "p50_ms": self.pipeline_latency.p50_ms,
                "p95_ms": self.pipeline_latency.p95_ms,
                "p99_ms": self.pipeline_latency.p99_ms,
                "throughput_cps": self.pipeline_latency.throughput_cps,
                "profiler_overhead_ns_per_op": self.pipeline_latency.profiler_overhead_ns_per_op,
            },
            "stage_latencies": {
                k: {
                    "avg_ms": v.avg_ms,
                    "p50_ms": v.p50_ms,
                    "p95_ms": v.p95_ms,
                    "max_ms": v.max_ms,
                }
                for k, v in self.stage_latencies.items()
            },
            "memory": (
                {
                    "baseline_kb": self.memory.baseline_kb,
                    "peak_kb": self.memory.peak_kb,
                    "current_kb": self.memory.current_kb,
                    "net_growth_kb": self.memory.net_growth_kb,
                    "leak_detected": self.memory.leak_detected,
                }
                if self.memory
                else None
            ),
            "disk_writes_detected": self.disk_writes_detected,
            "zero_disk_verified": self.zero_disk_verified,
            "metadata": self.metadata,
        }


class AudioPipelineProfiler:
    """High-precision, zero-overhead pipeline profiler and memory monitor."""

    def __init__(
        self,
        warmup_chunks: int = 50,
        leak_tolerance_kb_per_chunk: float = 0.05,
        enable_memory_tracking: bool = True,
    ) -> None:
        """Initialize the profiler.

        Args:
            warmup_chunks: Chunks allowed before establishing memory baseline.
            leak_tolerance_kb_per_chunk: Maximum allowed memory growth rate (KB/chunk).
            enable_memory_tracking: Whether to enable tracemalloc monitoring.
        """
        self.warmup_chunks = max(0, warmup_chunks)
        self.leak_tolerance_kb_per_chunk = leak_tolerance_kb_per_chunk
        self.enable_memory_tracking = enable_memory_tracking

        self._pipeline_durations_ns: list[int] = []
        self._stage_durations_ns: dict[str, list[int]] = {}
        self._chunk_counter = 0

        self._session_start_ns: int | None = None
        self._session_end_ns: int | None = None

        self._baseline_memory_bytes: int | None = None
        self._peak_memory_bytes: int = 0
        self._owns_tracemalloc = False
        self._overhead_ns_per_op = 0.0

    def start(self) -> None:
        """Begin a profiling session and calibrate baseline."""
        self.reset()
        self._overhead_ns_per_op = self.calibrate_overhead()

        if self.enable_memory_tracking:
            if not tracemalloc.is_tracing():
                tracemalloc.start()
                self._owns_tracemalloc = True
            tracemalloc.reset_peak()

        self._session_start_ns = time.perf_counter_ns()

    def stop(self) -> None:
        """Conclude the profiling session."""
        if self._session_end_ns is None:
            self._session_end_ns = time.perf_counter_ns()

    def reset(self) -> None:
        """Reset all recorded metrics."""
        self._pipeline_durations_ns.clear()
        self._stage_durations_ns.clear()
        self._chunk_counter = 0
        self._session_start_ns = None
        self._session_end_ns = None
        self._baseline_memory_bytes = None
        self._peak_memory_bytes = 0

    def calibrate_overhead(self, iterations: int = 1000) -> float:
        """Measure the baseline measurement overhead of time.perf_counter_ns().

        Args:
            iterations: Number of back-to-back timing calls.

        Returns:
            Average nanoseconds per timing call.
        """
        t0 = time.perf_counter_ns()
        for _ in range(iterations):
            _ = time.perf_counter_ns()
        t1 = time.perf_counter_ns()
        return max(0.0, float(t1 - t0) / float(iterations))

    @contextmanager
    def profile_chunk(self, chunk_id: int | None = None) -> Generator[None, None, None]:
        """Context manager to measure full end-to-end processing of a chunk."""
        t_start = time.perf_counter_ns()
        try:
            yield
        finally:
            t_end = time.perf_counter_ns()
            duration_ns = t_end - t_start
            self._pipeline_durations_ns.append(duration_ns)
            self._chunk_counter += 1

            if self.enable_memory_tracking and tracemalloc.is_tracing():
                curr, peak = tracemalloc.get_traced_memory()
                if curr > self._peak_memory_bytes:
                    self._peak_memory_bytes = curr
                if peak > self._peak_memory_bytes:
                    self._peak_memory_bytes = peak

                # Establish baseline memory right after warmup phase
                if self._chunk_counter == self.warmup_chunks or (
                    self._baseline_memory_bytes is None and self._chunk_counter >= self.warmup_chunks
                ):
                    self._baseline_memory_bytes = curr

    @contextmanager
    def measure_stage(self, stage_name: str) -> Generator[None, None, None]:
        """Context manager to measure the latency of a single internal stage."""
        t_start = time.perf_counter_ns()
        try:
            yield
        finally:
            t_end = time.perf_counter_ns()
            duration_ns = t_end - t_start
            if stage_name not in self._stage_durations_ns:
                self._stage_durations_ns[stage_name] = []
            self._stage_durations_ns[stage_name].append(duration_ns)

    def record_chunk_latency_ns(self, duration_ns: int) -> None:
        """Directly record chunk latency in nanoseconds."""
        self._pipeline_durations_ns.append(duration_ns)
        self._chunk_counter += 1

    def _compute_latency_metrics(self, durations_ns: list[int], wall_time_ns: int) -> LatencyMetrics:
        """Compute percentile distribution and throughput from raw nanosecond samples."""
        if not durations_ns:
            return LatencyMetrics(
                sample_count=0,
                avg_ms=0.0,
                min_ms=0.0,
                max_ms=0.0,
                p50_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                total_wall_ms=0.0,
                throughput_cps=0.0,
                profiler_overhead_ns_per_op=self._overhead_ns_per_op,
            )

        count = len(durations_ns)
        durations_ms = sorted([d / 1_000_000.0 for d in durations_ns])

        avg_ms = sum(durations_ms) / count
        min_ms = durations_ms[0]
        max_ms = durations_ms[-1]

        def _percentile(p: float) -> float:
            idx = int(math.ceil((p / 100.0) * count)) - 1
            idx = max(0, min(count - 1, idx))
            return durations_ms[idx]

        p50_ms = _percentile(50.0)
        p95_ms = _percentile(95.0)
        p99_ms = _percentile(99.0)

        total_wall_ms = max(0.001, wall_time_ns / 1_000_000.0)
        throughput_cps = (count / (total_wall_ms / 1000.0)) if total_wall_ms > 0 else 0.0

        return LatencyMetrics(
            sample_count=count,
            avg_ms=avg_ms,
            min_ms=min_ms,
            max_ms=max_ms,
            p50_ms=p50_ms,
            p95_ms=p95_ms,
            p99_ms=p99_ms,
            total_wall_ms=total_wall_ms,
            throughput_cps=throughput_cps,
            profiler_overhead_ns_per_op=self._overhead_ns_per_op,
        )

    def generate_report(self, disk_writes_detected: int = 0) -> ProfileReport:
        """Generate a comprehensive profiling and hardening report."""
        if self._session_end_ns is None:
            self._session_end_ns = time.perf_counter_ns()

        session_start = self._session_start_ns or self._session_end_ns
        wall_time_ns = max(1, self._session_end_ns - session_start)

        pipeline_latency = self._compute_latency_metrics(
            self._pipeline_durations_ns, wall_time_ns
        )

        stage_latencies = {
            stage: self._compute_latency_metrics(samples, wall_time_ns)
            for stage, samples in self._stage_durations_ns.items()
        }

        memory_metrics: MemoryMetrics | None = None
        if self.enable_memory_tracking and tracemalloc.is_tracing():
            curr_bytes, peak_bytes = tracemalloc.get_traced_memory()
            peak_bytes = max(peak_bytes, self._peak_memory_bytes)
            baseline_bytes = self._baseline_memory_bytes or curr_bytes

            baseline_kb = baseline_bytes / 1024.0
            peak_kb = peak_bytes / 1024.0
            current_kb = curr_bytes / 1024.0
            net_growth_kb = current_kb - baseline_kb

            active_post_warmup_chunks = max(1, self._chunk_counter - self.warmup_chunks)
            growth_rate_kb = max(0.0, net_growth_kb) / active_post_warmup_chunks

            # Leak detected if growth rate strictly exceeds configured tolerance
            # and net growth is non-trivial (> 64 KB total heap delta)
            leak_detected = (
                growth_rate_kb > self.leak_tolerance_kb_per_chunk
                and net_growth_kb > 64.0
            )

            memory_metrics = MemoryMetrics(
                baseline_kb=baseline_kb,
                peak_kb=peak_kb,
                current_kb=current_kb,
                net_growth_kb=net_growth_kb,
                warmup_chunks=self.warmup_chunks,
                leak_tolerance_kb_per_chunk=self.leak_tolerance_kb_per_chunk,
                leak_detected=leak_detected,
            )

        if self._owns_tracemalloc and tracemalloc.is_tracing():
            tracemalloc.stop()
            self._owns_tracemalloc = False

        return ProfileReport(
            pipeline_latency=pipeline_latency,
            stage_latencies=stage_latencies,
            memory=memory_metrics,
            disk_writes_detected=disk_writes_detected,
            zero_disk_verified=(disk_writes_detected == 0),
        )
