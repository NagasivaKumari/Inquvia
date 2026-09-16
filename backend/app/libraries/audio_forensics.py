"""Audio forensic analysis module for Inquvia investigations.

Provides deterministic, reproducible audio analysis including:
- Transcription with timestamps
- Speaker consistency analysis
- Audio manipulation/splicing detection
- AI/synthetic voice detection
- Acoustic anomaly detection
- Metadata/provenance extraction
"""
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal
from scipy.io import wavfile
from scipy.signal import spectrogram, find_peaks

from .. import config

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_LENGTH = int(SAMPLE_RATE * 0.025)
FRAME_SHIFT = int(SAMPLE_RATE * 0.010)

def load_audio(wav_path: str) -> tuple[np.ndarray, int] | tuple[None, None]:
    """Load WAV file as mono float32 at 16kHz."""
    try:
        sr, data = wavfile.read(wav_path)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if data.dtype != np.float32:
            data = data.astype(np.float32) / np.iinfo(data.dtype).max
        if sr != SAMPLE_RATE:
            from scipy.signal import resample
            num_samples = int(len(data) * SAMPLE_RATE / sr)
            data = resample(data, num_samples)
        return data, SAMPLE_RATE
    except Exception as e:
        logger.exception("Failed to load audio from %s", wav_path)
        return None, None


def compute_spectrogram(audio: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute spectrogram with consistent parameters."""
    f, t, Sxx = spectrogram(
        audio,
        fs=sr,
        window="hann",
        nperseg=FRAME_LENGTH,
        noverlap=FRAME_LENGTH - FRAME_SHIFT,
        mode="magnitude",
    )
    return f, t, 20 * np.log10(Sxx + 1e-10)


def compute_mfcc(audio: np.ndarray, sr: int, n_mfcc: int = 13) -> np.ndarray:
    """Compute MFCC features (approximate, using DCT of log mel spectrogram)."""
    f, t, Sxx = compute_spectrogram(audio, sr)
    mel_filters = _mel_filterbank(n_mels=40, sr=sr, n_fft=FRAME_LENGTH)
    mel_spec = mel_filters @ np.power(10, Sxx / 20)
    log_mel = np.log(mel_spec + 1e-10)
    mfcc = _dct(log_mel, n_mfcc)
    return mfcc.T


def _mel_filterbank(n_mels: int, sr: int, n_fft: int) -> np.ndarray:
    """Create mel filterbank matrix."""
    f_min, f_max = 0, sr / 2
    mel_min = 2595 * np.log10(1 + f_min / 700)
    mel_max = 2595 * np.log10(1 + f_max / 700)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    filters = np.zeros((n_mels, n_fft // 2 + 1))
    for i in range(1, n_mels + 1):
        left, center, right = bin_points[i - 1], bin_points[i], bin_points[i + 1]
        if center > left:
            filters[i - 1, left:center] = np.linspace(0, 1, center - left)
        if right > center:
            filters[i - 1, center:right] = np.linspace(1, 0, right - center)
    return filters


def _dct(x: np.ndarray, n: int) -> np.ndarray:
    """Discrete Cosine Transform Type-II."""
    N = x.shape[0]
    result = np.zeros((n, x.shape[1]))
    for k in range(n):
        result[k] = np.sum(x * np.cos(np.pi * k * (np.arange(N) + 0.5) / N)[:, np.newaxis], axis=0)
    return result


def detect_silence(audio: np.ndarray, sr: int, threshold_db: float = -40, min_duration: float = 0.1) -> list[dict]:
    """Detect silence/pause segments."""
    frame_len = int(sr * 0.025)
    hop_len = int(sr * 0.010)
    rms = np.sqrt(np.convolve(audio**2, np.ones(frame_len)/frame_len, mode='valid')[::hop_len])
    rms_db = 20 * np.log10(rms + 1e-10)
    is_silence = rms_db < threshold_db
    
    segments = []
    in_silence = False
    start = 0
    for i, silent in enumerate(is_silence):
        t = i * hop_len / sr
        if silent and not in_silence:
            in_silence = True
            start = t
        elif not silent and in_silence:
            in_silence = False
            duration = t - start
            if duration >= min_duration:
                segments.append({"start": round(start, 3), "end": round(t, 3), "duration": round(duration, 3), "type": "pause"})
    if in_silence:
        duration = len(audio) / sr - start
        if duration >= min_duration:
            segments.append({"start": round(start, 3), "end": round(len(audio) / sr, 3), "duration": round(duration, 3), "type": "pause"})
    return segments


def detect_breathing(audio: np.ndarray, sr: int) -> list[dict]:
    """Detect potential breathing sounds (high-frequency noise bursts during pauses)."""
    f, t, Sxx = compute_spectrogram(audio, sr)
    high_freq_idx = f > 2000
    high_energy = np.mean(Sxx[high_freq_idx], axis=0)
    threshold = np.percentile(high_energy, 85)
    is_breath = high_energy > threshold
    
    segments = []
    in_breath = False
    start = 0
    for i, breath in enumerate(is_breath):
        if breath and not in_breath:
            in_breath = True
            start = t[i]
        elif not breath and in_breath:
            in_breath = False
            duration = t[i] - start
            if 0.05 <= duration <= 1.0:
                segments.append({"start": round(start, 3), "end": round(t[i], 3), "duration": round(duration, 3), "type": "breathing"})
    if in_breath:
        duration = t[-1] - start
        if 0.05 <= duration <= 1.0:
            segments.append({"start": round(start, 3), "end": round(t[-1], 3), "duration": round(duration, 3), "type": "breathing"})
    return segments


def compute_pitch(audio: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Estimate fundamental frequency (F0) using autocorrelation."""
    frame_len = int(sr * 0.025)
    hop_len = int(sr * 0.010)
    n_frames = (len(audio) - frame_len) // hop_len + 1
    f0 = np.zeros(n_frames)
    voiced = np.zeros(n_frames, dtype=bool)
    
    for i in range(n_frames):
        frame = audio[i * hop_len:i * hop_len + frame_len]
        if len(frame) < frame_len:
            break
        frame = frame * np.hanning(len(frame))
        corr = np.correlate(frame, frame, mode='full')[len(frame)-1:]
        corr[:int(sr/500)] = 0
        peak_idx = np.argmax(corr[int(sr/500):int(sr/50)]) + int(sr/500)
        if peak_idx > 0 and corr[peak_idx] > 0.3 * corr[0]:
            f0[i] = sr / peak_idx
            voiced[i] = True
    times = np.arange(n_frames) * hop_len / sr
    return times, f0


def detect_pitch_anomalies(f0: np.ndarray, times: np.ndarray) -> list[dict]:
    """Detect unnatural pitch transitions."""
    anomalies = []
    voiced_f0 = f0[f0 > 0]
    if len(voiced_f0) < 10:
        return anomalies
    
    median_f0 = np.median(voiced_f0)
    diff = np.diff(f0)
    voiced_diff = diff[(f0[:-1] > 0) & (f0[1:] > 0)]
    
    if len(voiced_diff) > 0:
        threshold = 3 * np.std(voiced_diff)
        jumps = np.where(np.abs(diff) > threshold)[0]
        for idx in jumps:
            if f0[idx] > 0 and f0[idx+1] > 0:
                anomalies.append({
                    "timestamp": round(times[idx], 3),
                    "type": "pitch_jump",
                    "from_hz": round(f0[idx], 1),
                    "to_hz": round(f0[idx+1], 1),
                    "change_hz": round(abs(f0[idx+1] - f0[idx]), 1),
                    "description": f"Abrupt pitch change from {f0[idx]:.1f}Hz to {f0[idx+1]:.1f}Hz"
                })
    return anomalies


def detect_spectral_discontinuities(audio: np.ndarray, sr: int, window_sec: float = 0.5) -> list[dict]:
    """Detect abrupt spectral changes indicating possible splices."""
    f, t, Sxx = compute_spectrogram(audio, sr)
    window_frames = int(window_sec * sr / FRAME_SHIFT)
    
    anomalies = []
    for i in range(window_frames, Sxx.shape[1] - window_frames):
        before = np.mean(Sxx[:, i-window_frames:i], axis=1)
        after = np.mean(Sxx[:, i:i+window_frames], axis=1)
        diff = np.mean(np.abs(after - before))
        local_std = np.std(np.abs(np.diff(Sxx, axis=1)), axis=1)
        threshold = 3 * np.mean(local_std)
        if diff > threshold:
            anomalies.append({
                "timestamp": round(t[i], 3),
                "type": "spectral_discontinuity",
                "magnitude": round(diff, 2),
                "description": f"Spectral discontinuity at {t[i]:.2f}s (magnitude: {diff:.2f}dB)"
            })
    return anomalies


def detect_noise_floor_changes(audio: np.ndarray, sr: int, window_sec: float = 1.0) -> list[dict]:
    """Detect changes in background noise floor."""
    frame_len = int(sr * 0.025)
    hop_len = int(sr * 0.010)
    window_frames = int(window_sec * sr / hop_len)
    
    rms = np.sqrt(np.convolve(audio**2, np.ones(frame_len)/frame_len, mode='valid')[::hop_len])
    rms_db = 20 * np.log10(rms + 1e-10)
    
    anomalies = []
    for i in range(window_frames, len(rms_db) - window_frames):
        before = np.percentile(rms_db[i-window_frames:i], 10)
        after = np.percentile(rms_db[i:i+window_frames], 10)
        if abs(after - before) > 6:
            anomalies.append({
                "timestamp": round(i * hop_len / sr, 3),
                "type": "noise_floor_change",
                "before_db": round(before, 1),
                "after_db": round(after, 1),
                "change_db": round(after - before, 1),
                "description": f"Noise floor change from {before:.1f}dB to {after:.1f}dB"
            })
    return anomalies


def detect_clipping(audio: np.ndarray, sr: int, threshold: float = 0.99) -> list[dict]:
    """Detect digital clipping."""
    clipped = np.abs(audio) > threshold
    if not np.any(clipped):
        return []
    
    segments = []
    in_clip = False
    start = 0
    for i, clip in enumerate(clipped):
        if clip and not in_clip:
            in_clip = True
            start = i
        elif not clip and in_clip:
            in_clip = False
            duration = (i - start) / sr
            if duration > 0.001:
                segments.append({
                    "start": round(start / sr, 3),
                    "end": round(i / sr, 3),
                    "duration": round(duration, 3),
                    "type": "clipping",
                    "description": f"Digital clipping detected ({duration*1000:.1f}ms)"
                })
    return segments


def detect_duplicate_segments(audio: np.ndarray, sr: int, min_duration: float = 0.5) -> list[dict]:
    """Detect potentially duplicated audio segments using cross-correlation."""
    frame_len = int(sr * 0.1)
    hop_len = int(sr * 0.05)
    n_frames = (len(audio) - frame_len) // hop_len + 1
    
    if n_frames < 100:
        return []
    
    fingerprints = []
    for i in range(n_frames):
        frame = audio[i * hop_len:i * hop_len + frame_len]
        if len(frame) < frame_len:
            break
        fft = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
        fingerprint = fft[::max(1, len(fft)//64)]
        fingerprints.append(fingerprint / (np.linalg.norm(fingerprint) + 1e-10))
    
    fingerprints = np.array(fingerprints)
    anomalies = []
    threshold = 0.95
    
    for i in range(len(fingerprints)):
        for j in range(i + int(min_duration * sr / hop_len), len(fingerprints)):
            sim = np.dot(fingerprints[i], fingerprints[j])
            if sim > threshold:
                anomalies.append({
                    "timestamp_a": round(i * hop_len / sr, 3),
                    "timestamp_b": round(j * hop_len / sr, 3),
                    "type": "duplicate_segment",
                    "similarity": round(sim, 3),
                    "description": f"Highly similar segments at {i*hop_len/sr:.2f}s and {j*hop_len/sr:.2f}s (similarity: {sim:.3f})"
                })
    return anomalies[:10]


def analyze_speaker_consistency(audio: np.ndarray, sr: int, transcript_segments: list[dict] | None = None) -> dict:
    """Analyze voice characteristics for speaker consistency."""
    mfcc = compute_mfcc(audio, sr)
    
    if transcript_segments:
        segment_features = []
        for seg in transcript_segments:
            start_frame = int(seg["start"] * sr / FRAME_SHIFT)
            end_frame = int(seg["end"] * sr / FRAME_SHIFT)
            if start_frame < len(mfcc) and end_frame <= len(mfcc):
                segment_features.append(np.mean(mfcc[start_frame:end_frame], axis=0))
        
        if len(segment_features) >= 2:
            features = np.array(segment_features)
            pairwise_dist = np.zeros((len(features), len(features)))
            for i in range(len(features)):
                for j in range(i+1, len(features)):
                    dist = np.linalg.norm(features[i] - features[j])
                    pairwise_dist[i, j] = dist
                    pairwise_dist[j, i] = dist
            
            avg_dist = np.mean(pairwise_dist[pairwise_dist > 0])
            max_dist = np.max(pairwise_dist)
            
            return {
                "consistent": avg_dist < 2.0,
                "avg_mfcc_distance": round(float(avg_dist), 3),
                "max_mfcc_distance": round(float(max_dist), 3),
                "num_segments": len(segment_features),
                "segments_analyzed": len(transcript_segments),
                "interpretation": "Consistent with single speaker" if avg_dist < 2.0 else "Potential speaker change detected"
            }
    
    return {
        "consistent": True,
        "avg_mfcc_distance": None,
        "max_mfcc_distance": None,
        "num_segments": 0,
        "interpretation": "Insufficient segments for speaker consistency analysis"
    }


def detect_synthetic_voice_indicators(audio: np.ndarray, sr: int, transcript: str | None = None) -> dict:
    """Detect indicators of synthetic/AI-generated voice."""
    indicators = []
    
    times, f0 = compute_pitch(audio, sr)
    voiced_f0 = f0[f0 > 0]
    
    if len(voiced_f0) > 10:
        f0_std = np.std(voiced_f0)
        f0_range = np.max(voiced_f0) - np.min(voiced_f0)
        
        if f0_std < 5:
            indicators.append({
                "indicator": "low_pitch_variability",
                "description": f"Very low pitch variation (std={f0_std:.1f}Hz) — unnatural for human speech",
                "confidence": min(90, int(100 * (1 - f0_std / 20))),
                "type": "forensic_indicator"
            })
        
        if f0_range < 30:
            indicators.append({
                "indicator": "narrow_pitch_range",
                "description": f"Narrow pitch range ({f0_range:.1f}Hz) — may indicate synthetic voice",
                "confidence": min(80, int(100 * (1 - f0_range / 100))),
                "type": "forensic_indicator"
            })
    
    mfcc = compute_mfcc(audio, sr)
    mfcc_std = np.std(mfcc, axis=1)
    if np.mean(mfcc_std) < 5:
        indicators.append({
            "indicator": "low_spectral_variability",
            "description": "Low spectral variability across utterance — characteristic of some TTS systems",
            "confidence": 65,
            "type": "forensic_indicator"
        })
    
    pauses = detect_silence(audio, sr)
    if pauses:
        pause_durations = [p["duration"] for p in pauses]
        pause_cv = np.std(pause_durations) / (np.mean(pause_durations) + 1e-10)
        if pause_cv < 0.1 and len(pauses) > 3:
            indicators.append({
                "indicator": "unnatural_pause_regularity",
                "description": f"Unnaturally regular pause durations (CV={pause_cv:.3f}) — may indicate scripted/generated speech",
                "confidence": 70,
                "type": "forensic_indicator"
            })
    
    breathing = detect_breathing(audio, sr)
    if len(breathing) == 0 and len(audio) / sr > 10:
        indicators.append({
            "indicator": "no_breathing_detected",
            "description": "No breathing sounds detected in >10s of speech — unusual for natural human speech",
            "confidence": 55,
            "type": "forensic_indicator"
        })
    
    clipping = detect_clipping(audio, sr)
    if clipping:
        indicators.append({
            "indicator": "digital_clipping",
            "description": "Digital clipping present — may indicate post-processing or low-quality synthesis",
            "confidence": 60,
            "type": "forensic_indicator"
        })
    
    return {
        "indicators": indicators,
        "synthetic_likelihood": "high" if len([i for i in indicators if i["confidence"] > 70]) >= 2 else 
                               "moderate" if len(indicators) >= 1 else "low",
        "overall_confidence": min(95, max(i["confidence"] for i in indicators)) if indicators else 0,
        "limitations": ["Analysis limited to acoustic features; no external synthetic voice detector available"]
    }


def extract_metadata(wav_path: str) -> dict:
    """Extract audio metadata using ffprobe."""
    import shutil
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"error": "ffprobe not available"}
    
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_format", "-show_streams",
             "-print_format", "json", wav_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        logger.exception("ffprobe failed for %s", wav_path)
    return {"error": "metadata extraction failed"}


def analyze_audio_forensics(wav_path: str, transcript: str | None = None, 
                            transcript_segments: list[dict] | None = None) -> dict:
    """Comprehensive forensic audio analysis."""
    audio, sr = load_audio(wav_path)
    if audio is None:
        return {"error": "Failed to load audio"}
    
    duration = len(audio) / sr
    
    pauses = detect_silence(audio, sr)
    breathing = detect_breathing(audio, sr)
    times, f0 = compute_pitch(audio, sr)
    pitch_anomalies = detect_pitch_anomalies(f0, times)
    spectral_anomalies = detect_spectral_discontinuities(audio, sr)
    noise_floor_changes = detect_noise_floor_changes(audio, sr)
    clipping = detect_clipping(audio, sr)
    duplicates = detect_duplicate_segments(audio, sr)
    
    speaker_analysis = analyze_speaker_consistency(audio, sr, transcript_segments)
    synthetic_analysis = detect_synthetic_voice_indicators(audio, sr, transcript)
    metadata = extract_metadata(wav_path)
    
    voiced_f0 = f0[f0 > 0]
    pitch_stats = {}
    if len(voiced_f0) > 0:
        pitch_stats = {
            "mean_hz": round(float(np.mean(voiced_f0)), 1),
            "median_hz": round(float(np.median(voiced_f0)), 1),
            "std_hz": round(float(np.std(voiced_f0)), 1),
            "min_hz": round(float(np.min(voiced_f0)), 1),
            "max_hz": round(float(np.max(voiced_f0)), 1),
            "range_hz": round(float(np.max(voiced_f0) - np.min(voiced_f0)), 1),
            "voiced_fraction": round(float(len(voiced_f0) / len(f0)), 3)
        }
    
    rms = np.sqrt(np.mean(audio**2))
    rms_db = 20 * np.log10(rms + 1e-10)
    
    all_anomalies = []
    for a in pitch_anomalies:
        a["category"] = "prosody"
        all_anomalies.append(a)
    for a in spectral_anomalies:
        a["category"] = "spectral"
        all_anomalies.append(a)
    for a in noise_floor_changes:
        a["category"] = "background"
        all_anomalies.append(a)
    for a in clipping:
        a["category"] = "quality"
        all_anomalies.append(a)
    for a in duplicates:
        a["category"] = "duplication"
        all_anomalies.append(a)
    
    all_anomalies.sort(key=lambda x: x.get("timestamp", x.get("timestamp_a", 0)))
    
    result = {
        "duration_seconds": round(duration, 3),
        "sample_rate": sr,
        "rms_db": round(rms_db, 1),
        "pitch_statistics": pitch_stats,
        "pauses": pauses,
        "breathing": breathing,
        "pitch_anomalies": pitch_anomalies,
        "spectral_discontinuities": spectral_anomalies,
        "noise_floor_changes": noise_floor_changes,
        "clipping": clipping,
        "duplicate_segments": duplicates,
        "all_anomalies": all_anomalies,
        "speaker_consistency": speaker_analysis,
        "synthetic_voice_analysis": synthetic_analysis,
        "metadata": metadata,
        "limitations": [
            "Analysis performed on extracted 16kHz mono WAV (first {}s)".format(config.AUDIO_TRANSCRIPT_WINDOW_SECONDS),
            "No external synthetic voice detector (e.g., Resemblyzer, DeepFake-O-Meter) available",
            "Speaker consistency analysis requires multiple speech segments",
            "Spectral analysis limited by extracted audio quality"
        ]
    }
    return _convert(result)


def _convert(obj):
    """Convert numpy types to Python native types for JSON serialization."""
    if isinstance(obj, (np.integer, np.int64, np.int32, np.int8, np.int16)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _convert(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_convert(v) for v in obj]
    return obj


def format_evidence_record(analysis: dict, label: str, check_type: str) -> dict:
    """Format analysis results as structured evidence record."""
    if "error" in analysis:
        return {
            "finding": f"{check_type} ({label}): analysis failed — {analysis['error']}",
            "signal": "uncertain",
            "metadata": {"fileName": label, "evidenceUnavailable": True, "error": analysis["error"]}
        }
    
    analysis = _convert(analysis)
    findings = []
    evidence_record = {
        "finding": "",
        "signal": "observed",
        "metadata": {
            "fileName": label,
            "evidenceRecord": {
                "type": "observed",
                "source": {"name": "Inquvia Audio Forensics Engine", "url": "internal", "type": "primary", "verified": True},
                "confidence": 85,
                "rationale": "Automated deterministic audio forensic analysis using signal processing.",
                "details": {}
            },
            **analysis
        }
    }
    
    if check_type == "Audio authenticity":
        findings.append(f"Duration: {analysis['duration_seconds']}s, RMS: {analysis['rms_db']}dB")
        if analysis["pitch_statistics"]:
            ps = analysis["pitch_statistics"]
            findings.append(f"Pitch: mean={ps['mean_hz']}Hz, range={ps['range_hz']}Hz, voiced={ps['voiced_fraction']*100:.0f}%")
        findings.append(f"Pauses detected: {len(analysis['pauses'])}")
        findings.append(f"Breathing indicators: {len(analysis['breathing'])}")
        findings.append(f"Anomalies found: {len(analysis['all_anomalies'])}")
        evidence_record["metadata"]["evidenceRecord"]["details"] = {
            "duration": analysis["duration_seconds"],
            "pitch_stats": analysis["pitch_statistics"],
            "pause_count": len(analysis["pauses"]),
            "breathing_count": len(analysis["breathing"]),
            "anomaly_count": len(analysis["all_anomalies"])
        }
    
    elif check_type == "Voice/deepfake detection":
        synth = analysis["synthetic_voice_analysis"]
        findings.append(f"Synthetic likelihood: {synth['synthetic_likelihood']}")
        findings.append(f"Indicators found: {len(synth['indicators'])}")
        for ind in synth["indicators"]:
            findings.append(f"  - {ind['indicator']}: {ind['description']} (confidence: {ind['confidence']}%)")
        evidence_record["metadata"]["evidenceRecord"]["details"] = synth
    
    elif check_type == "Speaker/voice consistency":
        sc = analysis["speaker_consistency"]
        findings.append(f"Consistent with single speaker: {'Yes' if sc['consistent'] else 'No'}")
        findings.append(f"Interpretation: {sc['interpretation']}")
        if sc["avg_mfcc_distance"] is not None:
            findings.append(f"Avg MFCC distance: {sc['avg_mfcc_distance']}, Max: {sc['max_mfcc_distance']}")
        evidence_record["metadata"]["evidenceRecord"]["details"] = sc
    
    elif check_type == "Audio manipulation/splicing":
        anomalies = analysis["all_anomalies"]
        findings.append(f"Total anomalies detected: {len(anomalies)}")
        for a in anomalies[:10]:
            findings.append(f"  - {a['timestamp']}s: {a['description']}")
        if len(anomalies) > 10:
            findings.append(f"  ... and {len(anomalies) - 10} more")
        evidence_record["metadata"]["evidenceRecord"]["details"] = {
            "anomaly_count": len(anomalies),
            "anomalies_by_category": {
                "prosody": len([a for a in anomalies if a.get("category") == "prosody"]),
                "spectral": len([a for a in anomalies if a.get("category") == "spectral"]),
                "background": len([a for a in anomalies if a.get("category") == "background"]),
                "quality": len([a for a in anomalies if a.get("category") == "quality"]),
                "duplication": len([a for a in anomalies if a.get("category") == "duplication"])
            }
        }
    
    evidence_record["finding"] = f"{check_type} ({label}): " + "; ".join(findings)
    return evidence_record


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result = analyze_audio_forensics(sys.argv[1])
        print(json.dumps(result, indent=2, default=str))