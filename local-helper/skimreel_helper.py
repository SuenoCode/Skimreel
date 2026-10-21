"""Download a YouTube video locally and send it to the SkimReel API.

Desktop imports use anonymous YouTube access. The standalone helper retains
its optional Firefox-cookie workflow for users who run it directly.
"""

from __future__ import annotations

import argparse
import configparser
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests


DEFAULT_API = "https://skimreel-backend.onrender.com"
DEFAULT_FRONTEND = "https://skimreel.vercel.app"


def firefox_profile() -> str | None:
    """Return the actual Firefox profile directory name for the default profile."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    ini_path = Path(appdata) / "Mozilla" / "Firefox" / "profiles.ini"
    if not ini_path.exists():
        return None

    parser = configparser.RawConfigParser()
    parser.read(ini_path, encoding="utf-8")

    # Modern Firefox records the active profile under an [Install...] section.
    # Prefer that path over ProfileN's Default=1 flag, which can identify an
    # older profile kept for compatibility.
    for section in parser.sections():
        if not section.lower().startswith("install"):
            continue
        path = parser.get(section, "Default", fallback="").strip()
        if not path:
            continue
        profile_path = (
            (ini_path.parent / path) if not os.path.isabs(path) else Path(path)
        ).resolve()
        if profile_path.is_dir():
            return profile_path.name

    candidates: list[tuple[bool, str]] = []
    for section in parser.sections():
        if not section.lower().startswith("profile"):
            continue
        path = parser.get(section, "Path", fallback="").strip()
        if not path:
            continue
        is_relative = parser.getint(section, "IsRelative", fallback=1) == 1
        profile_path = (
            (ini_path.parent / path) if is_relative else Path(path)
        ).resolve()
        if profile_path.is_dir():
            candidates.append((parser.getint(section, "Default", fallback=0) == 1, profile_path.name))

    if not candidates:
        return None
    defaults = [name for is_default, name in candidates if is_default]
    return defaults[0] if defaults else candidates[0][1]


def download_source_with_binary(
    url: str,
    workdir: Path,
    ytdlp_executable: Path,
    deno: Path,
    quality: str,
) -> Path:
    command = [
        str(ytdlp_executable),
        "--no-warnings",
        "--no-colors",
        "--newline",
        "--no-playlist",
        "--no-simulate",
        "--format", f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best",
        "--merge-output-format", "mp4",
        "--output", str(workdir / "%(id)s.%(ext)s"),
        "--js-runtimes", f"deno:{deno}",
        "--progress-template", "download:Downloading locally: %(progress._percent_str)s",
        "--print", "after_move:SKIMREEL_FINAL_PATH:%(filepath)s",
        "--retries", "3",
        url,
    ]
    print("Downloading from YouTube without browser cookies.", flush=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    final_path: Path | None = None
    output_tail: list[str] = []
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip("\r\n")
        if line.startswith("SKIMREEL_FINAL_PATH:"):
            final_path = Path(line.removeprefix("SKIMREEL_FINAL_PATH:"))
        else:
            print(line, flush=True)
            output_tail.append(line)
            output_tail = output_tail[-30:]
    return_code = process.wait()
    if return_code:
        details = "\n".join(output_tail).strip()
        raise RuntimeError(details or f"yt-dlp exited with code {return_code}")
    if final_path is None or not final_path.is_file():
        raise RuntimeError("yt-dlp completed but no downloaded video file was found")
    return final_path


def download_source(
    url: str,
    workdir: Path,
    profile: str | None,
    ytdlp_executable: Path | None = None,
    deno_path: Path | None = None,
    quality: str = "720",
) -> Path:
    deno = shutil.which("deno")
    if deno_path and deno_path.is_file():
        deno = str(deno_path)
    if not deno:
        raise RuntimeError(
            "Deno was not found. Install it with: winget install --id DenoLand.Deno -e"
        )

    if ytdlp_executable:
        if not ytdlp_executable.is_file():
            raise RuntimeError(f"The bundled yt-dlp executable was not found: {ytdlp_executable}")
        return download_source_with_binary(url, workdir, ytdlp_executable, Path(deno), quality)

    # Keep the standalone local-helper workflow compatible with the same
    # yt-dlp Python API it has always used. The desktop app passes the current
    # official yt-dlp executable above and never imports this older module.
    import yt_dlp

    browser = ("firefox", profile) if profile else ("firefox",)
    last_reported = [-10]

    def progress_hook(status: dict) -> None:
        if status.get("status") != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        downloaded = status.get("downloaded_bytes") or 0
        if total:
            pct = int(downloaded * 100 / total)
            if pct >= last_reported[0] + 10:
                last_reported[0] = pct
                print(f"Downloading locally: {pct}%")

    opts = {
        "cookiesfrombrowser": browser,
        "js_runtimes": {"deno": {"path": deno}},
        "format": f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "progress_hooks": [progress_hook],
        "retries": 3,
    }

    print(f"Using Firefox profile: {profile or 'auto'}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info.get("id", "")

    files = [
        p for p in workdir.iterdir()
        if p.is_file()
        and video_id in p.name
        and not p.name.endswith((".part", ".ytdl"))
    ]
    if not files:
        raise RuntimeError("yt-dlp completed but no downloaded video file was found")
    return max(files, key=lambda p: p.stat().st_size)


def upload_and_wait(api: str, video: Path, args: argparse.Namespace) -> str:
    api = api.rstrip("/")
    print(f"Uploading {video.name} ({video.stat().st_size / 1024 / 1024:.1f} MB) to {api}")
    with video.open("rb") as fh:
        response = requests.post(
            f"{api}/api/analyze",
            files={"file": (video.name, fh, "video/mp4")},
            data={
                "length": str(args.length),
                "count": str(args.count),
                "quality": args.quality,
            },
            timeout=1800,
        )
    if not response.ok:
        # requests' default HTTPError only reports the status and URL. Include
        # the API/proxy response body and request identifier so gateway errors
        # can be distinguished from errors returned by the SkimReel app.
        detail = response.text.strip()
        if len(detail) > 1200:
            detail = detail[:1200] + "…"
        request_id = (
            response.headers.get("cf-ray")
            or response.headers.get("x-request-id")
            or response.headers.get("fly-request-id")
        )
        message = f"SkimReel API returned HTTP {response.status_code} {response.reason}."
        if detail:
            message += f" Response: {detail}"
        if request_id:
            message += f" Request ID: {request_id}"
        raise RuntimeError(message)
    job = response.json()["job"]
    print(f"Analysis job: {job}")
    if args.desktop_handoff:
        print(f"DESKTOP_JOB_ID:{job}", flush=True)
        return job
    result_url = (
        f"{args.frontend.rstrip('/')}/?"
        + urllib.parse.urlencode({"job": job, "source": args.source})
    )
    print(f"Opening results page: {result_url}")
    webbrowser.open(result_url)

    while True:
        status_response = requests.get(f"{api}/api/job/{job}", timeout=30)
        status_response.raise_for_status()
        status = status_response.json()
        detail = status.get("detail") or ""
        print(
            f"{status.get('pct', 0):>3}% {status.get('status', 'Working')}"
            + (f" — {detail}" if detail else "")
        )
        if status.get("done"):
            if status.get("error"):
                raise RuntimeError(status["error"])
            print("Analysis complete. Open SkimReel in your browser to view the result.")
            return job
        time.sleep(3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--api", default=DEFAULT_API, help="SkimReel backend URL")
    parser.add_argument("--frontend", default=DEFAULT_FRONTEND, help="SkimReel frontend URL")
    parser.add_argument("--length", type=float, default=30.0)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--quality", choices=("360", "480", "720", "1080"), default="720")
    parser.add_argument("--profile", help="Firefox profile folder; auto-detected by default")
    parser.add_argument(
        "--yt-dlp-executable",
        dest="ytdlp_executable",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--deno-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--desktop-handoff", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--keep", action="store_true", help="Keep the downloaded local video")
    args = parser.parse_args()
    args.source = args.url

    workdir = Path(tempfile.mkdtemp(prefix="skimreel-helper-"))
    try:
        # The packaged desktop passes the official yt-dlp binary and does not
        # need Firefox or a signed-in profile. Keep profile support for the
        # standalone Python helper.
        profile = None if args.ytdlp_executable else (args.profile or firefox_profile())
        video = download_source(
            args.url,
            workdir,
            profile,
            args.ytdlp_executable,
            args.deno_path,
            args.quality,
        )
        upload_and_wait(args.api, video, args)
        if args.keep:
            target = Path.cwd() / video.name
            shutil.copy2(video, target)
            print(f"Saved local copy: {target}")
        return 0
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
