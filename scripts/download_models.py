"""Fetch fixed model artifacts; verify the generated SHA256 manifest on subsequent runs."""

import urllib.request, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
MODELS.mkdir(exist_ok=True)
SOURCES = {
    "MiniFASNetV2.onnx": "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx",
    "MiniFASNetV1SE.onnx": "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV1SE.onnx",
    "silero_vad.onnx": "https://raw.githubusercontent.com/snakers4/silero-vad/v6.0/src/silero_vad/data/silero_vad.onnx",
    "yolo11n.onnx": "https://huggingface.co/deepghs/yolos/resolve/main/yolo11n/model.onnx",
    "yolo11s.onnx": "https://huggingface.co/deepghs/yolos/resolve/main/yolo11s/model.onnx",
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "face_detector.tflite": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
    "face_detection_yunet.onnx": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface.onnx": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
manifest_path = MODELS / "manifest.json"
old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
manifest = {}
for name, url in SOURCES.items():
    path = MODELS / name
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            path.write_bytes(response.read())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pinned = {'MiniFASNetV2.onnx':'b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907',
              'MiniFASNetV1SE.onnx':'ebab7f90c7833fbccd46d3a555410e78d969db5438e169b6524be444862b3676'}
    if name in pinned and digest != pinned[name]:
        raise RuntimeError('Pinned anti-spoof model hash mismatch')
    if name == "silero_vad.onnx" and digest != "597d30b3ec076608d059477bb14cfeffdf951bf5cae370d38f65d33bbfe82004":
        raise RuntimeError("Pinned speech model hash mismatch")
    if name in old and old[name]["sha256"] != digest:
        raise RuntimeError("Model hash mismatch: " + name)
    manifest[name] = {
        "url": url,
        "sha256": digest,
        "bytes": path.stat().st_size,
        "license": (
            'MiniVision Apache-2.0, yakhyo ONNX conversion' if name.startswith('MiniFAS') else "Silero VAD MIT (v6.0)" if name == "silero_vad.onnx" else "Ultralytics AGPL-3.0 (community ONNX conversion)"
            if name.startswith("yolo")
            else (
                "OpenCV Zoo upstream model license"
                if name.endswith(".onnx")
                else "MediaPipe model terms; see upstream model card"
            )
        ),
    }
    print(name, path.stat().st_size, digest)
manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
