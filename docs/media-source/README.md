# Media build scripts

`content.py` holds the scenes and narration; `build.py` renders slides with Playwright (Chromium),
speaks them with Kokoro (kokoro-onnx, `af_heart` voice) and joins them with ffmpeg.

Setup (not committed: the model files, about 350 MB):
    python3 -m venv v && . v/bin/activate && pip install kokoro-onnx soundfile playwright
    curl -L -o kokoro.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
    curl -L -o voices.bin  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
Run: `python build.py long` (walkthrough) or `python build.py short 20` (LinkedIn cut).
`build.py` expects Chromium at /opt/pw-browsers/chromium-1194/chrome-linux/chrome; change the path for your machine.
Check the Kokoro license before commercial use.
