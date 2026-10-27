"""
Standalone Test Runner for Day 2 Tasks.
Discovers and executes all test_* functions across:
- test_synthetic_frames
- test_mock_reasoning
- test_versioned_prompts

Zero external test runner dependencies required (works with standard Python or pytest).
"""

import inspect
import os
import sys
import time

# Ensure project paths are on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(current_dir, ".."))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

import test_synthetic_frames
import test_mock_reasoning
import test_versioned_prompts
import test_day2_integration
import test_reasoning_validation


def run_all_tests():
    modules = [
        ("Task 1: Synthetic Frames (Screen Capture Disabled by Default)", test_synthetic_frames),
        ("Task 2: Deterministic Mock Reasoning Engine", test_mock_reasoning),
        ("Task 3: Versioned Prompts with Trusted/Untrusted Separation", test_versioned_prompts),
        ("Task 4: Complete End-to-End Pipeline Integration", test_day2_integration),
        ("Task 5: Reasoning Request & Result Validation Suite", test_reasoning_validation),
    ]

    total_run = 0
    total_passed = 0
    total_failed = 0
    start_time = time.time()

    print("=" * 75)
    print(" SDE-2 VOICEBOT: DAY 2 & DAY 3 AUTOMATED TEST SUITE")
    print("=" * 75)

    for suite_name, module in modules:
        print(f"\n[SUITE] Running: {suite_name}")
        test_funcs = [
            (name, func)
            for name, func in inspect.getmembers(module, inspect.isfunction)
            if name.startswith("test_")
        ]

        for name, func in test_funcs:
            total_run += 1
            try:
                sig = inspect.signature(func)
                if "engine" in sig.parameters:
                    from test_mock_reasoning import fixed_time, engine as make_engine
                    ft = fixed_time()
                    eng = make_engine(ft)
                    func(eng)
                else:
                    func()

                total_passed += 1
                print(f"  [PASS] {name}")
            except Exception:
                import traceback
                total_failed += 1
                print(f"  [FAIL] {name}")
                traceback.print_exc()

    elapsed = round(time.time() - start_time, 3)
    print("\n" + "=" * 75)
    print(f" TEST RUN SUMMARY: {total_passed}/{total_run} PASSED in {elapsed}s (Failed: {total_failed})")
    print("=" * 75)

    if total_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
