"""Create a narrated assessment-video copy from the live LicenceIQ recording.

The script sends only the prepared product narration to OpenAI's speech API.
It never uploads the screen recording, a licence image, an API key, a token, or
database data.  It then uses a workspace-local FFmpeg binary to add the audio
track to the already-recorded MP4 without changing its video stream.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCAL_MEDIA = REPOSITORY_ROOT / ".tools" / "media"
if LOCAL_MEDIA.is_dir():
    sys.path.insert(0, str(LOCAL_MEDIA))

import imageio_ffmpeg  # noqa: E402


DEFAULT_RECORDING = (
    REPOSITORY_ROOT
    / "artifacts"
    / "recordings"
    / "live-demo-20260920T095515Z"
    / "LicenceIQ-Live-Demo-5m13.mp4"
)
DEFAULT_SCRIPT = REPOSITORY_ROOT / "docs" / "DEMO_SCRIPT.md"
TTS_URL = "https://api.openai.com/v1/audio/speech"
DURATION_PATTERN = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, default=DEFAULT_RECORDING)
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RECORDING.with_name("LicenceIQ-Live-Demo-Narrated.mp4"),
    )
    parser.add_argument("--voice", default="marin")
    return parser.parse_args()


def read_openai_api_key(dotenv_path: Path) -> str:
    """Read only OPENAI_API_KEY from the ignored local environment file."""

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "OPENAI_API_KEY":
            secret = value.strip().strip('"').strip("'")
            if secret:
                return secret
    raise RuntimeError("OPENAI_API_KEY is not configured in the local .env file.")


def narration_from_markdown(script_path: Path) -> str:
    """Extract only the approved spoken lines from the checked-in demo script."""

    spoken_lines = [
        line[2:].strip()
        for line in script_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("> ")
    ]
    narration = "\n\n".join(spoken_lines).strip()
    if not narration:
        raise RuntimeError("No spoken narration was found in the demo script.")
    if len(narration) > 4_096:
        raise RuntimeError("The narration exceeds the OpenAI speech input limit.")
    return narration


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a local media command without exposing its environment or secrets."""

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError("A local media-processing command failed.")
    return completed


def duration_seconds(ffmpeg: str, media_path: Path) -> float:
    """Read a media duration from FFmpeg's local inspection output."""

    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(media_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = DURATION_PATTERN.search(result.stderr)
    if not match:
        raise RuntimeError("Could not determine the media duration.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3_600 + int(minutes) * 60 + float(seconds)


def atempo_chain(tempo: float) -> str:
    """Return FFmpeg tempo filters while respecting the supported factor range."""

    if tempo <= 0:
        raise ValueError("Audio tempo must be positive.")
    factors: list[float] = []
    while tempo < 0.5:
        factors.append(0.5)
        tempo /= 0.5
    while tempo > 2.0:
        factors.append(2.0)
        tempo /= 2.0
    factors.append(tempo)
    return ",".join(f"atempo={factor:.6f}" for factor in factors)


def synthesize_speech(api_key: str, narration: str, voice: str, destination: Path) -> None:
    """Create narration audio from product prose only; never print API output."""

    payload = json.dumps(
        {
            "model": "gpt-4o-mini-tts",
            "voice": voice,
            "input": narration,
            "instructions": (
                "Speak in clear, natural English for a calm software engineering demo. "
                "Use a warm, confident, professional tone. Keep technical terms distinct."
            ),
            "response_format": "mp3",
            "speed": 1.0,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TTS_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            audio = response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"OpenAI speech generation failed with HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        raise RuntimeError("OpenAI speech generation could not reach the service.") from error
    if len(audio) < 1_000:
        raise RuntimeError("OpenAI speech generation returned an unusably small audio file.")
    destination.write_bytes(audio)


def main() -> int:
    args = parse_args()
    recording = args.recording.resolve()
    script = args.script.resolve()
    output = args.output.resolve()
    if not recording.is_file():
        raise FileNotFoundError(f"Recording was not found: {recording}")
    if not script.is_file():
        raise FileNotFoundError(f"Narration script was not found: {script}")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    narration_mp3 = output.with_name("LicenceIQ-Live-Demo-Narration.mp3")
    normalized_audio = output.with_name("LicenceIQ-Live-Demo-Narration.m4a")
    if narration_mp3.exists() or normalized_audio.exists():
        raise FileExistsError("Narration outputs already exist; choose a new output name.")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    narration = narration_from_markdown(script)
    api_key = read_openai_api_key(REPOSITORY_ROOT / ".env")
    try:
        synthesize_speech(api_key, narration, args.voice, narration_mp3)
    finally:
        # The value should not persist beyond this process or appear in tracebacks.
        del api_key

    video_duration = duration_seconds(ffmpeg, recording)
    source_audio_duration = duration_seconds(ffmpeg, narration_mp3)
    # Leave a short quiet beat on the real successful sign-out screen.
    target_audio_duration = max(video_duration - 6.0, 1.0)
    tempo = source_audio_duration / target_audio_duration
    run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(narration_mp3),
            "-filter:a",
            atempo_chain(tempo),
            "-ar",
            "48000",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(normalized_audio),
        ]
    )
    run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(recording),
            "-i",
            str(normalized_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    # Decode both streams as a local final-file integrity check.
    run([ffmpeg, "-v", "error", "-i", str(output), "-f", "null", "-"])
    print(f"Created narrated video: {output}")
    print(f"Video duration: {video_duration:.1f} seconds")
    print(f"Narration duration: {source_audio_duration:.1f} seconds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
