"""Convert a Playwright WebM screen recording into a shareable MP4 copy.

This converter is intentionally separate from the browser-recording script: it
does not inspect the application or change a captured frame.  The bundled demo
recording has no audio track, so frame-by-frame conversion preserves all of its
content.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCAL_VIDEO_LIBRARIES = REPOSITORY_ROOT / ".tools" / "video"
if LOCAL_VIDEO_LIBRARIES.is_dir():
    sys.path.insert(0, str(LOCAL_VIDEO_LIBRARIES))

import cv2  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Source Playwright WebM file.")
    parser.add_argument("output", type=Path, help="Destination MP4 file.")
    parser.add_argument(
        "--trailing-hold-seconds",
        type=float,
        default=0,
        help="Repeat the final captured frame for this many seconds.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Recording was not found: {source}")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    if args.trailing_hold_seconds < 0:
        raise ValueError("--trailing-hold-seconds cannot be negative.")

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open the WebM recording.")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if fps <= 0 or width <= 0 or height <= 0:
            raise RuntimeError("The WebM recording did not expose valid video dimensions.")

        output.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(output),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise RuntimeError("OpenCV could not create the MP4 video writer.")
        try:
            frame_count = 0
            final_frame = None
            while True:
                read_ok, frame = capture.read()
                if not read_ok:
                    break
                writer.write(frame)
                frame_count += 1
                final_frame = frame
            trailing_frames = round(args.trailing_hold_seconds * fps)
            if final_frame is not None:
                for _ in range(trailing_frames):
                    writer.write(final_frame)
                    frame_count += 1
        finally:
            writer.release()
    finally:
        capture.release()

    if frame_count == 0:
        raise RuntimeError("No frames were converted; the partial MP4 should not be used.")
    print(f"Converted {frame_count} frames to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
