"""Video media extraction engine for the video investigation pipeline.

uploaded video → media inspection → adaptive frame extraction → audio
extraction/transcription → timestamped evidence. Everything runs through
ffprobe/ffmpeg subprocesses that are discovered generically (env override →
PATH → standard install locations), bounded by wall-clock timeouts, and the
result is cached per uploaded file so repeated analysis never re-decodes the
same video.

Never fabricates evidence: when a binary is missing, the file is corrupt, or
extraction fails, the limitation is recorded and the caller degrades to the
file-level metadata that IS available.
"""
import hashlib
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from .. import config

logger = logging.getLogger(__name__)


class VideoUnreadable(Exception):
    """The stored video could not be materialized for probing."""


class VideoCorrupt(Exception):
    """ffprobe ran but the file is not a readable video."""


class VideoUnsupported(Exception):
    """The file probes fine but contains no decodable video stream."""


# Generic install locations, not environment-specific: these are the standard
# ffmpeg layouts on Linux, macOS (homebrew) and Windows. Missing binaries are
# reported as a limitation, never as fabricated evidence.
_PROBE_EXTRA_DIRS = [
    "/usr/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
    str(Path(os.getenv("PROGRAMFILES", "C:\\Program Files")) / "ffmpeg" / "bin"),
    str(Path.home() / "ffmpeg" / "bin"),
    str(Path.home() / "scoop" / "apps" / "ffmpeg" / "current" / "bin"),
]


def _find_binary(env_name: str, name: str) -> str | None:
    """Locate an ff* binary: explicit env path → PATH → standard prefixes."""
    raw = os.getenv(env_name, "").strip()
    if raw:
        cand = Path(raw)
        if cand.is_file():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    exe = name + (".exe" if os.name == "nt" else "")
    for d in _PROBE_EXTRA_DIRS:
        cand = Path(d) / exe
        if cand.is_file():
            return str(cand)
    return None


_CLASS_LOCK = None
_FOUND = {}


def _locate(env_name: str, name: str) -> str | None:
    global _CLASS_LOCK
    if _CLASS_LOCK is None:
        import threading
        _CLASS_LOCK = threading.Lock()
    key = (env_name, name)
    with _CLASS_LOCK:
        if key not in _FOUND:
            _FOUND[key] = _find_binary(env_name, name)
        return _FOUND[key]


def _run(binary: str, args: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Bounded subprocess execution. No shell, captured output, hard timeout,
    and on Windows no console window is spawned."""
    # ponytail: subprocess.run with a timeout is enough; upgrade to Popen with
    # explicit kill on SIGTERM handling only if a timeout requires caring about
    # orphan ffmpeg children.
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    return subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )


# ── pure planning helpers (unit-testable without binaries) ────────────────

def plan_frames(duration: float, max_frames: int = None, min_interval: float = 1.0):
    """Adaptive sampling: short videos get dense 1s sampling, long videos stay
    even-and-sparse so the whole video is represented within max_frames."""
    max_frames = max(1, int(max_frames or config.VIDEO_MAX_FRAMES))
    duration = max(float(duration or 0), 0.0)
    if duration <= 0:
        return min_interval, 0
    interval = max(duration / max_frames, min_interval)
    count = min(int(duration // interval) + 1, max_frames)
    return interval, count


def _showinfo_timestamps(stderr: str) -> list[float]:
    """Parse ffmpeg -vf showinfo padding lines for 'pts_time:NNN.NNNN'."""
    times = []
    for line in stderr.splitlines():
        marker = "pts_time:"
        i = line.find(marker)
        if i < 0:
            continue
        frag = line[i + len(marker):].split(" ")[0].strip()
        try:
            times.append(float(frag))
        except ValueError:
            continue
    return times


# ── processor ─────────────────────────────────────────────────────────────

class VideoProcessor:
    def __init__(self):
        self.ffprobe = _locate("FFPROBE_PATH", "ffprobe")
        self.ffmpeg = _locate("FFMPEG_PATH", "ffmpeg")

    def is_available(self) -> bool:
        return self.ffprobe is not None and self.ffmpeg is not None

    def missing_tools(self) -> list[str]:
        missing = []
        if not self.ffprobe:
            missing.append("ffprobe")
        if not self.ffmpeg:
            missing.append("ffmpeg")
        return missing

    def inspect(self, source: str) -> dict:
        """One ffprobe pass for the metadata the rest of the pipeline reuses.
        Raises VideoCorrupt / VideoUnsupported on unreadable input."""
        if not self.ffprobe:
            raise VideoCorrupt(f"ffprobe unavailable: {', '.join(self.missing_tools())}")
        out = _run(self.ffprobe, [
            "-v", "error", "-show_format", "-show_streams",
            "-print_format", "json", source,
        ], config.VIDEO_FFPROBE_TIMEOUT)
        if out.returncode != 0:
            raise VideoCorrupt((out.stderr or out.stdout or "unreadable").strip()[:400])
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError as e:
            raise VideoCorrupt(f"ffprobe output was not JSON: {e}")

        streams = data.get("streams") or []
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        if not video_streams:
            raise VideoUnsupported("no decodable video stream present")

        fmt = data.get("format") or {}
        v = video_streams[0]
        a = audio_streams[0] if audio_streams else None

        def _num(v, k, default=None):
            try:
                return float(v[k])
            except (KeyError, TypeError, ValueError):
                return default

        def _fps(v, k):
            raw = v.get(k)
            if not raw or "/" not in str(raw):
                return None
            try:
                num, den = str(raw).split("/", 1)
                num, den = float(num), float(den)
                return round(num / den, 3) if den else None
            except ValueError:
                return None

        return {
            "formatName": fmt.get("format_name"),
            "sizeBytes": _num(fmt, "size") or None,
            "durationSeconds": _num(fmt, "duration") or _num(v, "duration") or 0.0,
            "nbStreams": len(streams),
            "video": {
                "codecName": v.get("codec_name"),
                "codecLongName": v.get("codec_long_name"),
                "profile": v.get("profile"),
                "pixFmt": v.get("pix_fmt"),
                "width": v.get("width"),
                "height": v.get("height"),
                "rFrameRate": _fps(v, "r_frame_rate"),
                "avgFrameRate": _fps(v, "avg_frame_rate"),
                "nbFrames": _num(v, "nb_frames") or None,
                "bitRate": _num(v, "bit_rate") or None,
            },
            "audio": (
                {
                    "codecName": a.get("codec_name"),
                    "channels": a.get("channels"),
                    "sampleRate": _num(a, "sample_rate"),
                    "bitDepth": a.get("bits_per_sample"),
                    "bitRate": _num(a, "bit_rate") or None,
                }
                if a else None
            ),
            "hasAudio": bool(a),
            "sourcePath": source,
        }

    def extract_frames(self, source: str, out_dir: str, max_frames: int = None,
                       duration: float | None = None, interval: float | None = None) -> list[dict]:
        """Extract evenly-spaced key visual frames as downscaled JPEGs — one
        quick ffmpeg seek per frame. Seeking before -i skips straight to each
        planned timestamp instead of decoding the whole movie, so hour-long
        videos cost ~N short decodes (bounded, N frames) rather than one long
        one. Returns [{index, timestamp, path}] ordered by time, or [] on
        failure (never a fabricated frame)."""
        if not self.ffmpeg:
            return []
        max_frames = max(1, int(max_frames or config.VIDEO_MAX_FRAMES))
        if duration is None:
            try:
                duration = self.inspect(source).get("durationSeconds") or 0.0
            except Exception:
                return []
        if interval is None:
            interval, _ = plan_frames(duration, max_frames)
        if duration <= 0:
            return []

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("frame_*.jpg"):
            old.unlink(missing_ok=True)

        frames = []
        max_index = min(int(duration // interval) + 1, max_frames)
        for i in range(max_index):
            planned = round(i * interval, 3)
            if planned >= duration:
                # no frame exists exactly at the duration boundary; skip it
                # instead of failing a pointless seek
                continue
            frame_path = out / f"frame_{i:04d}.jpg"
            try:
                res = _run(self.ffmpeg, [
                    "-v", "error", "-ss", str(planned), "-i", source,
                    "-frames:v", "1",
                    "-vf", f"scale='min(iw,{config.VIDEO_FRAME_MAX_WIDTH})':-2,showinfo",
                    "-q:v", "3", str(frame_path),
                ], config.VIDEO_FFMPEG_TIMEOUT)
            except subprocess.TimeoutExpired:
                # a hung seek is killed; skip that frame and continue
                logger.error("ffmpeg frame seek timed out at t=%ss for %s", planned, source)
                continue
            if res.returncode != 0:
                logger.error("ffmpeg frame seek failed at t=%ss (%s): %s",
                             planned, res.returncode, (res.stderr or "")[:300])
                continue
            if not frame_path.is_file() or frame_path.stat().st_size == 0:
                continue
            # prefer the exact pts of the frame we actually landed on;
            # fall back to the planned timestamp (keyframe seek drift).
            times = _showinfo_timestamps(res.stderr or "")
            ts = times[0] if times else planned
            frames.append({"index": i, "timestamp": float(ts), "path": str(frame_path)})
            if len(frames) >= max_frames:
                break
        return frames

    def extract_audio(self, source: str, out_wav: str, max_seconds: float | None = None) -> str | None:
        """16kHz mono PCM WAV for transcription. Returns the wav path or None
        on failure. max_seconds bounds the decoded window."""
        if not self.ffmpeg:
            return None
        args = ["-v", "error", "-i", source, "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1"]
        if max_seconds:
            args += ["-t", str(max_seconds)]
        args.append(out_wav)
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        try:
            res = _run(self.ffmpeg, args, config.VIDEO_FFMPEG_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg audio extraction timed out for %s", source)
            return None
        path = Path(out_wav)
        if res.returncode == 0 and path.is_file() and path.stat().st_size > 0:
            return out_wav
        return None

    def describe(self, inspection: dict, label: str = "") -> str:
        """Human finding from cached inspection — pure, reuses one probe."""
        v = inspection.get("video") or {}
        a = inspection.get("audio")
        lines = ["FILE_LEVEL_SIGNALS (observed, reproducible):"]
        d = inspection.get("durationSeconds")
        lines.append(
            f"- container/probe=ffprobe, format={inspection.get('formatName') or 'unknown'}, "
            f"size={inspection.get('sizeBytes') or 'unknown'} bytes, duration={d or 'unknown'}s"
        )
        dims = f"{v.get('width')}x{v.get('height')}" if v.get("width") and v.get("height") else "dimensions unknown"
        lines.append(
            f"- video stream: codec={v.get('codecName') or 'unknown'}, {dims}, "
            f"pix_fmt={v.get('pixFmt') or 'unknown'}, "
            f"avg_frame_rate={v.get('avgFrameRate') or 'unknown'}"
        )
        if a:
            lines.append(
                f"- audio stream: codec={a.get('codecName') or 'unknown'}, "
                f"channels={a.get('channels') or 'unknown'}, "
                f"sample_rate={a.get('sampleRate') or 'unknown'}"
            )
        else:
            lines.append("- audio stream: none detected")
        if label:
            lines.append(f"- source label: {label}")
        return "\n".join(lines)


# ── per-file cached extraction used by evidence_checks and the analyzer ────

def artifacts_dir(file_path: str) -> Path:
    digest = hashlib.sha1(file_path.encode("utf-8")).hexdigest()[:12]
    return config.STORAGE_PATH / "media-cache" / digest


def materialize_source(file_path: str) -> str:
    """Return a path on disk ffmpeg/ffprobe can read: the local uploaded file
    when it is already on disk (GridFS-backed deployments fall back to one
    materialized copy in the media cache)."""
    from ..libraries import storage
    from ..libraries import signals as signals_lib

    local = storage.resolve_stored_path(file_path)
    if local:
        return str(local)
    data = signals_lib.load_bytes(file_path)
    if not data:
        raise VideoUnreadable("stored file could not be read")
    d = artifacts_dir(file_path)
    d.mkdir(parents=True, exist_ok=True)
    ext = Path(file_path).suffix or ".mp4"
    target = d / f"source{ext}"
    if not target.is_file() or target.stat().st_size != len(data):
        target.write_bytes(data)
    return str(target)


def prepare_video(input_: dict) -> dict:
    """Materialize + inspect + extract frames/audio for one video input, and
    cache everything on the input record so repeated calls (and repeated runs
    of an investigation) never re-decode the video. Never fabricates output:
    failures are recorded as limitations with state != 'ok'."""
    cached = input_.get("mediaExtraction")
    if isinstance(cached, dict) and cached.get("prepared"):
        return cached

    extract = {"prepared": True, "state": "error", "inspection": None,
               "frames": [], "audio": None, "transcript": None,
               "transcriptWindowSeconds": None, "limitations": []}

    try:
        source = materialize_source(input_.get("filePath") or "")
    except Exception as e:
        extract["state"] = "unreadable"
        extract["limitations"].append(f"Video could not be read: {e}")
        input_["mediaExtraction"] = extract
        return extract

    file_path = input_.get("filePath") or ""
    processor = VideoProcessor()
    missing = processor.missing_tools()
    extract["sourcePath"] = source

    if missing:
        # No ffmpeg/ffprobe: degrade to a pure-stdlib container probe so the
        # user still gets real metadata, with an honest limitation. No frames,
        # no audio, no fabrication.
        extract["state"] = "ffmpeg_unavailable"
        extract["limitations"].append(
            f"ffmpeg/ffprobe are not installed on this server ({', '.join(missing)} missing); "
            "only container-level metadata could be extracted. Install ffmpeg to enable frame/audio analysis."
        )
        try:
            from ..libraries import signals as signals_lib
            data = Path(source).read_bytes()
            sig = signals_lib.inspect_bytes(data, "video", input_.get("mimeType"))
            desc = signals_lib.describe(data, "video", sig)
            if desc:
                extract["fallbackSignals"] = desc
        except Exception as e:
            extract["limitations"].append(f"Container metadata extraction failed: {e}")
        input_["mediaExtraction"] = extract
        return extract

    try:
        extract["inspection"] = processor.inspect(source)
    except VideoUnsupported as e:
        extract["state"] = "unsupported"
        extract["limitations"].append(str(e))
        input_["mediaExtraction"] = extract
        return extract
    except Exception as e:
        extract["state"] = "corrupt"
        extract["limitations"].append(f"Video could not be probed: {e}")
        input_["mediaExtraction"] = extract
        return extract

    extract["state"] = "ok"
    duration = extract["inspection"].get("durationSeconds") or 0.0
    if duration > config.VIDEO_MAX_DURATION_SECONDS:
        extract["state"] = "too_long"
        extract["limitations"].append(
            f"Video duration {duration:.0f}s exceeds the {config.VIDEO_MAX_DURATION_SECONDS:.0f}s "
            "processing bound; frames/audio were skipped. File-level metadata is still reported."
        )
    else:
        frames_dir = artifacts_dir(file_path) / "frames"
        extract["frames"] = processor.extract_frames(
            source, str(frames_dir), duration=duration)
        if not extract["frames"]:
            extract["limitations"].append(
                "Frame extraction produced no frames; visual evidence is unavailable (no fabricated frames)."
            )
        if extract["inspection"].get("hasAudio"):
            wav = str(artifacts_dir(file_path) / "audio.wav")
            max_seconds = max(1, config.AUDIO_TRANSCRIPT_WINDOW_SECONDS)
            extract["audio"] = processor.extract_audio(source, wav)
            extract["transcriptWindowSeconds"] = max_seconds if duration > max_seconds else duration
            if not extract["audio"]:
                extract["limitations"].append(
                    "Audio stream was detected but could not be extracted; transcription unavailable."
                )
        else:
            extract["audio"] = None
            extract["transcript"] = None

    input_["mediaExtraction"] = extract
    return extract


def frame_payload_bytes(frame: dict) -> bytes | None:
    """Read one cached frame for an AI call (bounded by extraction size)."""
    try:
        p = Path(frame.get("path") or "")
        if p.is_file() and p.stat().st_size > 0:
            return p.read_bytes()
    except OSError:
        return None
    return None


if __name__ == "__main__":  # self-check
    assert plan_frames(10, 16) == (1.0, 11)  # dense 1s sampling on a short clip
    interval, count = plan_frames(3600, 16)
    assert count == 16 and 220 <= interval <= 230, (interval, count)
    assert plan_frames(0, 16)[1] == 0
    assert _showinfo_timestamps("n:0 pts_time:0.000000 n:1") == [0.0]
    assert _showinfo_timestamps("n:0 pts_time:2.500000 x\nn:1 pts_time:7.000") == [2.5, 7.0]
    _lock_local_ok = _locate("FFPROBE_PATH", "ffprobe")  # warm the cache (may be None — fine)
    print("video_processor self-check OK")