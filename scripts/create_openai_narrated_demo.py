"""Generate timestamped OpenAI narration and mux it into the live demo video.

Only the approved narration prose in ``docs/DEMO_SCRIPT.md`` is sent to the
OpenAI speech endpoint. The video, fictional licence, environment values,
account data, and database data remain local. Generated speech is placed in
the timestamped scenes declared in that script, then muxed with the existing
screen capture into a broadly compatible H.264/AAC MP4.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
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
SCENE_PATTERN = re.compile(r"^### (\d+:\d+)–(\d+:\d+) —")


@dataclass(frozen=True)
class NarrationScene:
    """One reviewed narration passage and its matching screen-recording window."""

    start_seconds: float
    end_seconds: float
    text: str

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


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


def parse_timestamp(value: str) -> float:
    minutes, seconds = value.split(":", 1)
    return float(int(minutes) * 60 + int(seconds))


def narration_scenes(script_path: Path) -> list[NarrationScene]:
    """Extract blockquote narration under the document's timestamp headings."""

    current_start: float | None = None
    current_end: float | None = None
    current_lines: list[str] = []
    scenes: list[NarrationScene] = []
    for line in script_path.read_text(encoding="utf-8").splitlines():
        heading = SCENE_PATTERN.match(line)
        if heading:
            if current_start is not None:
                scenes.append(
                    NarrationScene(current_start, current_end or 0, " ".join(current_lines))
                )
            current_start = parse_timestamp(heading.group(1))
            current_end = parse_timestamp(heading.group(2))
            current_lines = []
        elif current_start is not None and line.startswith("> "):
            current_lines.append(line[2:].strip())
    if current_start is not None:
        scenes.append(NarrationScene(current_start, current_end or 0, " ".join(current_lines)))

    if not scenes or any(not scene.text or scene.duration_seconds <= 0 for scene in scenes):
        raise RuntimeError("The narration script has an incomplete timestamped scene.")
    if scenes[0].start_seconds != 0 or any(
        left.end_seconds != right.start_seconds for left, right in zip(scenes, scenes[1:])
    ):
        raise RuntimeError("Narration scene windows must form one continuous timeline.")
    return scenes


def read_openai_api_key(dotenv_path: Path) -> str:
    """Read just the API key locally, without logging the ignored .env file."""

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


def speech_text(text: str) -> str:
    """Make technical names clear in speech without changing the reviewed script."""

    replacements = {
        "LicenceIQ": "Licence I Q",
        "Argon2": "Argon two",
        "JWT": "J W T",
        "MinIO": "Min I O",
        "pgvector": "P G vector",
        "Q-and-A": "questions and answers",
    }
    for written, spoken in replacements.items():
        text = text.replace(written, spoken)
    return text


def synthesize_scene(
    api_key: str, scene: NarrationScene, voice: str, destination: Path
) -> None:
    """Generate one WAV scene from the approved text and no application data."""

    payload = json.dumps(
        {
            "model": "gpt-4o-mini-tts",
            "voice": voice,
            "input": speech_text(scene.text),
            "instructions": (
                "Speak in clear, natural English for a calm, professional software "
                "demonstration. Keep technical terms distinct. Do not add words that "
                "are not in the supplied narration."
            ),
            "response_format": "wav",
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
        raise RuntimeError("OpenAI speech generation returned an unusably small WAV file.")
    destination.write_bytes(audio)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a local media operation without leaking environment variables."""

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
    """Read duration from FFmpeg's local media-inspection output."""

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
        raise RuntimeError("Could not determine a media duration.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3_600 + int(minutes) * 60 + float(seconds)


def atempo_chain(tempo: float) -> str:
    """Express an arbitrary tempo through FFmpeg's supported filter factors."""

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


def main() -> int:
    args = parse_args()
    recording = args.recording.resolve()
    script_path = args.script.resolve()
    output = args.output.resolve()
    if not recording.is_file():
        raise FileNotFoundError(f"Recording was not found: {recording}")
    if not script_path.is_file():
        raise FileNotFoundError(f"Narration script was not found: {script_path}")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")

    scenes = narration_scenes(script_path)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    video_duration = duration_seconds(ffmpeg, recording)
    if abs(scenes[-1].end_seconds - video_duration) > 1.0:
        raise RuntimeError("The narration timeline does not match the source recording duration.")

    work_dir = output.with_name("openai-narration-work")
    if work_dir.exists():
        raise FileExistsError("Narration work directory already exists; choose a new output name.")
    work_dir.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    key = read_openai_api_key(REPOSITORY_ROOT / ".env")
    timed_segments: list[Path] = []
    try:
        for index, scene in enumerate(scenes, start=1):
            raw_audio = work_dir / f"scene-{index:02}-raw.wav"
            timed_audio = work_dir / f"scene-{index:02}-timed.wav"
            synthesize_scene(key, scene, args.voice, raw_audio)
            raw_duration = duration_seconds(ffmpeg, raw_audio)
            # Keep naturally short scenes natural, leaving quiet review time on
            # screen. Only speed up speech when it would overrun its scene.
            tempo = max(raw_duration / scene.duration_seconds, 1.0)
            run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(raw_audio),
                    "-filter:a",
                    f"{atempo_chain(tempo)},apad=whole_dur={scene.duration_seconds:.3f}",
                    "-t",
                    f"{scene.duration_seconds:.3f}",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-c:a",
                    "pcm_s16le",
                    str(timed_audio),
                ]
            )
            timed_segments.append(timed_audio)
    finally:
        # Do not retain the secret in process state after all TTS calls complete.
        del key

    concat_list = work_dir / "scenes.txt"
    concat_list.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in timed_segments), encoding="ascii"
    )
    master_audio = work_dir / "LicenceIQ-Narration-Master.m4a"
    run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(master_audio),
        ]
    )
    run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(recording),
            "-i",
            str(master_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-fps_mode",
            "passthrough",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-t",
            f"{video_duration:.3f}",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    run([ffmpeg, "-v", "error", "-i", str(output), "-f", "null", "-"])
    print(f"Created narrated video: {output}")
    print(f"Duration: {video_duration:.1f} seconds; narration scenes: {len(scenes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
