import subprocess
from pathlib import Path

def extract_audio(ffmpeg_path, source, out_wav):
    args = [ffmpeg_path, "-v", "error", "-i", source, "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1", out_wav]
    
    # Try capturing output
    try:
        res = subprocess.run(args, capture_output=True, text=True, check=True)
        return True, "Success", res.stderr
    except subprocess.CalledProcessError as e:
        return False, str(e), e.stderr

ffmpeg_path = "ffmpeg"
source = "test_audio_fail.mp4"
out_wav = "test_output.wav"

success, msg, stderr = extract_audio(ffmpeg_path, source, out_wav)
print(f"Success: {success}, Msg: {msg}, Stderr: {stderr}")
if success and Path(out_wav).exists():
    print("File exists")
else:
    print("File missing")
