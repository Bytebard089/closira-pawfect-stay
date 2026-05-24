"""
test_scenarios.py — Pawfect Stay
=================================
Automatically runs all 5 required scenarios and saves transcripts.
No manual input needed.

Usage: python test_scenarios.py
"""

import os
import json
import time
import datetime
from groq import Groq

from prompt import SYSTEM_PROMPT
from utils import call_with_retry, parse_reply

TRANSCRIPT_DIR = "test_transcripts"
MODEL          = "llama-3.3-70b-versatile"
os.makedirs(TRANSCRIPT_DIR, exist_ok=True)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


def simulate(name: str, turns: list) -> str:
    messages          = []
    lines             = []
    escalated         = False
    escalation_reason = ""

    lines.append(f"# Test Scenario: {name}")
    lines.append(f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)
    lines.append("")

    opening = ("Hi there! I'm Biscuit, your assistant at Pawfect Stay. "
               "Whether you're thinking of boarding, daycare, or grooming — "
               "I'm here to help. What can I do for you today?")
    lines.append(f"**Biscuit:** {opening}")
    lines.append("")
    messages.append({"role": "assistant", "content": opening})

    for turn in turns:
        if turn["role"] != "user":
            continue

        content = turn["content"]
        lines.append(f"**Customer:** {content}")
        messages.append({"role": "user", "content": content})

        resp, err = call_with_retry(
            lambda: client.chat.completions.create(
                model       = MODEL,
                max_tokens  = 500,
                temperature = 0.4,
                messages    = [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            )
        )

        if err:
            raw = "ESCALATE: API error\nI'm having trouble connecting right now — a team member will be in touch shortly."
        else:
            raw = resp.choices[0].message.content.strip()

        # ── Always parse — never write raw reply to transcript ──
        is_escalation, reason, clean_reply = parse_reply(raw)

        messages.append({"role": "assistant", "content": clean_reply})
        lines.append(f"**Biscuit:** {clean_reply}")
        lines.append("")

        if is_escalation:
            escalated         = True
            escalation_reason = reason
            lines.append(f"> **[SYSTEM]** Escalation flagged — {reason}")
            lines.append("")
            break

    # ── Summary ──
    summary_prompt = f"""
Review this Pawfect Stay support conversation and write a structured summary.

Conversation:
{json.dumps(messages, indent=2)}

Escalated: {escalated}
Escalation reason: {escalation_reason if escalated else "N/A"}

Use exactly these sections:

## Customer Intent
[1-2 sentences]

## Key Details Collected
[Bullet list or "None"]

## SOP Gaps Identified
[Topics not in SOP, or "None"]

## Escalation Status
[Status + reason, or "No escalation required"]

## Confidence Signal
[Any turns where the AI was uncertain, or "All turns handled confidently"]

## Recommended Next Action
[Specific next step for the team]
"""
    sr, err = call_with_retry(
        lambda: client.chat.completions.create(
            model      = MODEL,
            max_tokens = 500,
            messages   = [
                {"role": "system", "content": "You are a helpful business analyst."},
                {"role": "user",   "content": summary_prompt},
            ],
        )
    )
    summary = sr.choices[0].message.content.strip() if not err else "Summary unavailable."

    lines.append("")
    lines.append("---")
    lines.append("## Session Summary")
    lines.append("")
    lines.append(summary)

    return "\n".join(lines)


# ── Scenarios ──────────────────────────────────────────────────────────────────
SCENARIOS = [
    {
        "filename": "scenario_1_in_sop_question.md",
        "name":     "Scenario 1 — In-SOP Question (Boarding prices & policies)",
        "turns": [
            {"role": "user", "content": "Hi! How much does overnight dog boarding cost?"},
            {"role": "user", "content": "Does that include food or do I bring my own?"},
            {"role": "user", "content": "What time does checkout need to be?"},
        ],
    },
    {
        "filename": "scenario_2_out_of_scope.md",
        "name":     "Scenario 2 — Out-of-Scope Question",
        "turns": [
            {"role": "user", "content": "Do you offer dog training classes for adult dogs?"},
            {"role": "user", "content": "What about hydrotherapy or swimming sessions?"},
            {"role": "user", "content": "Can you do any kind of anxiety behavioural assessment?"},
        ],
    },
    {
        "filename": "scenario_3_escalation_trigger.md",
        "name":     "Scenario 3 — Escalation Trigger (Complaint / Angry Customer)",
        "turns": [
            {"role": "user", "content": "I picked up my dog Milo yesterday and he had a cut on his leg. Nobody told me anything about it. I'm absolutely furious."},
            {"role": "user", "content": "I want to speak to someone senior right now. This is completely unacceptable."},
        ],
    },
    {
        "filename": "scenario_4_lead_qualification.md",
        "name":     "Scenario 4 — Lead Qualification",
        "turns": [
            {"role": "user", "content": "Hey, I'm going on holiday for 10 days in July and need someone to look after my dog. Do you do long stays?"},
            {"role": "user", "content": "Her name is luna, she's a 3-year-old golden retriever."},
            {"role": "user", "content": "This would be our first time — I've never left her anywhere before and I'm honestly a bit nervous about it."},
            {"role": "user", "content": "She's a pretty social dog, loves other dogs. Would she be in a group setting?"},
            {"role": "user", "content": "Okay, that sounds great. What's the nightly rate and what do I need to bring?"},
        ],
    },
    {
        "filename": "scenario_5_full_conversation_summary.md",
        "name":     "Scenario 5 — Full Conversation with Summary",
        "turns": [
            {"role": "user", "content": "Hi! My name is James. I saw you on Google Maps and I'm wondering about grooming for my cat."},
            {"role": "user", "content": "He's a 4-year-old Persian, named mochi. His coat gets really matted."},
            {"role": "user", "content": "How much would a full groom cost and how long does it take?"},
            {"role": "user", "content": "Is there anything special I need to prepare before bringing him in?"},
            {"role": "user", "content": "Perfect. When can I book him in? And do you need proof of his vaccinations?"},
        ],
    },
]


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Running all 5 test scenarios — Pawfect Stay")
    print("=" * 60)
    for i, s in enumerate(SCENARIOS, 1):
        print(f"\n[{i}/5] {s['name']}")
        transcript = simulate(s["name"], s["turns"])
        path       = os.path.join(TRANSCRIPT_DIR, s["filename"])
        with open(path, "w") as f:
            f.write(transcript)
        print(f"  Done -> {path}")
    print("\n" + "=" * 60)
    print("  All done. Check test_transcripts/")
    print("=" * 60)
