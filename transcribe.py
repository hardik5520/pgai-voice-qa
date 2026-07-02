"""Downloads a call recording from Twilio, splits it into its two channels
(the call was recorded in dual channel mode, one channel per side of the
conversation), transcribes each channel separately, and merges both into a
single chronological, speaker labeled transcript.

Timestamps come from our own silence detection on each channel, not from
Whisper's own segment timestamps. Whisper drifts on long single-speaker
files, especially right after a stretch of silence, which misplaces lines in
a way that doesn't match the actual audio. Detecting speech bursts ourselves
first and transcribing each one in isolation avoids that.

Usage:
    python transcribe.py                  # transcribes the most recent call
    python transcribe.py <recording_sid>  # transcribes a specific call

Requires the ffmpeg binary on PATH (brew install ffmpeg if you don't have it).

Which physical channel is which speaker depends on how Twilio orders dual
channel recordings for a single, non-conferenced call leg. Channel labels
below are a starting guess, listen to the first transcript against the mp3
once and flip CHANNEL_LABELS if they're backwards.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from openai import OpenAI
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

import config

CALL_LOG_PATH = Path("calls/call_log.jsonl")

CHANNEL_LABELS = {
    0: "Clinic Agent",
    1: "Patient (Bot)",
}


def load_call_entry(recording_sid: str | None) -> dict:
    if not CALL_LOG_PATH.exists():
        sys.exit(f"no call log found at {CALL_LOG_PATH}, place a call first")

    entries = [json.loads(line) for line in CALL_LOG_PATH.read_text().splitlines() if line.strip()]
    if not entries:
        sys.exit("call log is empty, place a call first")

    if recording_sid is None:
        return entries[-1]

    for entry in reversed(entries):
        if entry["recording_sid"] == recording_sid:
            return entry

    sys.exit(f"recording_sid {recording_sid} not found in {CALL_LOG_PATH}")


def download_mp3(entry: dict, out_dir: Path) -> Path:
    """Downloads the raw two channel recording, one speaker per channel.
    Kept around for accurate per speaker transcription, not meant for
    playback, see mixdown_for_playback for the file you actually submit."""
    dual_path = out_dir / f"{entry['recording_sid']}_dual.mp3"
    resp = requests.get(
        f"{entry['recording_url']}.mp3",
        auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
    )
    resp.raise_for_status()
    dual_path.write_bytes(resp.content)
    return dual_path


def mixdown_for_playback(dual_path: Path, out_dir: Path, recording_sid: str) -> Path:
    """Combines both channels into one normal, always audible track. This is
    the file to actually submit, a raw two channel file can sound like it's
    missing a speaker on players or headphones that don't sum channels."""
    mixed_path = out_dir / f"{recording_sid}.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(dual_path),
            "-filter_complex", "[0:a]pan=mono|c0=0.5*c0+0.5*c1[out]",
            "-map", "[out]", str(mixed_path),
        ],
        check=True,
        capture_output=True,
    )
    return mixed_path


def split_channels(mp3_path: Path, out_dir: Path) -> dict[int, Path]:
    channel_paths = {
        0: out_dir / f"{mp3_path.stem}_channel0.wav",
        1: out_dir / f"{mp3_path.stem}_channel1.wav",
    }
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(mp3_path),
            "-filter_complex", "[0:a]channelsplit=channel_layout=stereo[left][right]",
            "-map", "[left]", str(channel_paths[0]),
            "-map", "[right]", str(channel_paths[1]),
        ],
        check=True,
        capture_output=True,
    )
    return channel_paths


MIN_BURST_MS = 300  # shorter than this is almost always a click, breath, or
                     # line noise, not a word, transcribing it invites the
                     # model to hallucinate text for it


def detect_speech_bursts(audio: AudioSegment) -> list[tuple[float, float]]:
    """Finds where each speaker actually starts and stops talking using
    silence detection, rather than relying on a transcription model's own
    notion of time over a long, mostly silent, single-speaker file."""
    silence_thresh = audio.dBFS - 16
    ranges_ms = detect_nonsilent(audio, min_silence_len=500, silence_thresh=silence_thresh)
    ranges_ms = [(start, end) for start, end in ranges_ms if end - start >= MIN_BURST_MS]
    return [(start_ms / 1000, end_ms / 1000) for start_ms, end_ms in ranges_ms]


TRANSCRIBE_TIMEOUT_SECONDS = 60  # a single burst is a few seconds of audio,
                                  # if a request takes anywhere near this
                                  # long something's wrong, fail fast instead
                                  # of hanging with no visibility


def transcribe_channel(client: OpenAI, path: Path, channel_label: str) -> list[dict]:
    audio = AudioSegment.from_file(path)
    bursts = detect_speech_bursts(audio)

    results = []
    for i, (start, end) in enumerate(bursts, start=1):
        print(f"  {channel_label}: burst {i}/{len(bursts)} ({start:.1f}s)...", flush=True)
        clip = audio[int(start * 1000):int(end * 1000)]
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            clip.export(tmp.name, format="wav")
            with open(tmp.name, "rb") as f:
                try:
                    transcription = client.audio.transcriptions.create(
                        model="gpt-4o-mini-transcribe",
                        file=f,
                        language="en",
                        timeout=TRANSCRIBE_TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    print(f"    skipped, request failed: {exc}")
                    continue
        text = transcription.text.strip()
        if text:
            results.append({"start": start, "text": text})
    return results


def format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def merge_transcript(channel_segments: dict[int, list[dict]]) -> str:
    lines = []
    for channel, segments in channel_segments.items():
        speaker = CHANNEL_LABELS[channel]
        for seg in segments:
            lines.append((seg["start"], f"[{format_timestamp(seg['start'])}] {speaker}: {seg['text']}"))
    lines.sort(key=lambda pair: pair[0])
    return "\n".join(text for _, text in lines)


def main():
    recording_sid = sys.argv[1] if len(sys.argv) > 1 else None
    entry = load_call_entry(recording_sid)

    out_dir = Path("calls") / entry["scenario"]
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"downloading recording {entry['recording_sid']} (scenario={entry['scenario']})...")
    dual_path = download_mp3(entry, out_dir)

    print("mixing down a playback copy...")
    mixed_path = mixdown_for_playback(dual_path, out_dir, entry["recording_sid"])

    print("splitting channels for transcription...")
    channel_paths = split_channels(dual_path, out_dir)

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    print("transcribing...")
    channel_segments = {
        channel: transcribe_channel(client, path, CHANNEL_LABELS[channel])
        for channel, path in channel_paths.items()
    }

    transcript = merge_transcript(channel_segments)
    transcript_path = out_dir / f"{entry['recording_sid']}.txt"
    transcript_path.write_text(transcript)

    for path in channel_paths.values():
        path.unlink()

    print(f"recording (submit this one): {mixed_path}")
    print(f"raw dual channel copy: {dual_path}")
    print(f"transcript: {transcript_path}")


if __name__ == "__main__":
    main()
