import shutil
import os
import subprocess

print(f"FFPROBE_PATH env: {os.getenv('FFPROBE_PATH')}")
ffprobe = shutil.which("ffprobe")
print(f"shutil.which('ffprobe'): {ffprobe}")

if ffprobe:
    try:
        out = subprocess.run([ffprobe, "-version"], capture_output=True, text=True)
        print(f"ffprobe version: {out.stdout.splitlines()[0]}")
    except Exception as e:
        print(f"Error running ffprobe: {e}")
else:
    print("ffprobe not found")
