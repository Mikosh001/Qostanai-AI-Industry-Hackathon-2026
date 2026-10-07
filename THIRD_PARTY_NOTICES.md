# Third-party sources

The project source is supplied under AGPL-3.0-or-later; see LICENSE. Upstream components retain their own licenses. This list records provenance and does not replace their full notices.

| Component | Source / declared license |
|---|---|
| YOLO11n / YOLO11s weights | Ultralytics COCO models, metadata declares AGPL-3.0: https://github.com/ultralytics/ultralytics and https://docs.ultralytics.com/models/yolo11/ |
| ONNX conversion | Community export: https://huggingface.co/deepghs/yolos/tree/main. Exact artifact SHA-256 and URL in models/manifest.json. Not represented as an official Ultralytics binary export. |
| MediaPipe Tasks | https://github.com/google-ai-edge/mediapipe — Apache-2.0. Model assets use Google's mediapipe-models URLs; consult upstream model cards/terms. |
| ONNX Runtime | https://github.com/microsoft/onnxruntime — MIT |
| Silero VAD 6.0 | https://github.com/snakers4/silero-vad/tree/v6.0 — MIT. Pinned ONNX digest in models/manifest.json; full license in models/SILERO-LICENSE.txt. Used for voice activity only; no speaker recognition or speech transcription. |
| YuNet face detector | https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet — MIT, Shiqi Yu. Full license in models/licenses/face_detection_yunet-LICENSE.txt. |
| SFace recognizer | https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface — Apache-2.0. Full license in models/licenses/face_recognition_sface-LICENSE.txt. |
| OpenCV | https://github.com/opencv/opencv — Apache-2.0 |
| Electron / React / Vite / Lucide | MIT / MIT / MIT / ISC respectively; upstream notices are retained in installed packages. |
| FastAPI / Uvicorn / HTTPX | MIT / BSD-3-Clause / BSD-3-Clause |
| Cryptography | Apache-2.0 or BSD-3-Clause |
| ReportLab / psutil / pywin32 | BSD licenses / BSD-3-Clause / PSF-related license; see installed distribution notices. |
| .NET + System.Management + System.Drawing.Common + System.ServiceProcess.ServiceController | https://github.com/dotnet/runtime — MIT |
| Moodle lab | https://github.com/moodle/moodle, version 4.5.15 — GPL-3.0-or-later. The lab is isolated test infrastructure, not redistributed inside the desktop installer. |
| PHP / MariaDB lab | Official PHP Windows distribution and official MariaDB 11.4.8 archive; see lab/setup.py pinned checksums and upstream licenses. |

Raw COCO128 and labelled test photographs remain in the local work directory and are not redistributed in source archives or the desktop installer. `tests/model-acceptance.json` stores measurements and image filenames, not the photographs. Documentation screenshots include an AI-generated demonstration portrait and the actual application interface. That portrait does not depict a real student. The separate demonstration video uses opt-in test camera frames, as disclosed in its validation record.

Runtime JavaScript dependency audit reported zero advisories during validation. The build tooling chain (electron-builder download/logging dependencies) reported moderate development-only advisories; these packages are not part of runtime dependencies. No forced incompatible downgrade was applied.

MiniFASNetV2 and MiniFASNetV1SE: https://github.com/minivision-ai/Silent-Face-Anti-Spoofing (Apache-2.0); ONNX conversion https://github.com/yakhyo/face-anti-spoofing (Apache-2.0). Full license: models/licenses/MiniFASNet-LICENSE.txt. Pinned SHA256 values are in scripts/download_models.py and models/manifest.json. Labelled example photographs are kept only in the local work directory.
