"""Places one outbound call to the test line and hangs up on Twilio's side
once the call ends. Run this after server.py is already running and your
tunnel URL is set in PUBLIC_SERVER_URL.

Usage:
    python make_call.py [scenario_name]
"""

import argparse

from twilio.rest import Client

import config
from personas import DEFAULT_SCENARIO, SCENARIOS


def place_call(scenario: str) -> str:
    client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    call = client.calls.create(
        to=config.TARGET_NUMBER,
        from_=config.TWILIO_CALLER_NUMBER,
        url=f"{config.PUBLIC_SERVER_URL}/voice/{scenario}",
        record=True,
        recording_channels="dual",
        recording_status_callback=f"{config.PUBLIC_SERVER_URL}/recording-status?scenario={scenario}",
        recording_status_callback_event=["completed"],
    )
    return call.sid


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "scenario", nargs="?", default=DEFAULT_SCENARIO, choices=list(SCENARIOS)
    )
    args = parser.parse_args()

    call_sid = place_call(args.scenario)
    print(f"call placed sid={call_sid} scenario={args.scenario} to={config.TARGET_NUMBER}")
