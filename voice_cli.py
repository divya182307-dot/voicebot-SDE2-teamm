"""
Interactive Voice Interface CLI for SDE-2 Voicebot Engine.
Simulates transcribed voice input, demonstrates multimodal reaction,
intent classification, safety gating, and optional spoken TTS audio feedback.

Usage:
    # 1. Single-shot voice command:
    python projects/sde-2-voicebot/voice_cli.py "Why is this code throwing an exception?"
    python projects/sde-2-voicebot/voice_cli.py "Move these files into my project folder"
    python projects/sde-2-voicebot/voice_cli.py "Delete all database tables"

    # 2. Interactive voice dialogue session:
    python projects/sde-2-voicebot/voice_cli.py --interactive

    # 3. Speak response aloud through Windows speakers (TTS audio):
    python projects/sde-2-voicebot/voice_cli.py "Why is this failing?" --speak
"""

import argparse
import os
import subprocess
import sys
import time

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.schemas.common import InputModality, RiskLevel
from app.schemas.reasoning import ReasoningRequest, ReasoningResult
from app.reasoning.mock_engine import DeterministicMockReasoningEngine
from app.vision.synthetic_frames import ScreenCaptureManager, SyntheticScenario


def play_audio_tts(text: str):
    """Speaks the response aloud through Windows audio synthesizer (SAPI)."""
    clean_text = text.replace('"', '').replace("'", '').replace("`", "")
    ps_command = (
        f"Add-Type -AssemblyName System.Speech; "
        f"$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$speaker.Speak('{clean_text}')"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_command], check=False)
    except Exception:
        pass


def process_voice_input(
    engine: DeterministicMockReasoningEngine,
    user_utterance: str,
    enable_screen: bool = True,
    speak_audio: bool = False,
):
    """Processes a voice utterance and displays the engine's reaction and safety gates."""
    print("\n" + "=" * 75)
    print(" [VOICE INPUT] INCOMING SPOKEN UTTERANCE")
    print("=" * 75)
    print(f" User Spoke: \"{user_utterance}\"")

    screen_frame = None
    if enable_screen:
        mgr = ScreenCaptureManager(capture_enabled=True)
        q_lower = user_utterance.lower()
        if "paper" in q_lower or "pdf" in q_lower or "methodology" in q_lower:
            sc = SyntheticScenario.RESEARCH_PAPER_PDF
        elif "sales" in q_lower or "sheet" in q_lower or "growth" in q_lower:
            sc = SyntheticScenario.SPREADSHEET_ANALYSIS
        elif "secret" in q_lower or "key" in q_lower:
            sc = SyntheticScenario.REDACTED_PRIVACY
        else:
            sc = SyntheticScenario.CODE_EDITOR_ERROR

        screen_frame = mgr.capture_frame(sc)
        print(f"\n [VISUAL CONTEXT] Active Workspace Screen Grounding:")
        print(f"  - Application : {screen_frame.application_name} ({screen_frame.width}x{screen_frame.height}px)")
        print(f"  - Active Area : {screen_frame.window_title}")
        first_line = screen_frame.ocr_text.splitlines()[0] if screen_frame.ocr_text else "None"
        print(f"  - OCR Snippet : {first_line}")

    req = ReasoningRequest(
        request_id=f"voice-req-{int(time.time() * 1000) % 100000}",
        session_id="voice-session-interactive",
        user_query=user_utterance,
        modality=InputModality.VOICE,
        screen_context=screen_frame,
    )

    t0 = time.perf_counter()
    res: ReasoningResult = engine.reason(req)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    print("\n [ENGINE REACTION] Intent & Risk Evaluation:")
    print(f"  - Detected Intent   : {res.user_intent}")
    print(f"  - Confidence Score  : {res.confidence_score * 100:.1f}%")
    print(f"  - Processing Time   : {res.processing_time_ms:.2f} ms (Round-trip: {latency_ms:.2f} ms)")

    print("\n [SAFETY GATE] PRD Section 18 Human-In-The-Loop:")
    if res.risk_level == RiskLevel.CATEGORY_A_INFORMATIONAL:
        print(f"  - Risk Level        : CATEGORY A (Informational / Read-Only)")
        print(f"  - Approval Required : NO (Execution proceeds immediately)")
    elif res.risk_level == RiskLevel.CATEGORY_C_SENSITIVE:
        print(f"  - Risk Level        : CATEGORY C (Sensitive File/State Modification)")
        print(f"  - Approval Required : YES (HALTS EXECUTION FOR VERBAL CONFIRMATION)")
        print(f"  - Verbal Gate Prompt: \"{res.approval_prompt}\"")
    elif res.risk_level == RiskLevel.CATEGORY_D_HIGH_RISK_DESTRUCTIVE:
        print(f"  - Risk Level        : CATEGORY D (Irreversible Destructive Operation)")
        print(f"  - Approval Required : YES (CRITICAL HUMAN CONFIRMATION GATE)")
        print(f"  - Verbal Gate Prompt: \"{res.approval_prompt}\"")

    if res.tool_call_required and res.action_plan:
        print(f"\n [PLANNED ACTIONS] Multi-Step Plan:")
        for step in res.action_plan:
            print(f"    Step {step.step_number}: [{step.tool_name}] -> {step.step_description}")

    print("\n [VOICEBOT REACTION] Spoken Response (TTS Audio Output):")
    print(f"  \"{res.response_text}\"")
    print("=" * 75)

    if speak_audio:
        to_speak = res.approval_prompt if (res.requires_user_approval and res.approval_prompt) else res.response_text
        print("\n [Playing audio response through Windows speakers...]")
        play_audio_tts(to_speak)

    return res


def run_interactive_mode(engine: DeterministicMockReasoningEngine, speak_audio: bool = False):
    """Starts an ongoing interactive voice dialogue loop in the terminal."""
    print("\n" + "=" * 75)
    print(" ACADEMIA AI VOICEBOT - INTERACTIVE VOICE SHELL")
    print(" Speak or type your voice utterance below.")
    print(" Type 'exit' or 'quit' to end the session.")
    print("=" * 75)
    print(" [MICROPHONE TIP] To speak using your physical microphone:")
    print("   1. Click on this terminal window.")
    print("   2. Press [Windows Key + H] (Win + H) on your keyboard.")
    print("   3. Windows Voice Dictation will open at the top of your screen.")
    print("   4. Speak into your mic! Windows will type your words in real time.")
    print("   5. Press Enter to submit your spoken utterance to the Voicebot.")
    print("-" * 75)

    example_queries = [
        "Why is this code throwing an exception?",
        "Move these result files to my archive folder",
        "Delete all student records from database",
        "Summarize the research methodology in this paper",
    ]
    print("\nSuggested Voice Queries to try:")
    for ex in example_queries:
        print(f"   * \"{ex}\"")
    print()

    while True:
        try:
            user_input = input("Speak Voice Query > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("\nVoicebot session ended. Goodbye!")
                break

            process_voice_input(engine, user_input, enable_screen=True, speak_audio=speak_audio)
            print()
        except (KeyboardInterrupt, EOFError):
            print("\nSession interrupted. Exiting.")
            break


def main():
    parser = argparse.ArgumentParser(description="Academia AI Voicebot Command-Line Voice Interface")
    parser.add_argument("query", nargs="?", default=None, help="Spoken voice query utterance")
    parser.add_argument("--interactive", "-i", action="store_true", help="Launch interactive voice dialogue shell")
    parser.add_argument("--speak", "-s", action="store_true", help="Speak response aloud through Windows speakers (TTS audio)")
    parser.add_argument("--no-screen", action="store_true", help="Disable active screen context capture")

    args = parser.parse_args()
    engine = DeterministicMockReasoningEngine()

    if args.interactive or args.query is None:
        run_interactive_mode(engine, speak_audio=args.speak)
    else:
        process_voice_input(
            engine=engine,
            user_utterance=args.query,
            enable_screen=not args.no_screen,
            speak_audio=args.speak,
        )


if __name__ == "__main__":
    main()
