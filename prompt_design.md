# Prompt Design Document
## Closira — Pawfect Stay Pet Hotel & Grooming

---

## 1. Full System Prompt

The system prompt lives in `prompt.py` — a dedicated file imported by both `main.py` and `test_scenarios.py`. This ensures there is exactly one copy of the prompt in the codebase. Any change to the prompt is automatically reflected in both the live chat and the test runner.

```
You are Biscuit, a warm and knowledgeable AI assistant for Pawfect Stay Pet Hotel
& Grooming in Austin, Texas. Your personality is friendly and reassuring — pet
owners care deeply about their animals and want to feel like they're leaving them
somewhere safe and loved.

============================
SOP — YOUR ONLY SOURCE OF TRUTH
============================
[SOP JSON injected at runtime from sop_data.json]
============================

== CORE RULES ==
1. Answer ONLY from the SOP above. Do not guess or make something up.
2. When you cannot answer or an escalation trigger fires, begin your reply with:
   ESCALATE: [specific reason]
   Then write your warm customer-facing message. The ESCALATE line is an internal
   system flag — write it, then continue with the reply.
3. Never give medical or veterinary advice. Always escalate.
4. Never negotiate prices or make promises not in the SOP.
5. If a customer mentions an incident (injury, fight, illness during a stay),
   escalate immediately.

== ESCALATION TRIGGERS ==
- Customer is angry, upset, or uses frustrated language
- Medical or health question about a specific animal
- Incident during a past or current stay mentioned
- Custom price or discount requested
- 2+ questions with NO answer in the SOP (partial answers count as answered)
- Explicit request for a manager or human
- Formal complaint

== LEAD QUALIFICATION ==
When a customer shows booking interest, ask ONE AT A TIME:
  Q1: Pet name and type
  Q2: Which service — boarding, daycare, or grooming?
  Q3: First visit or returning?

== TONE ==
- Warm, friendly, reassuring — like a trusted pet-sitter
- Short messages (2–5 sentences)
- Use the pet's name once known
- No corporate language
- Only mention facility details if specifically asked
- Acknowledge nervousness before answering
- Never say you can complete a booking — only collect details
- After escalation, never promise to arrange a callback — only say the team has been notified
```

---

## 2. Why This Business and SOP

Pet care is an emotionally charged service. Owners dropping off an animal for ten days are anxious and trust-sensitive in a way that B2B or retail customers are not. This makes the design more interesting across every dimension:

- **Escalation** has real urgency — an injury during a stay is not a billing dispute, it's a potential liability and a distressed owner. The agent must escalate immediately.
- **Tone** matters more — a cold, transactional reply to a nervous first-time boarder can lose the booking even if the answer is correct.
- **Hallucination risk** is higher — if the AI invents a vaccine policy or price, the customer might show up unprepared and be turned away. The consequences are concrete.

The SOP was designed to be realistic and rich: 13 services with exact prices, vaccination requirements by species, cancellation and check-in policies, a loyalty programme, a sick-pet protocol, and 8 explicit escalation rules.

---

## 3. Project Architecture

The codebase is split across four files with clear responsibilities:

| File | Responsibility |
|---|---|
| `prompt.py` | Single source of truth for the system prompt and SOP loading |
| `utils.py` | Shared `call_with_retry()` and `parse_reply()` — used by both main and test runner |
| `main.py` | Live CLI chat loop, conversation state, session logging, `--demo` mode |
| `test_scenarios.py` | Automated test runner, transcript generation |

This separation means:
- The prompt is never duplicated or out of sync
- Retry logic and reply parsing are never duplicated
- Both the live agent and the test runner use identical logic

---

## 4. Key Prompt Design Decisions

### Giving the AI a persona name ("Biscuit")
For a pet hotel, personality is part of the product. A named assistant signals warmth before the first word of the actual reply. It sets the tone for the whole conversation. Owners responding to a "Biscuit" feel differently than owners responding to "AI Assistant."

### SOP injected as JSON at runtime
The SOP loads from `sop_data.json` every time `prompt.py` is imported. The business can update prices, hours, or policies by editing one JSON file — no code changes. This is how it would work in production and it's worth doing correctly from the start.

### Section dividers inside the prompt (`====`)
Strong visual delimiters help the model treat each section as a distinct instruction category rather than blending them into a single body of text. Without clear separators, long system prompts suffer from instruction bleed — rules in one section get softened by adjacent context.

### Qualification questions are fixed, not improvised
Rather than asking the model to figure out qualification, three specific questions are given verbatim. This guarantees consistent lead capture across every conversation. The model decides *when* to enter qualification mode, but not *what to ask*.

---

## 5. Hallucination Prevention

**Rule 1 — Explicit prohibition**
The first core rule names the failure mode directly: *"Do not guess or make something up."* This is more effective than "use only provided information" because it targets the specific behaviour (guessing) rather than the desired state.

**Rule 2 — Escalation as the fallback, not refusal**
The model is not told to say "I don't know." It's told to escalate with a reason. A flat refusal is a dead end for the customer. An escalation with a logged reason tells the human team exactly what was asked, gives the customer a path forward, and creates a data trail of SOP gaps.

**Rule 3 — SOP loaded fresh every run**
No stale information is baked into any trained weight. If the SOP changes, the next conversation reflects it automatically.

**Rule 4 — Out-of-SOP gaps tracked separately from tone escalations**
The session log tracks `sop_gaps` only when the escalation reason contains gap-specific language ("not covered", "no information", "out of scope"). Angry customer escalations do not pollute the SOP gap list. This distinction makes the gap data actionable rather than noisy.

**No hard-coded topic list**
The system does not rely on hard-coded keyword lists to force escalation. Instead, the prompt and `ESCALATE:` output format are the single source of truth, so any out-of-SOP topic is handled consistently.

---

## 6. Escalation Design

**Detection method: output-format-based**
The model outputs `ESCALATE: reason` on the first line as an internal flag. `parse_reply()` in `utils.py` strips this line before anything reaches the customer. The customer sees only the warm reassurance. The reason is logged internally.

This approach was chosen over a secondary sentiment classifier because:
- No extra API call = no added latency or cost
- The reason is in plain English, immediately usable by the human picking it up
- The logic is transparent and debuggable

**Escalation state across a session**
Each session maintains `escalation_reasons` (a list — all escalations preserved) and `escalation_notice_count` (an integer — how many escalation notices have been shown). The chat loop shows a notice whenever the count of escalation reasons increases. The reasons list is never cleared, and the session summary/log reflect every escalation.

**`low_confidence_turns`**
Every turn number where the model escalated is stored in `low_confidence_turns`. This gives the human team a turn-by-turn signal about where the AI struggled, without requiring any extra inference.

**Escalation trigger categories:**

| Trigger | Why it matters |
|---|---|
| Angry/frustrated tone | AI de-escalation attempts can backfire; hand off fast |
| Medical/health question | Potential liability; never answer |
| Incident during stay | Urgent; requires human with access to records |
| Pricing negotiation | AI has no authority to offer deals |
| Out-of-SOP (×2) | Repeated failures signal a real SOP gap worth logging |
| Explicit human request | Non-negotiable |
| Formal complaint | Legal and reputational risk |

---

## 7. Retry Logic

Every API call goes through `call_with_retry()` in `utils.py`:

```python
from typing import Callable, Optional, Tuple

def call_with_retry(fn: Callable[[], object], retries: int = 3) -> Tuple[object, Optional[str]]:
    for attempt in range(retries):
        try:
            return fn(), None
        except RateLimitError:
            if attempt == retries - 1:
                return None, "rate_limit"
            time.sleep(2 ** attempt)
        except APIConnectionError:
            if attempt == retries - 1:
                return None, "connection"
            time.sleep(2 ** attempt)
    return None, "unknown"
```

The contract is consistent: always returns `(result, None)` on success, `(None, error_str)` on failure. All callers pass bare lambdas — the wrapper does the tuple construction. Callers access `resp.choices[0]...` directly with no indexing gymnastics.

---

## 8. Tone and Persona

Pet owners text on their phones, often while anxious. Tone choices:

- **Short replies always** — 2–5 sentences max, hard-coded in the prompt
- **Use the pet's name** — extracted via regex from the conversation, applied from the next reply onward. Regex is case-insensitive (`[a-zA-Z]+` with `.capitalize()`) so "her name is luna" works as well as "Her name is Luna"
- **Acknowledge nervousness first** — explicitly in the prompt: "acknowledge the feeling before answering"
- **No booking promises** — the AI cannot confirm dates or complete transactions. The prompt explicitly forbids saying "I'll guide you through booking"
- **No post-escalation promises** — the AI cannot arrange callbacks. It can only say the team has been notified

---

## 9. What I'd Add With More Time

- **Redis session store** keyed by WhatsApp phone number — so conversations persist across messages, not just within a single CLI run
- **WhatsApp Business API webhook** — the conversation state logic in `main.py` is already structured for async message handling
- **SOP gap dashboard** — the `sop_gaps` array in session logs is a seed for analytics. Over 100 sessions, patterns emerge ("everyone asks about hydrotherapy") and the SOP can be updated
- **Streaming responses** — `client.chat.completions.create(stream=True)` would make replies appear word-by-word, reducing perceived latency significantly
- **Vaccination reminder flow** — prompt returning customers to confirm vaccines before confirming a booking, reducing same-day surprises at check-in
