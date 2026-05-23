"""
Closira AI Agent — Pawfect Stay Pet Hotel & Grooming
=====================================================
Four-stage AI workflow:
  Stage 1 — FAQ Answering      (SOP-grounded only)
  Stage 2 — Lead Qualification (structured questions, one at a time)
  Stage 3 — Escalation Detection (sentiment + scope + explicit triggers)
  Stage 4 — Conversation Summary (structured, actionable)

Run:         python main.py
Demo mode:   python main.py --demo
Env:         GROQ_API_KEY must be set (see .env.example)
"""

import os
import re
import json
import time
import datetime
import argparse
from groq import Groq

from prompt import SYSTEM_PROMPT
from utils import call_with_retry, parse_reply

# ── Config ─────────────────────────────────────────────────────────────────────
LOG_DIR = "logs"
MODEL   = "llama-3.3-70b-versatile"
os.makedirs(LOG_DIR, exist_ok=True)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ── Demo conversation (used with --demo flag) ──────────────────────────────────
DEMO_TURNS = [
    "Hi! How much does overnight dog boarding cost?",
    "Her name is Bella, she's a 2-year-old Labrador.",
    "Does that include food or do I bring my own?",
    "Is this her first time? Yes, totally new. What do I need to bring?",
    "What are your opening hours on Sunday?",
    "Perfect. I'll get in touch to book. Thanks!",
]


# ── Conversation State ─────────────────────────────────────────────────────────
class ConversationState:
    def __init__(self):
        self.messages              = []
        self.stage                 = "faq"
        self.lead_data             = {}
        self.escalated             = False
        self.escalation_shown      = False   # Track if notice already shown this session
        self.escalation_reasons    = []      # All escalations this session
        self.sop_gaps              = []      # Only genuine out-of-SOP topics
        self.unanswered_count      = 0       # Only out-of-SOP escalations
        self.low_confidence_turns  = []      # Turn numbers where AI escalated
        self.turn_number           = 0

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def log_dict(self) -> dict:
        return {
            "timestamp":            datetime.datetime.now().isoformat(),
            "stage_reached":        self.stage,
            "escalated":            len(self.escalation_reasons) > 0,
            "escalation_reasons":   self.escalation_reasons,
            "lead_data":            self.lead_data,
            "sop_gaps":             self.sop_gaps,
            "unanswered_count":     self.unanswered_count,
            "low_confidence_turns": self.low_confidence_turns,
            "total_turns":          self.turn_number,
        }


def _build_messages(state: ConversationState) -> list:
    return [{"role": "system", "content": SYSTEM_PROMPT}] + state.messages


# ── Stage 1–3: Get AI response ─────────────────────────────────────────────────
def get_response(state: ConversationState, user_input: str) -> str:
    state.turn_number += 1
    state.add("user", user_input)

    # API call with retry
    resp, err = call_with_retry(
        lambda: client.chat.completions.create(
            model       = MODEL,
            max_tokens  = 500,
            messages    = _build_messages(state),
            temperature = 0.4,
        )
    )

    if err:
        fallback = "Something went wrong on my end — please try again shortly."
        state.add("assistant", fallback)
        return fallback

    raw_reply = resp.choices[0].message.content.strip()

    # Strip ESCALATE line — customer never sees it
    escalated, reason, clean_reply = parse_reply(raw_reply)

    # Store only the clean reply in history
    state.add("assistant", clean_reply)

    if escalated:
        state.escalation_reasons.append(reason)
        state.low_confidence_turns.append(state.turn_number)
        _log_escalation(state, user_input, reason)

        # Only track as SOP gap if the reason is about missing information,
        # NOT about tone/anger/incidents (which are separate escalation types)
        sop_gap_signals = ["not in", "no information", "cannot find", "outside",
                           "not covered", "don't have details", "out of scope"]
        if any(s in reason.lower() for s in sop_gap_signals):
            state.unanswered_count += 1
            state.sop_gaps.append(user_input[:100])

        # Mark escalated for this turn (notice shown once per NEW escalation)
        state.escalated = True

    # Booking intent → qualification (only if not already in qualification)
    booking_signals = ["book", "reserve", "appointment", "schedule", "drop off",
                       "interested in boarding", "want to board", "thinking of boarding",
                       "thinking of bringing", "bring my dog", "bring my cat"]
    if state.stage == "faq" and any(s in user_input.lower() for s in booking_signals):
        state.stage = "qualification"

    # Pet name extraction (case-insensitive, no capital letter assumption)
    if "pet_name" not in state.lead_data:
        _try_extract_pet_name(user_input, state)

    return clean_reply


def _try_extract_pet_name(text: str, state: ConversationState):
    patterns = [
        r"(?:my (?:dog|cat|puppy|kitten|pet)(?:'s name)? is|her name is|his name is|they're called|named)\s+([a-zA-Z]+)",
        r"(?:dog|cat|puppy|kitten) called\s+([a-zA-Z]+)",
        r"(?:name is|called)\s+([a-zA-Z]+)",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            state.lead_data["pet_name"] = m.group(1).capitalize()
            break


# ── Stage 4: Session Summary ───────────────────────────────────────────────────
def generate_summary(state: ConversationState) -> str:
    prompt = f"""
You are reviewing a completed Pawfect Stay customer support conversation.

Conversation history:
{json.dumps(state.messages, indent=2)}

Lead data collected: {json.dumps(state.lead_data)}
SOP gaps (topics completely absent from SOP): {json.dumps(state.sop_gaps)}
Escalated: {len(state.escalation_reasons) > 0}
Escalation reasons: {json.dumps(state.escalation_reasons)}
Low confidence turns: {state.low_confidence_turns}

Write a structured summary with exactly these sections:

## Customer Intent
[1-2 sentences on what the customer wanted]

## Key Details Collected
[Bullet list — pet info, service interest, any specific needs. Write "None" if nothing gathered.]

## SOP Gaps Identified
[Topics the SOP did not cover. Write "None" if all questions were answered.]

## Escalation Status
[All escalations that occurred with reasons, or "No escalation required"]

## Confidence Signal
[Note any turns where the AI lacked confidence or escalated. Write "All turns handled confidently" if none.]

## Recommended Next Action
[Specific, practical next step for the Pawfect Stay team]
"""
    resp, err = call_with_retry(
        lambda: client.chat.completions.create(
            model      = MODEL,
            max_tokens = 600,
            messages   = [
                {"role": "system", "content": "You are a helpful business analyst."},
                {"role": "user",   "content": prompt},
            ],
        )
    )
    if err:
        return "Summary unavailable — API error during generation."
    return resp.choices[0].message.content.strip()


# ── Logging ────────────────────────────────────────────────────────────────────
def _log_escalation(state: ConversationState, trigger: str, reason: str):
    path    = os.path.join(LOG_DIR, "escalation_log.json")
    entries = []
    if os.path.exists(path):
        with open(path) as f:
            entries = json.load(f)
    entries.append({
        "timestamp":   datetime.datetime.now().isoformat(),
        "event":       "ESCALATION",
        "trigger_msg": trigger,
        "reason":      reason,
        "turn_number": state.turn_number,
    })
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)


def save_session(state: ConversationState, summary: str):
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, f"session_{ts}.json")
    with open(path, "w") as f:
        json.dump({**state.log_dict(),
                   "conversation": state.messages,
                   "summary":      summary}, f, indent=2)
    print(f"  [LOG] Session saved -> {path}")


# ── CLI Chat Loop ──────────────────────────────────────────────────────────────
def run(demo: bool = False):
    print("\n" + "=" * 62)
    print("  Pawfect Stay — AI Customer Support (powered by Closira)")
    if demo:
        print("  DEMO MODE — replaying canned conversation")
    else:
        print("  Type 'exit' or 'quit' to end your session.")
    print("=" * 62)

    state   = ConversationState()
    opening = ("Hi there! I'm Biscuit, your assistant at Pawfect Stay. "
               "Whether you're thinking of boarding, daycare, or grooming — "
               "I'm here to help. What can I do for you today?")

    print(f"\nBiscuit: {opening}\n")
    state.add("assistant", opening)

    demo_iter = iter(DEMO_TURNS) if demo else None

    while True:
        # ── Get input ──
        if demo:
            try:
                user_input = next(demo_iter)
                print(f"You: {user_input}")
            except StopIteration:
                print("\n[Demo complete]")
                break
        else:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n[Session ended by user]")
                break

        if not user_input:
            continue

        if not demo and user_input.lower() in {"exit", "quit", "bye", "goodbye"}:
            print("\nBiscuit: It was lovely chatting! Give your furry one a pat from us.\n")
            break

        reply = get_response(state, user_input)
        print(f"\nBiscuit: {reply}\n")

        # ── Show escalation notice once per session ──
        if state.escalated and not state.escalation_shown:
            state.escalation_shown = True
            state.escalated        = False   # Reset turn flag; reasons preserved in list
            print("  [NOTICE] A human team member has been notified and will follow up shortly.")
            print("           You can continue chatting with Biscuit in the meantime.\n")

        if demo:
            time.sleep(0.5)   # Slight pause so demo is readable

    # ── Stage 4: Summary ──
    print("\n" + "=" * 62)
    print("  Generating session summary...")
    print("=" * 62 + "\n")
    summary = generate_summary(state)
    print(summary)
    save_session(state, summary)
    print("\n[Session complete]")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pawfect Stay AI Support Agent")
    parser.add_argument("--demo", action="store_true",
                        help="Auto-play a canned demo conversation (no typing needed)")
    args = parser.parse_args()
    run(demo=args.demo)
