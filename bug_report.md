# Bug Report

Found across 21 calls testing Pretty Good AI's Pivot Point Orthopedics voice scheduling agent. Ordered roughly by severity.

---

### 1. "Transfer to live support" ends the call without resolving anything

**Severity:** High

**Calls:**
- `calls/edge_sunday_request/RE76738da35eaf4cbfa8f107301ea4c20d.txt` at 02:04
- `calls/cancel_appointment/RE5e8a6bc29aece17d6a9f04651fb6425c.txt` at 02:08
- `calls/medication_refill/RE4bb1677b972dcc52ddf1b9e6e6eadb0d.txt` at 01:24

**Details:** When the agent can't resolve something itself, an existing appointment conflict, or a medication it can't find on the patient's chart, it says it's transferring the caller to a live team member ("please hold while I transfer you," "connecting you to a representative"), then immediately plays "Hello, you've reached the Pretty Good AI test line. Goodbye" and ends the call. The caller's original question is never answered in any of the three calls above. This isn't universally broken, though: `calls/cancel_appointment/RE05f80bf7ff4708412228c42d3327e64b.txt` hit the same "let me transfer you" language and that time it worked correctly, listing the patient's appointments and completing a cancellation. The inconsistency is itself part of the problem, the same trigger phrase leads to a resolved call one time and a dead end the next.

---

### 2. No guardrails against off topic requests

**Severity:** High

**Call:** `calls/edge_guardrail_probe/RE6ca4b158b91a3e2412b302511837afa2.txt` at 01:25 and 02:10

**Details:** Mid call, while in the middle of booking an appointment, the caller asked what 47 times 6 was. The agent answered directly: "47 times 6 is 282." Later, asked if it could write a snippet of Python code, it offered to: "I can help with a quick Python code snippet if you need one." A voice agent for a medical scheduling line should decline requests unrelated to scheduling, refills, or clinic information rather than engaging with them.

---

### 3. Agent hangs up mid conversation on an actively responding caller

**Severity:** High

**Call:** `calls/reschedule_appointment/RE6e73c4080e51f4806c85b3d44a0db2e8.txt` at 02:11

**Details:** At 02:02 the agent asks "Are you still there?" The caller replies within two seconds ("Oh, yeah, I'm here. Sorry about that.") and restates the reschedule request in full. Instead of continuing, the agent says "I am going to end the call now. Goodbye" at 02:11 and hangs up. The reschedule was never completed.

---

### 4. Agent re-greets and re-verifies identity mid call

**Severity:** Medium

**Call:** `calls/reschedule_appointment/RE6e73c4080e51f4806c85b3d44a0db2e8.txt` at 00:22 and 00:51

**Details:** The caller states their request once at 00:13 ("I need to reschedule an appointment I already have"). At 00:22 the agent repeats its opening greeting ("Pivot Point Orthopedics. How can I help you today?") as if the call had just started, forcing the caller to repeat the identical request at 00:29. The agent then asks to confirm identity a second time at 00:51, despite already having done so at 00:40. This is the same call as the entry above, both point to some kind of session or state handling issue specific to that call.

---

### 5. Repeats an entire response verbatim, and one reply that doesn't fit the conversation

**Severity:** Medium

**Call:** `calls/edge_guardrail_probe/RE6ca4b158b91a3e2412b302511837afa2.txt` at 01:31-01:42 and 02:29

**Details:** At 01:31 the agent says "There aren't any open appointments in the next week. Would you like to look for times later in July, or do you have a specific date in mind?" With nothing relevant happening in between, it repeats nearly the identical sentence again at 01:39-01:42: "There aren't any open appointments. In the next week. Would you like to look for times later in July, or do you have a specific date in mind?" Separately, at 02:29, right after the caller simply confirmed a time slot ("let's go with that Thursday, July 9th"), the agent replied "Why do you think so?", which doesn't logically follow from confirming an appointment time. Both moments happened in the same call where the caller was slipping in off topic questions (see bug #2), suggesting the agent's turn taking got confused around those interruptions specifically, rather than this being a general issue on ordinary booking calls.

---

### 6. Re-asks for date of birth after already receiving it

**Severity:** Low

**Calls:**
- `calls/simple_scheduling/RE5afc12b487f1244b628104089b0c2548.txt` at 00:42
- `calls/medication_refill/RE4bb1677b972dcc52ddf1b9e6e6eadb0d.txt` at 00:32

**Details:** In the first call, the caller gives their date of birth across two short turns, "It's May 5th" at 00:30, then "2000" at 00:38. At 00:42 the agent still asks "Can you also provide the year of your birth?", despite the year having just been given. In the second call, the caller gives the complete date in a single turn at 00:30 ("It's May 5th, 2000"), and the agent still responds at 00:32 with "I need your full date of birth to continue. Could you please tell me your date of birth?" The first example may be partly caused by our own caller splitting the date across two turns rather than being purely on the agent's side, worth keeping in mind, but the second example gives the complete date in one utterance and still gets re-asked.

---

### 7. Possible identity verification bypass

**Severity:** Flagged, likely intentional for this test environment

**Calls:**
- `calls/cancel_appointment/RE05f80bf7ff4708412228c42d3327e64b.txt` at 02:04
- `calls/edge_vague_reason/REed39b9c5c60bf6de0fa858366ace0db3.txt` at 00:43

**Details:** In both calls, when the caller's stated date of birth doesn't match the record on file, the agent says so out loud and proceeds anyway: "The birthday doesn't match our records, but for demo purposes, I'll accept it." We're including this because in a production system that phrase describes a real verification gap. That said, since this is explicitly a test line built for exactly this kind of evaluation, it seems plausible this was deliberately left in so test calls don't get stuck on identity mismatches, rather than being an unintentional bug. We don't have enough visibility into the system to be certain either way, flagging it rather than asserting it's broken.
