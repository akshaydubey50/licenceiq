"""Record a real, repeatable LicenceIQ walkthrough with Playwright.

The recording stays inside the local app and uses the fictional sample bundled
with this repository.  It deliberately exercises the reviewer-visible flow:
guest access, account creation and sign-in, upload and OCR, source evidence,
review edits, grounded document questions, and sign-out.

Playwright records WebM video natively.  Run from the repository root:

    python scripts/record_live_demo.py

The script uses the workspace-local Playwright installation at
``.tools/playwright`` when it is available.  It never reads or prints an API
key, session token, document value, username, or password.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Final


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
LOCAL_PLAYWRIGHT: Final = REPOSITORY_ROOT / ".tools" / "playwright"
if LOCAL_PLAYWRIGHT.is_dir():
    sys.path.insert(0, str(LOCAL_PLAYWRIGHT))

from playwright.sync_api import Locator, Page, expect, sync_playwright  # noqa: E402


DEFAULT_BASE_URL: Final = "http://127.0.0.1:3000"
DEFAULT_SAMPLE: Final = REPOSITORY_ROOT / "samples" / "fictional_maharashtra_licence.png"
VIDEO_SIZE: Final = {"width": 1600, "height": 900}
OCR_TIMEOUT_MS: Final = 300_000
QUESTION_TIMEOUT_MS: Final = 75_000


def parse_args() -> argparse.Namespace:
    """Read small, safe recording controls without accepting credentials."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / "artifacts" / "recordings",
        help="Parent directory for the recorded WebM file.",
    )
    parser.add_argument(
        "--minimum-duration-seconds",
        type=int,
        default=300,
        help="Keep the completed, signed-out screen visible until this duration.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser while also recording it.",
    )
    return parser.parse_args()


def edge_executable() -> str:
    """Use the locally installed Edge browser without downloading a browser."""

    configured = os.environ.get("PLAYWRIGHT_BROWSER_EXECUTABLE")
    candidates = [
        Path(configured) if configured else None,
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return str(candidate)
    raise RuntimeError(
        "Microsoft Edge was not found. Set PLAYWRIGHT_BROWSER_EXECUTABLE to a Chromium browser executable."
    )


def pause(page: Page, milliseconds: int) -> None:
    """Hold a meaningful application state long enough for a human viewer."""

    page.wait_for_timeout(milliseconds)


def bring_into_view(page: Page, locator: Locator, hold_ms: int = 0) -> None:
    """Make the active UI scene readable in the captured video."""

    locator.scroll_into_view_if_needed()
    locator.wait_for(state="visible")
    if hold_ms:
        pause(page, hold_ms)


def clear_source_focus(page: Page) -> None:
    """Return the preview to its normal state after a source-evidence scene."""

    clear_button = page.get_by_role("button", name="Clear source focus")
    if clear_button.is_visible():
        clear_button.click()
        pause(page, 4_000)


def show_source_evidence(page: Page, source_button: Locator) -> None:
    """Open the source panel and verify that the preview is source focused."""

    bring_into_view(page, source_button)
    source_button.click()
    evidence = page.get_by_role("heading", name="Source evidence")
    bring_into_view(page, evidence, hold_ms=10_000)
    expect(
        page.get_by_role("region", name="Document preview focused on source page 1")
    ).to_be_visible()


def accept_next_dialog(page: Page) -> None:
    """Accept the intentional guest-workspace exit confirmation."""

    page.once("dialog", lambda dialog: dialog.accept())


def sign_up_and_sign_in(page: Page, base_url: str) -> None:
    """Demonstrate registration, logout, redirect, and fresh sign-in."""

    page.get_by_role("link", name="Sign up").click()
    expect(page.get_by_role("heading", name="Create your account")).to_be_visible()
    pause(page, 6_000)

    # A fresh local demo account keeps every recording independent without
    # exposing an existing account or any real credential.
    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    username = f"licenceiqdemo{suffix}"
    password = "DemoPass7"
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_label("Confirm password").fill(password)
    pause(page, 3_000)
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_label("Signed-in session")).to_be_visible(timeout=20_000)
    bring_into_view(page, page.get_by_label("Signed-in session"), hold_ms=8_000)

    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_text("You have signed out safely.")).to_be_visible(timeout=20_000)
    pause(page, 7_000)

    # Keep the redirect itself visible before using the normal sign-in form.
    expect(page.get_by_role("heading", name="Welcome back")).to_be_visible()
    pause(page, 6_000)
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_label("Signed-in session")).to_be_visible(timeout=20_000)
    bring_into_view(page, page.get_by_label("Signed-in session"), hold_ms=6_000)

    # The value is intentionally used only in page memory.  Make it clear to
    # static analysers and reviewers that it is not retained or reported.
    del username, password, base_url


def upload_and_read(page: Page, sample: Path) -> None:
    """Upload the fictional licence and wait for the live reading result."""

    file_input = page.locator("#document-file")
    bring_into_view(page, file_input)
    file_input.set_input_files(str(sample))
    expect(page.get_by_text(sample.name)).to_be_visible()
    pause(page, 6_000)

    page.get_by_role("button", name="Upload document").click()
    preview = page.get_by_alt_text(f"Preview of {sample.name}")
    bring_into_view(page, preview, hold_ms=8_000)

    page.get_by_role("button", name="Read document").click()
    full_name = page.get_by_label("Full name")
    full_name.wait_for(state="visible", timeout=OCR_TIMEOUT_MS)
    bring_into_view(page, full_name, hold_ms=12_000)


def review_and_save(page: Page) -> None:
    """Trace a field to evidence, then make and save a harmless format review."""

    source_button = page.locator("#full_name-source button").first
    expect(source_button).to_be_visible()
    show_source_evidence(page, source_button)
    clear_source_focus(page)

    full_name = page.get_by_label("Full name")
    bring_into_view(page, full_name, hold_ms=6_000)
    original = full_name.input_value()
    if not original:
        raise RuntimeError("The demo document did not provide a full name to review.")
    normalized = original.title()
    if normalized == original:
        normalized = original.upper()
    full_name.fill(normalized)
    save_status = page.locator("section.details-panel .review-actions .save-state")
    expect(save_status).to_have_text("Unsaved changes")
    pause(page, 8_000)

    page.get_by_role("button", name="Save changes").click()
    expect(save_status).to_have_text("All changes saved", timeout=20_000)
    pause(page, 8_000)


def ask_question(page: Page, question: str) -> Locator:
    """Ask one grounded question and return its visible response card."""

    answers = page.locator("ol.chat-transcript .chat-answer")
    answer_count = answers.count()
    question_box = page.get_by_label("Your question")
    bring_into_view(page, question_box, hold_ms=5_000)
    question_box.fill(question)
    page.get_by_role("button", name="Ask", exact=True).click()
    expect(answers).to_have_count(answer_count + 1, timeout=QUESTION_TIMEOUT_MS)
    answer = answers.nth(answer_count)
    bring_into_view(page, answer, hold_ms=10_000)
    return answer


def show_question_paths(page: Page) -> None:
    """Demonstrate direct, broader retrieval, and an honest unavailable answer."""

    direct_answer = ask_question(page, "What is the driving licence number?")
    expect(direct_answer).not_to_have_class("chat-answer-unavailable")
    direct_source = direct_answer.get_by_role(
        "button", name="View source on page 1"
    )
    expect(direct_source).to_be_visible()
    show_source_evidence(page, direct_source)
    clear_source_focus(page)

    broader_answer = ask_question(
        page,
        "What vehicles is this person authorised to drive, and what restrictions apply?",
    )
    expect(broader_answer).not_to_have_class("chat-answer-unavailable")
    broader_source = broader_answer.get_by_role(
        "button", name="View source on page 1"
    )
    expect(broader_source).to_be_visible()
    show_source_evidence(page, broader_source)
    clear_source_focus(page)

    unavailable_answer = ask_question(page, "What is the holder's passport number?")
    expect(unavailable_answer).to_contain_text("I couldn't find that in this document.")
    expect(
        unavailable_answer.get_by_role("button", name="View source on page 1")
    ).to_have_count(0)
    pause(page, 8_000)


def demonstrate_guest(page: Page) -> None:
    """Show the temporary guest path without duplicating a live OCR request."""

    guest_button = page.get_by_role("button", name="Continue as guest")
    expect(guest_button).to_be_visible()
    pause(page, 8_000)
    guest_button.click()
    expect(page.get_by_label("Guest session")).to_be_visible()
    bring_into_view(page, page.get_by_label("Guest session"), hold_ms=7_000)
    accept_next_dialog(page)
    page.get_by_role("button", name="Leave guest workspace").click()
    expect(page.get_by_role("button", name="Continue as guest")).to_be_visible()
    pause(page, 4_000)


def sign_out_for_final_scene(page: Page) -> None:
    """End with the real session-revocation and redirect behavior."""

    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_text("You have signed out safely.")).to_be_visible(timeout=20_000)
    pause(page, 8_000)


def main() -> int:
    args = parse_args()
    sample = args.sample.resolve()
    if not sample.is_file():
        raise FileNotFoundError(f"The fictional sample was not found: {sample}")
    if args.minimum_duration_seconds < 0:
        raise ValueError("--minimum-duration-seconds cannot be negative.")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    recording_dir = args.output_dir.resolve() / f"live-demo-{timestamp}"
    recording_dir.mkdir(parents=True, exist_ok=False)
    recording_started_at = time.monotonic()
    video_path: Path | None = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=edge_executable(),
            headless=not args.headed,
            slow_mo=120,
        )
        context = browser.new_context(
            viewport=VIDEO_SIZE,
            record_video_dir=str(recording_dir),
            record_video_size=VIDEO_SIZE,
            color_scheme="light",
            reduced_motion="reduce",
        )
        page = context.new_page()
        page.set_default_timeout(20_000)
        try:
            page.goto(args.base_url, wait_until="domcontentloaded")
            demonstrate_guest(page)
            sign_up_and_sign_in(page, args.base_url)
            upload_and_read(page, sample)
            review_and_save(page)
            show_question_paths(page)
            sign_out_for_final_scene(page)

            remaining_ms = max(
                0,
                args.minimum_duration_seconds * 1_000
                - int((time.monotonic() - recording_started_at) * 1_000),
            )
            if remaining_ms:
                pause(page, remaining_ms)
        finally:
            # Video files become readable only after the page and context close.
            video_path = Path(page.video.path())
            context.close()
            browser.close()

    assert video_path is not None
    duration = int(time.monotonic() - recording_started_at)
    print(f"Recorded live demo: {video_path}")
    print(f"Recorded duration: {duration} seconds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
