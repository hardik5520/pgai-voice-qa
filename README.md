# PrettyGoodAI voice bot tester

This is an automated voice bot that calls Pretty Good AI's test scheduling line, plays a patient trying to book, reschedule, cancel, or ask questions, and records and transcribes the whole conversation so the results can be reviewed for bugs.

It does not use a script. Each call is given a short description of who the caller is and what they're trying to accomplish, and a live AI model handles the actual back and forth conversation, reacting to whatever the scheduling agent on the other end actually says.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design writeup, and [bug_report.md](bug_report.md) for what was found.

## How it works, in short

There are two AI models involved, doing two different jobs. While a call is happening, OpenAI's Realtime API listens to the other side and speaks back as the patient, live, the same way a phone call actually works. After the call ends, a separate transcription model turns the recording into a written transcript, that one never talks, it just listens to a finished recording and writes down what it heard.

Twilio is the telephone company piece, it's what actually places the call and records it. A small local server, `server.py`, sits in the middle and moves audio back and forth between Twilio and OpenAI in real time. Since that server only runs on your own laptop, it needs a public tunnel (ngrok) so Twilio's servers out on the internet can actually reach it.

## What you need before starting

* Python 3.11 or newer
* [ffmpeg](https://ffmpeg.org/) installed and on your PATH, check with `ffmpeg -version`, install with `brew install ffmpeg` on macOS if it's missing
* [ngrok](https://ngrok.com/) installed, a free account is enough
* A Twilio account with billing enabled (a trial account will not work, it blocks calls to unverified numbers and adds an audible watermark to every call) and one phone number purchased on it
* An OpenAI API key with access to the Realtime API and with some prepaid credit on the account

Expect well under $20 total in Twilio and OpenAI usage for a full run of every scenario.

## Setup

Clone the repo and set up a virtual environment:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy the example environment file and fill it in:

```
cp .env.example .env
```

Open `.env` and set:

* `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`, from the Twilio console
* `TWILIO_CALLER_NUMBER`, the one number you bought in Twilio, in E.164 format, e.g. `+14015551234`
* `OPENAI_API_KEY`
* `PUBLIC_SERVER_URL`, filled in during the next step, leave it as the placeholder for now

`OPENAI_REALTIME_MODEL`, `OPENAI_VOICE`, and `PORT` already have sensible defaults in `.env.example` and don't need to change.

## Running it

Three things need to be running at once, each in its own terminal.

**1. Start the public tunnel**

```
ngrok http 8000
```

Copy the `https://...ngrok-free.app` forwarding URL it prints, and paste it into `PUBLIC_SERVER_URL` in `.env`.

**2. Start the bridge server**

```
source .venv/bin/activate
python server.py
```

Leave this running for the entire session. If you ever edit `personas.py`, `config.py`, or `server.py`, this needs to be restarted before the change takes effect, it doesn't reload automatically.

**3. Place calls**

To run every scenario end to end, one after another, with automatic transcription in between:

```
source .venv/bin/activate
./run_all_scenarios.sh
```

This takes a few hours, since each call needs time to actually happen and Twilio needs time to finish processing the recording before it can be downloaded. To run a single scenario by hand instead:

```
python make_call.py simple_scheduling
```

wait for the call to finish (a minute or two after it ends, once Twilio finishes processing the recording), then:

```
python transcribe.py
```

which automatically picks up the most recent call.

## What's in this repo

* `server.py` — the live audio bridge between Twilio and OpenAI's Realtime API, this is the core of the whole thing
* `make_call.py` — places one outbound call for a given scenario
* `transcribe.py` — downloads a finished call recording, splits it into each speaker's own audio channel, and produces a written transcript
* `personas.py` — the eleven test scenarios, each one a short description of who the caller is and what they're trying to do
* `config.py` — loads and validates environment variables
* `run_all_scenarios.sh` — runs every scenario in sequence unattended
* `calls/` — one folder per scenario, each containing the recording (`.mp3`), a raw two channel copy (`_dual.mp3`, not meant for listening, just used internally for accurate transcription), and the transcript (`.txt`)

## The eleven scenarios

* `simple_scheduling` — books a new appointment
* `reschedule_appointment` — moves an existing appointment (needs one to already exist, run after `simple_scheduling`)
* `cancel_appointment` — cancels whatever's currently on file
* `medication_refill` — requests a prescription refill
* `office_hours_and_location` — asks about hours and address, no booking
* `insurance_question` — asks about accepted insurance and cost, no booking
* `edge_sunday_request` — asks for an appointment on a day the office is likely closed
* `edge_vague_reason` — gives a deliberately vague reason for calling
* `edge_interruption` — talks over the agent mid sentence a couple of times
* `edge_correction` — gives a wrong date of birth, then corrects it
* `edge_guardrail_probe` — mixes in off topic requests (math, code, trivia) to test whether the agent stays in scope

Every scenario uses the same caller identity, Hardik Arora, born May 5th 2000, since Pretty Good AI's test account ties a real, persistent patient record to the calling phone number. That means state carries over between calls, an appointment booked in one call is still there the next time you call. `reschedule_appointment` and `cancel_appointment` are written to work with whatever's actually on file rather than assuming a specific date, for exactly this reason.

## Iteration

Two rounds of changes came directly out of listening to early calls rather than being planned upfront.

The first: `reschedule_appointment` and `cancel_appointment` were originally written to describe the situation ("you have an appointment, you need to move it") without telling the model what to actually say first. In practice this meant the caller opened both scenarios with a generic "I'd like to book an appointment," the same as a fresh booking call, instead of stating the real intent. This only became obvious from listening to the actual transcripts, the persona reads fine on paper. Both prompts were rewritten to explicitly state the opening line, and rerun to confirm the fix actually changed the caller's behavior before moving on, that's why each of those scenarios has an early call that opens generically and a later one that opens by clearly stating reschedule or cancel intent.

The second reason `cancel_appointment` specifically appears more than once by design: this test account uses one persistent caller identity for every single call, meaning a real appointment booked in one call is still on file for the next one. Several scenarios need to book a fresh appointment to actually test what they're meant to test, so `run_all_scenarios.sh` deliberately runs `cancel_appointment` again before each of them, clearing the slate rather than letting an unrelated leftover appointment from an earlier call derail an unrelated scenario. Most of the repeated `cancel_appointment` recordings are this cleanup step, not redundant testing.

## A known limitation of the transcripts

Transcription is done by feeding short, isolated clips of detected speech to a transcription model rather than the whole recording at once, since that gives far more reliable timestamps than asking a model to time-stamp a long, mostly silent file itself. Occasionally, a clip that's just noise or a click, rather than an actual word, gets transcribed into a plausible sounding but wrong short phrase, since transcription models don't have a way to say "I heard nothing meaningful here." This is rare and usually shows up as an isolated, out of place line, worth a quick sanity check against the audio for anything you plan to cite directly.
