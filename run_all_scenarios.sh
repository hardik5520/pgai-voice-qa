#!/usr/bin/env bash
# Runs every remaining scenario end to end: places the call, waits for it to
# finish and for Twilio to finish processing the recording, transcribes it,
# then waits again before starting the next one.
#
# cancel_appointment is repeated before every scenario that tries to book a
# new appointment, so each one starts from a clean slate instead of running
# into whatever's currently on file and derailing into the conflict/transfer
# flow, which is what happened repeatedly when that wasn't the case.
#
# server.py must already be running in another terminal, with the current
# personas.py loaded (restart it first if you just edited that file).

set -uo pipefail

CALL_WAIT_SECONDS=420        # 7 minutes, time for the call itself to finish
TRANSCRIBE_WAIT_SECONDS=300  # 5 minutes, pacing before the next call

SCENARIOS=(
    simple_scheduling
    reschedule_appointment
    cancel_appointment
    medication_refill
    office_hours_and_location
    insurance_question
    edge_vague_reason
    cancel_appointment
    edge_interruption
    cancel_appointment
    edge_correction
    cancel_appointment
    edge_guardrail_probe
    cancel_appointment
    edge_sunday_request
)

for scenario in "${SCENARIOS[@]}"; do
    echo "[$(date +%H:%M:%S)] placing call: ${scenario}"
    python make_call.py "${scenario}"

    echo "[$(date +%H:%M:%S)] waiting ${CALL_WAIT_SECONDS}s for the call to finish"
    sleep "${CALL_WAIT_SECONDS}"

    echo "[$(date +%H:%M:%S)] transcribing"
    python transcribe.py

    echo "[$(date +%H:%M:%S)] waiting ${TRANSCRIBE_WAIT_SECONDS}s before the next call"
    sleep "${TRANSCRIBE_WAIT_SECONDS}"
done

echo "[$(date +%H:%M:%S)] done, ${#SCENARIOS[@]} calls placed"
