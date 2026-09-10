"""Observable file-level signal extraction for defensible forensics.

Extracts only reproducible facts an examiner could verify: container fields,
metadata tags, and codec/duration values where the format exposes them. When a
deep probe is impossible (e.g. no ffmpeg for video), the limitation is reported
instead of a fabricated signal.

ponytail: pure stdlib + Pillow; images get full metadata/EXIF, video/audio get
container-level parsing only. Add ffprobe/mediainfo probes later if deep
encoding analysis becomes a requirement.
"""
import io
import struct

IMAGE_KINDS = {"image", "jpeg", "png", "gif", "webp", "bmp", "tiff"}
VIDEO_KINDS = {"video", "mp4", "mov", "webm", "mkv", "avi"}
AUDIO_KINDS = {"audio", "wav", "mp3", "flac", "ogg", "m4a", "aac"}


def load_bytes(file_path: str) -> bytes | None:
    from .. import db
    from ..libraries import storage

    stored = db.read_upload_file(file_path)
    if stored and stored[0]:
        return stored[0]
    p = storage.resolve_stored_path(file_path)
    if p:
        try:
            return p.read_bytes()
        except OSError:
            return None
    return None


def _probe_image(buf: bytes) -> dict:
    from PIL import Image
    from PIL.ExifTags import Base as EBase

    s = {}
    try:
        with Image.open(io.BytesIO(buf)) as img:
            s["format"] = (img.format or "UNKNOWN").upper()
            s["width"] = img.width
            s["height"] = img.height
            s["mode"] = img.mode
            try:
                s["animated"] = bool(img.is_animated)
                s["frames"] = img.n_frames
            except Exception:
                pass
            if s["format"] == "PNG":
                txt = getattr(img, "text", None)
                if isinstance(txt, dict):
                    for k in ("Software", "Creation Time", "Source", "Comment"):
                        if k in txt:
                            s["png_" + k.replace(" ", "_").lower()] = str(txt[k])[:200]
            exif = img.getexif()
            if exif:
                s["exifPresent"] = True
                ex = {}
                for k in (
                    EBase.Make, EBase.Model, EBase.Software,
                    EBase.DateTimeOriginal, EBase.Artist, EBase.Orientation,
                ):
                    try:
                        v = exif.get(k)
                        if v not in (None, ""):
                            ex[EBase(k).name] = str(v)
                    except Exception:
                        pass
                if ex:
                    s["exif"] = ex
            else:
                s["exifPresent"] = False
            s["jfif"] = b"JFIF" in buf[:1024] if s["format"] == "JPEG" else False
    except Exception as e:  # pragma: no cover - defensive
        s["error"] = str(e)[:200]
    return s


def _iso_boxes(buf: bytes, tags: set, depth: int = 3):
    """Yield (tag, payload_offset, payload_len, version_byte) for boxes whose
    type is in tags, digging into container boxes (moov/trak/...) up to depth.
    Reads the whole file (uploads are tiny) so moov-at-tail MP4s still resolve."""
    found = []
    pos = 0
    n = len(buf)
    restrict = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta"}
    while pos + 8 <= n and len(found) < 64:
        box_size = struct.unpack(">I", buf[pos:pos + 4])[0]
        box_type = buf[pos + 4:pos + 8]
        header = 8
        if box_size == 1:
            if pos + 16 > n:
                break
            box_size = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
            header = 16
        elif box_size == 0:
            box_size = n - pos
        if box_size < header:
            break
        body = pos + header
        if box_type in tags:
            ver = buf[body] if body < n else 0
            found.append((box_type, body, min(box_size - header, n - body), ver))
        elif box_type in restrict and depth > 0:
            outer = body
            found.extend(
                (t, outer + o, l, v)
                for (t, o, l, v) in _iso_boxes(buf[body:body + box_size - header], tags, depth - 1)
            )
        pos += box_size
        if pos <= 0 or box_size > 40 * 1024 * 1024:
            break
    return found


def _read_u32(buf, off):
    return struct.unpack(">I", buf[off:off + 4])[0] if off + 4 <= len(buf) else None


def _probe_video(buf: bytes) -> dict:
    s = {}
    if buf[:4] == b"\x00\x00\x00\x18ftyp" or buf[4:8] == b"ftyp":
        s["container"] = "ISO-BMFF (MP4/MOV)"
        tags = {b"ftyp", b"mvhd", b"tkhd"}
        for tag, body, ln, ver in _iso_boxes(buf, tags):
            payload = buf[body:body + ln]
            if tag == b"ftyp" and len(payload) >= 8:
                s.setdefault("brands", []).append(payload[:4].decode("latin-1", "replace"))
                comp = payload[8:8 + max(0, (len(payload) - 8) // 4 * 4)]
                s.setdefault("compatibleBrands", []).extend(
                    comp[i:i + 4].decode("latin-1", "replace") for i in range(0, len(comp), 4))
            elif tag == b"mvhd" and len(payload) >= (40 if ver == 1 else 20) and "duration" not in s:
                if ver == 1:
                    ts = _read_u32(payload, 20)
                    if len(payload) >= 32 and ts:
                        d = struct.unpack(">Q", payload[24:32])[0]
                        s["durationSeconds"] = round(d / ts, 3)
                        s["timeScale"] = ts
                else:
                    ts = _read_u32(payload, 12)
                    d = _read_u32(payload, 16)
                    if ts and d:
                        s["durationSeconds"] = round(d / ts, 3)
                        s["timeScale"] = ts
            elif tag == b"tkhd" and len(payload) >= (92 if ver == 1 else 84) and "width" not in s:
                woff = 88 if ver == 1 else 76
                w = _read_u32(payload, woff)
                h = _read_u32(payload, woff + 4)
                if w and h:
                    s["trackWidth"] = round(w / 65536, 2)
                    s["trackHeight"] = round(h / 65536, 2)
    elif buf[:4] == b"\x1a\x45\xdf\xa3":
        s["container"] = "EBML (WebM/MKV)"
    else:
        s["container"] = "unknown"

    deep = _probe_ffprobe(buf, "video")
    if deep:
        _merge_ffprobe_video(s, deep)
    return s


def _merge_ffprobe_video(s: dict, deep: dict) -> None:
    s["probe"] = "ffprobe"
    st = deep.get("streams") or []
    vids = [x for x in st if x.get("codec_type") == "video"]
    if vids:
        v = vids[0]
        for k in ("codec_name", "codec_long_name", "profile", "level", "pix_fmt",
                  "r_frame_rate", "avg_frame_rate", "nb_frames", "bit_rate"):
            if v.get(k) is not None:
                s[k] = v[k]
        if v.get("width") and v.get("height"):
            s["trackWidth"] = v["width"]
            s["trackHeight"] = v["height"]
        if v.get("duration"):
            s["durationSeconds"] = float(v["duration"])
        tags = v.get("tags") or {}
        if tags.get("encoder"):
            s["encoder"] = tags["encoder"][:120]
        if tags.get("creation_time"):
            s["creationTime"] = tags["creation_time"][:60]
        if len(vids) > 1:
            s["videoStreamCount"] = len(vids)
    fmt = deep.get("format") or {}
    if fmt.get("format_name"):
        s["formatName"] = fmt["format_name"]
    if fmt.get("duration"):
        s.setdefault("durationSeconds", float(fmt["duration"]))
    if fmt.get("size"):
        s["fileSizeBytes"] = int(fmt["size"])
    if fmt.get("nb_streams"):
        s["nbStreams"] = int(fmt["nb_streams"])
    ftags = fmt.get("tags") or {}
    for k in ("encoder", "creation_time", "major_brand", "comment"):
        if ftags.get(k):
            s[f"container_{k}"] = str(ftags[k])[:120]


def _probe_ffprobe(buf: bytes, _kind: str) -> dict | None:
    """Deep probe via ffprobe when available; None otherwise (caller degrades
    to the container parser). never fabricates a signal."""
    import json
    import shutil
    import subprocess
    import tempfile
    import os

    ff = os.getenv("FFPROBE_PATH") or shutil.which("ffprobe")
    if not ff:
        return None
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".probe", delete=False) as tf:
            tf.write(buf)
            path = tf.name
        out = subprocess.run(
            [ff, "-v", "error", "-show_format", "-show_streams",
             "-print_format", "json", path],
            capture_output=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except Exception:
        return None
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _probe_audio(buf: bytes) -> dict:
    s = {}
    if buf[:4] == b"RIFF" and buf[8:12] == b"WAVE":
        s["container"] = "WAV"
        pos = 12
        fmt = None
        data_size = None
        while pos + 8 <= len(buf):
            cid = buf[pos:pos + 4]
            csz = struct.unpack("<I", buf[pos + 4:pos + 8])[0]
            cdata = buf[pos + 8:pos + 8 + csz]
            if cid == b"fmt " and len(cdata) >= 16:
                afmt, ch, rate, byte_rate, _blk, bits = struct.unpack("<HHIIHH", cdata[:16])
                fmt = {"channels": ch, "sampleRate": rate, "bitsPerSample": bits,
                       "codec": "PCM" if afmt == 1 else f"format_{afmt}"}
            elif cid == b"data":
                data_size = csz
            pos += 8 + csz + (csz & 1)
        if fmt:
            s.update(fmt)
        if fmt and data_size is not None and fmt.get("bitsPerSample"):
            br = fmt["sampleRate"] * fmt["channels"] * (fmt["bitsPerSample"] // 8)
            if br:
                s["durationSeconds"] = round(data_size / br, 3)
    elif buf[:4] == b"fLaC":
        s["container"] = "FLAC"
        if len(buf) >= 46 and buf[4] == 0x00:
            total = buf[10] >> 3
            sr = ((buf[10] & 0x07) << 12) | (buf[11] << 4) | (buf[12] >> 4)
            ch = ((buf[12] & 0x0E) >> 1) + 1
            bps = (((buf[12] & 0x01) << 4) | (buf[13] >> 4)) + 1
            samples = ((buf[13] & 0x0F) << 32) | (buf[14] << 24) | (buf[15] << 16) | (buf[16] << 8) | buf[17]
            s["sampleRate"] = sr
            s["channels"] = ch
            s["bitsPerSample"] = bps
            if sr:
                s["durationSeconds"] = round(samples / sr, 3)
    elif buf[:4] == b"OggS":
        s["container"] = "OGG"
        head = buf.find(b"\x01vorbis")
        if head > 0 and head + 3 + 4 <= len(buf):
            s["sampleRate"] = struct.unpack("<I", buf[head + 4:head + 8])[0]
            s["channels"] = buf[head + 3]
    elif buf[0] == 0xFF and (buf[1] & 0xE0) == 0xE0:
        s["container"] = "MP3"
        ver = (buf[1] >> 3) & 0x03
        layer = (buf[1] >> 1) & 0x03
        br_idx = (buf[2] >> 4) & 0x0F
        sr_idx = (buf[2] >> 2) & 0x03
        rates = {0: 44100, 1: 48000, 2: 32000}
        s["version"] = "MPEG1" if ver == 3 else ("MPEG2" if ver == 2 else "MPEG2.5")
        s["layer"] = f"Layer{4 - layer}" if layer else None
        if sr_idx in rates:
            s["sampleRate"] = rates[sr_idx]
        tbl = {1: 32, 2: 40, 3: 48, 4: 56, 5: 64, 6: 80, 7: 96, 8: 112, 9: 128,
               10: 160, 11: 192, 12: 224, 13: 256, 14: 320}
        if br_idx in tbl:
            bitrate = tbl[br_idx] * 1000
            s["bitrateKbps"] = bitrate // 1000
            if bitrate:
                s["estimatedDurationSeconds"] = round(len(buf) * 8 / bitrate, 1)
    else:
        s["container"] = "unknown"
    return s


def inspect_bytes(data: bytes, kind: str) -> dict:
    k = kind.lower().lstrip(".")
    if k in IMAGE_KINDS:
        sig = _probe_image(data)
    elif k in VIDEO_KINDS:
        sig = _probe_video(data)
    elif k in AUDIO_KINDS:
        sig = _probe_audio(data)
    else:
        sig = {"kind": "unknown"}
    sig["_kind"] = k if k in IMAGE_KINDS | VIDEO_KINDS | AUDIO_KINDS else "unknown"
    return sig


def describe(data: bytes, kind: str) -> str:
    sig = inspect_bytes(data, kind)
    if sig.get("error"):
        return f"FILE_LEVEL_SIGNALS: could not be extracted ({sig['error']})."
    if sig.get("_kind") == "unknown":
        return ""
    lines = []
    if "format" in sig:
        dims = f"{sig['width']}x{sig['height']}" if "width" in sig else "dimensions unknown"
        lines.append(f"- format={sig['format']}, {dims}, mode={sig.get('mode', 'n/a')}")
        if sig.get("animated"):
            lines.append(f"- animated, {sig['frames']} frames")
        if sig.get("jfif"):
            lines.append("- JFIF marker present")
        if sig.get("exifPresent"):
            ex = sig.get("exif") or {}
            parts = [f"{k}={v}" for k, v in ex.items()]
            lines.append("- EXIF metadata present (" + ", ".join(parts) + ")" if parts else "- EXIF metadata present (no editor/camera tags)")
        else:
            lines.append("- no EXIF metadata found")
        for k in ("png_software", "png_creation_time", "png_source"):
            if k in sig:
                lines.append(f"- PNG {k[4:].replace('_', ' ')}: {sig[k]}")
    if "container" in sig:
        lines.append(f"- container={sig['container']}, size={len(data)} bytes")
        if sig.get("probe") == "ffprobe":
            lines.append("- probe=ffprobe (deep container/encoding read)")
        if "brands" in sig:
            lines.append(f"- brands={sig['brands'][:6]}")
        if sig.get("trackWidth"):
            lines.append(f"- track dimensions: {sig['trackWidth']}x{sig['trackHeight']}")
        if sig.get("durationSeconds"):
            lines.append(f"- duration={sig['durationSeconds']}s")
        for k in ("codec", "profile", "level", "pix_fmt", "r_frame_rate", "avg_frame_rate",
                  "nb_frames", "nbStreams", "videoStreamCount", "encoder", "creationTime",
                  "formatName", "fileSizeBytes", "container_encoder", "container_creation_time",
                  "container_major_brand"):
            if k in sig:
                lines.append(f"- {k}={sig[k]}")
        for k in ("channels", "sampleRate", "bitsPerSample", "codec", "bitrateKbps",
                  "estimatedDurationSeconds", "version", "layer"):
            if k in sig:
                lines.append(f"- {k}={sig[k]}")
    if sig["_kind"] in VIDEO_KINDS and sig.get("probe") != "ffprobe":
        lines.append("- limitation: no ffprobe available — codec, encoding, frame-level and audio-stream signals were NOT extracted")
    header = "FILE_LEVEL_SIGNALS (observed, reproducible):"
    return header + "\n" + "\n".join(lines)


def inspect_text(file_path: str, kind: str) -> str:
    data = load_bytes(file_path)
    if not data:
        return ""
    return describe(data, kind)


if __name__ == "__main__":  # self-check: fails loudly if any parser regresses
    import struct

    # PNG via Pillow
    from PIL import Image
    png = io.BytesIO()
    Image.new("RGB", (37, 23), "red").save(png, format="PNG")
    s = inspect_bytes(png.getvalue(), "image")
    assert s["format"] == "PNG" and (s["width"], s["height"]) == (37, 23), s

    # WAV synthesized
    rate, ch, bits = 8000, 1, 16
    data = bytes(800)
    wav = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" +
           b"fmt " + struct.pack("<IHHIIHH", 16, 1, ch, rate, rate * ch * 2, 2, bits) +
           b"data" + struct.pack("<I", len(data)) + data)
    s = inspect_bytes(wav, "audio")
    assert s["sampleRate"] == 8000 and s["durationSeconds"] == round(len(data) / (rate * ch * 2), 3) == 0.05, s

    # MP4 stub: ftyp + moov(mvhd v0 + tkhd v0)
    def box(t, payload):
        return struct.pack(">I", 8 + len(payload)) + t + payload

    mvhd = bytes([0]) + b"\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, 5)
    tkhd = (bytes([0]) + b"\x00\x00\x07" + struct.pack(">II", 0, 0) + struct.pack(">I", 1) +
            b"\x00\x00\x00\x00" + struct.pack(">I", 5) + b"\x00\x00\x00\x00\x00\x00\x00\x00" +
            struct.pack(">HHHH", 0, 0, 0, 0) + b"\x00" * 36 +
            struct.pack(">II", 1920 << 16, 1080 << 16))
    mp4 = box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2") + box(b"moov", box(b"mvhd", mvhd) + box(b"trak", box(b"tkhd", tkhd)))
    s = inspect_bytes(mp4, "video")
    assert "isom" in s["brands"], s
    assert s["durationSeconds"] == 0.005, s
    assert s["trackWidth"] == 1920.0 and s["trackHeight"] == 1080.0, s

    # MP3 header stub (MPEG1 Layer3 44100, 128kbps)
    mp3 = bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * 1024
    s = inspect_bytes(mp3, "audio")
    assert s["sampleRate"] == 44100 and s["bitrateKbps"] == 128, s

    print("signals self-check OK")