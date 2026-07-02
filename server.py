"""Bridges an outbound Twilio phone call to the OpenAI Realtime API so the
patient persona can hold a live spoken conversation with the target agent.

Two endpoints matter here:
  POST /voice/{scenario}          -> TwiML Twilio fetches when the call
                                      connects, telling it to open a media
                                      stream back to this server.
  WS   /media-stream/{scenario}   -> the actual audio bridge, phone audio in
                                      one direction, model audio out the
                                      other, both already in the g711 ulaw
                                      format Twilio uses so no resampling is
                                      needed.
POST /recording-status is a webhook Twilio calls once the call recording is
ready; it appends the call's metadata to calls/call_log.jsonl so transcribe.py
can find and download it without you having to copy SIDs around by hand.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
import websockets
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

import config
from personas import DEFAULT_SCENARIO, SCENARIOS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bridge")

app = FastAPI()

CALL_LOG_PATH = Path("calls/call_log.jsonl")

OPENAI_WS_URL = f"wss://api.openai.com/v1/realtime?model={config.OPENAI_REALTIME_MODEL}"

LOGGED_OPENAI_EVENTS = {
    "error",
    "session.created",
    "session.updated",
    "response.done",
    "input_audio_buffer.speech_started",
    "input_audio_buffer.speech_stopped",
}


@app.post("/voice/{scenario}")
async def voice(scenario: str):
    response = VoiceResponse()
    connect = Connect()
    stream_url = f"{config.PUBLIC_SERVER_URL.replace('https', 'wss')}/media-stream/{scenario}"
    connect.stream(url=stream_url)
    response.append(connect)
    return Response(content=str(response), media_type="application/xml")


@app.post("/recording-status")
async def recording_status(request: Request, scenario: str = "unknown"):
    form = await request.form()
    entry = {
        "scenario": scenario,
        "call_sid": form.get("CallSid"),
        "recording_sid": form.get("RecordingSid"),
        "recording_url": form.get("RecordingUrl"),
        "duration_seconds": form.get("RecordingDuration"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    log.info("recording ready %s", entry)

    CALL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CALL_LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")

    return Response(status_code=204)


@app.websocket("/media-stream/{scenario}")
async def media_stream(websocket: WebSocket, scenario: str):
    await websocket.accept()
    persona = SCENARIOS.get(scenario, SCENARIOS[DEFAULT_SCENARIO])
    log.info("call connected, scenario=%s", scenario)

    async with websockets.connect(
        OPENAI_WS_URL,
        extra_headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
    ) as openai_ws:
        await configure_session(openai_ws, persona["instructions"])

        state = {
            "stream_sid": None,
            "latest_media_timestamp": 0,
            "response_start_timestamp": None,
            "last_assistant_item": None,
            "has_active_response_audio": False,
        }

        await asyncio.gather(
            twilio_to_openai(websocket, openai_ws, state),
            openai_to_twilio(websocket, openai_ws, state),
        )


async def configure_session(openai_ws, instructions: str):
    await openai_ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "model": config.OPENAI_REALTIME_MODEL,
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcmu"},
                            "turn_detection": {"type": "server_vad"},
                        },
                        "output": {
                            "format": {"type": "audio/pcmu"},
                            "voice": config.OPENAI_VOICE,
                        },
                    },
                    "instructions": instructions,
                },
            }
        )
    )


async def twilio_to_openai(twilio_ws: WebSocket, openai_ws, state: dict):
    """Forward audio coming from the phone call into the model."""
    try:
        async for message in twilio_ws.iter_text():
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                state["stream_sid"] = data["start"]["streamSid"]
                log.info("twilio stream started sid=%s", state["stream_sid"])

            elif event == "media":
                state["latest_media_timestamp"] = int(data["media"]["timestamp"])
                await openai_ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": data["media"]["payload"],
                        }
                    )
                )

            elif event == "stop":
                log.info("twilio stream stopped")
                break

    except Exception:
        log.exception("twilio_to_openai loop ended")


async def openai_to_twilio(twilio_ws: WebSocket, openai_ws, state: dict):
    """Forward model audio back to the phone call, and truncate/clear
    playback if the other side starts talking while we're still speaking."""
    try:
        async for raw in openai_ws:
            event = json.loads(raw)
            etype = event.get("type")

            if etype in LOGGED_OPENAI_EVENTS:
                log.info("openai event: %s %s", etype, event.get("error", ""))

            if etype == "response.output_audio.delta" and event.get("delta"):
                await twilio_ws.send_json(
                    {
                        "event": "media",
                        "streamSid": state["stream_sid"],
                        "media": {"payload": event["delta"]},
                    }
                )

                if state["response_start_timestamp"] is None:
                    state["response_start_timestamp"] = state["latest_media_timestamp"]

                if event.get("item_id"):
                    state["last_assistant_item"] = event["item_id"]

                state["has_active_response_audio"] = True

            elif etype == "input_audio_buffer.speech_started":
                await handle_interruption(twilio_ws, openai_ws, state)

    except Exception:
        log.exception("openai_to_twilio loop ended")


async def handle_interruption(twilio_ws: WebSocket, openai_ws, state: dict):
    if not state["has_active_response_audio"] or state["response_start_timestamp"] is None:
        return

    elapsed_ms = max(state["latest_media_timestamp"] - state["response_start_timestamp"], 0)

    if state["last_assistant_item"]:
        await openai_ws.send(
            json.dumps(
                {
                    "type": "conversation.item.truncate",
                    "item_id": state["last_assistant_item"],
                    "content_index": 0,
                    "audio_end_ms": elapsed_ms,
                }
            )
        )

    await twilio_ws.send_json({"event": "clear", "streamSid": state["stream_sid"]})

    state["last_assistant_item"] = None
    state["response_start_timestamp"] = None
    state["has_active_response_audio"] = False


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
