"""Local camera inference and per-session photo comparison; no automatic guilt score."""

import cv2, numpy as np, math, time
from collections import deque
from pathlib import Path
from .identity import FaceIdentity
from .liveness import PresentationDetector


class Vision:
    def __init__(self, models: Path):
        self.models = models
        self.yolo = None
        self.landmarker = None
        self.detector = None
        self.error = ""
        self.calibration = {}
        self.samples = deque(maxlen=60)
        self.last_ts = 0
        self.identity = None
        self.presentation = None
        self.identity_threshold = 0.363
        self.phone_threshold = 0.30
        self.phone_sample_at = 0
        self.phone_cache = []
        self.phone_crop_cycle = 0
        self.identity_result = {"state": "not_enrolled", "score": None}
        self.last_identity_at = 0
        try:
            import onnxruntime as ort
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision

            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            self.model_name = (
                "yolo11s.onnx" if (models / "yolo11s.onnx").exists() else "yolo11n.onnx"
            )
            self.yolo = ort.InferenceSession(
                str(models / self.model_name),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self.landmarker = vision.FaceLandmarker.create_from_options(
                vision.FaceLandmarkerOptions(
                    base_options=BaseOptions(
                        model_asset_path=str(models / "face_landmarker.task")
                    ),
                    running_mode=vision.RunningMode.VIDEO,
                    num_faces=3,
                    output_facial_transformation_matrixes=True,
                )
            )
            self.detector = vision.FaceDetector.create_from_options(
                vision.FaceDetectorOptions(
                    base_options=BaseOptions(
                        model_asset_path=str(models / "face_detector.tflite")
                    ),
                    running_mode=vision.RunningMode.VIDEO,
                    min_detection_confidence=0.55,
                )
            )
            self.mp = mp
            self.identity = FaceIdentity(models)
            self.presentation = PresentationDetector(models)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    @property
    def ready(self):
        return (
            self.yolo is not None
            and self.landmarker is not None
            and self.detector is not None
            and self.identity is not None
            and not self.error
        )

    def phones(self, frame):
        now = time.monotonic()
        if self.phone_sample_at and now - self.phone_sample_at < 0.5:
            return self.phone_cache
        height, width = frame.shape[:2]
        # The training scale and the detail scale complement each other: a
        # 640px positive can disappear at 960px after padding/resizing, and vice versa.
        result = self._phone_infer(frame,640)
        if max((p['confidence'] for p in result),default=0)<0.65:
            result += self._phone_infer(frame,960)
        # An additional crop preserves detail around hands without a larger model
        # or any rectangle/color heuristic that would mislabel ordinary objects.
        if not result:
            self.phone_crop_cycle+=1
            x1,x2=(0,int(width*.64)) if self.phone_crop_cycle%2 else (int(width*.36),width)
            crop=frame[:,x1:x2]
            for p in self._phone_infer(crop,960):
                p['box'][0]+=x1;p['source']='detail_crop';result.append(p)
        boxes=[p['box'] for p in result];scores=[p['confidence'] for p in result]
        indices=cv2.dnn.NMSBoxes(boxes,scores,self.phone_threshold,0.45) if boxes else []
        self.phone_cache=[result[int(i)] for i in np.array(indices).flatten()]
        self.phone_sample_at=time.monotonic()
        return self.phone_cache

    def _phone_infer(self, frame, size):
        height, width = frame.shape[:2]
        scale = min(size / width, size / height)
        rw, rh = round(width * scale), round(height * scale)
        left = (size - rw) // 2
        top = (size - rh) // 2
        resized = cv2.resize(frame, (rw, rh))
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)
        canvas[top : top + rh, left : left + rw] = resized
        tensor = (
            np.ascontiguousarray(
                canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32
            )
            / 255
        )
        output = self.yolo.run(None, {self.yolo.get_inputs()[0].name: tensor})[0]
        predictions = output[0].T if output.shape[1] < output.shape[2] else output[0]
        # COCO index 67 is cell phone. Standard COCO has no face class.
        confidence = predictions[:, 4 + 67]
        selected = predictions[confidence >= self.phone_threshold]
        boxes = []
        scores = []
        for p in selected:
            x, y, w, h = p[:4]
            boxes.append(
                [
                    float((x - w / 2 - left) / scale),
                    float((y - h / 2 - top) / scale),
                    float(w / scale),
                    float(h / scale),
                ]
            )
            scores.append(float(p[4 + 67]))
        indices = cv2.dnn.NMSBoxes(boxes, scores, self.phone_threshold, 0.45)
        result = []
        for index in np.array(indices).flatten():
            x, y, w, h = boxes[int(index)]
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(width, int(x + w)), min(height, int(y + h))
            if x2 <= x1 or y2 <= y1:
                continue
            # A weak, clipped object at the camera border is ambiguous (e.g. a
            # wristwatch/hand cut by the frame). Require strong model evidence
            # there; do not convert a partial low-confidence shape into a flag.
            if (x1 <= 1 or y1 <= 1 or x2 >= width-1 or y2 >= height-1) and scores[int(index)] < 0.75:
                continue
            result.append(
                {
                    "box": [
                        x1, y1, x2 - x1, y2 - y1,
                    ],
                    "confidence": scores[int(index)],
                }
            )
        return result

    @staticmethod
    def iris_ratio(points, iris, a, b):
        ia, ib, ip = points[a], points[b], points[iris]
        dx = ib.x - ia.x
        dy = ib.y - ia.y
        return ((ip.x - ia.x) * dx + (ip.y - ia.y) * dy) / max(dx * dx + dy * dy, 1e-6)

    def analyze(self, frame):
        start = time.perf_counter()
        result = {
            "faces": 0,
            "phone": False,
            "phones": [],
            "gaze": "unknown",
            "yaw": None,
            "pitch": None,
            "iris": None,
            "quality": "unknown",
            "confidence": 0.0,
        }
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        result.update(brightness=round(brightness, 1), sharpness=round(sharpness, 1))
        result["quality"] = (
            "dark" if brightness < 35 else "blur" if sharpness < 12 else "good"
        )
        if not self.ready:
            result["error"] = self.error
            return result, frame
        phones = self.phones(frame)
        result["phones"] = phones
        result['frame_size']=[frame.shape[1],frame.shape[0]]
        result["phone"] = bool(phones)
        result["phone_sample_at"] = self.phone_sample_at
        result["phone_confidence"] = max((p["confidence"] for p in phones), default=0)
        result["phone_raised"] = any(
            (p["box"][1] + p["box"][3] / 2) < frame.shape[0] * 0.6 for p in phones
        )
        timestamp = max(self.last_ts + 1, int(time.monotonic() * 1000))
        self.last_ts = timestamp
        image = self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB,
            data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
        )
        detection = self.detector.detect_for_video(image, timestamp)
        landmarks = self.landmarker.detect_for_video(image, timestamp)
        result["faces"] = max(len(detection.detections), len(landmarks.face_landmarks))
        if landmarks.face_landmarks:
            points = landmarks.face_landmarks[0]
            def eye_ratio(ids):
                p=[np.array([points[i].x,points[i].y]) for i in ids]
                return float((np.linalg.norm(p[1]-p[5])+np.linalg.norm(p[2]-p[4]))/(2*max(np.linalg.norm(p[0]-p[3]),1e-6)))
            result['eye_openness']=(eye_ratio([33,160,158,133,153,144])+eye_ratio([362,385,387,263,373,380]))/2
            xs = [p.x for p in points]
            ys = [p.y for p in points]
            result["face_box"] = [min(xs), min(ys), max(xs), max(ys)]
            if landmarks.facial_transformation_matrixes:
                rotation = np.array(landmarks.facial_transformation_matrixes[0])[:3, :3]
                result["yaw"] = math.degrees(math.atan2(rotation[0, 2], rotation[2, 2]))
                result["pitch"] = math.degrees(
                    math.atan2(
                        -rotation[1, 2],
                        math.sqrt(rotation[1, 0] ** 2 + rotation[1, 1] ** 2),
                    )
                )
            if len(points) > 477:
                result["iris"] = (
                    self.iris_ratio(points, 468, 33, 133)
                    + self.iris_ratio(points, 473, 362, 263)
                ) / 2
            if (
                result["yaw"] is not None
                and result["iris"] is not None
                and result["quality"] == "good"
            ):
                self.samples.append(
                    (time.monotonic(), [result["yaw"], result["pitch"], result["iris"]])
                )
                result["gaze"] = self.classify(
                    [result["yaw"], result["pitch"], result["iris"]]
                )
                result["confidence"] = max(
                    (
                        d.categories[0].score
                        for d in detection.detections
                        if d.categories
                    ),
                    default=0,
                )
        annotated = frame.copy()
        if self.identity and self.identity.reference is not None:
            center = self.calibration.get("center")
            pose_ok = not center or (
                result["yaw"] is not None
                and abs(result["yaw"] - center[0]) < 25
                and abs(result["pitch"] - center[1]) < 20
            )
            if result["faces"] == 1 and result["quality"] == "good" and pose_ok:
                if time.monotonic() - self.last_identity_at >= 0.7:
                    self.identity_result = self.identity.compare(
                        frame, self.identity_threshold
                    )
                    self.last_identity_at = time.monotonic()
            else:
                self.identity_result = {"state": "not_comparable", "score": None}
            result["identity"] = dict(self.identity_result)
        if result['faces']==1 and detection.detections and result['quality']=='good' and self.presentation:
            box=detection.detections[0].bounding_box
            result['presentation']=self.presentation.analyze(frame,[box.origin_x,box.origin_y,box.width,box.height])
        for phone in phones:
            x, y, w, h = phone["box"]
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 160, 255), 2)
            cv2.putText(
                annotated,
                f"PHONE {phone['confidence']:.2f}",
                (x, max(20, y - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 160, 255),
                1,
            )
        for face in detection.detections:
            box = face.bounding_box
            cv2.rectangle(
                annotated,
                (box.origin_x, box.origin_y),
                (box.origin_x + box.width, box.origin_y + box.height),
                (180, 230, 60),
                1,
            )
        result["inference_ms"] = round((time.perf_counter() - start) * 1000, 1)
        return result, annotated

    def capture_calibration(self, direction):
        values = [v for stamp, v in self.samples if time.monotonic() - stamp < 2.5]
        if len(values) < 5:
            raise ValueError(
                "Бет анық көрінген күйде бағытқа кемінде 2 секунд қараңыз."
            )
        self.calibration[direction] = np.median(values, axis=0).tolist()
        self.samples.clear()
        return self.calibration

    def classify(self, vector):
        if "center" not in self.calibration:
            return "uncalibrated"
        current = np.array(vector)
        center = np.array(self.calibration["center"])
        delta = current - center
        if abs(delta[0]) < 12 and abs(delta[1]) < 10 and abs(delta[2]) < 0.10:
            return "center"
        if delta[1] >= 12 and abs(delta[0]) < 20:
            return "down"
        if delta[1] <= -12:
            return "away"
        if abs(delta[0]) >= 15 or abs(delta[2]) >= 0.14:
            return "away"
        distances = {}
        for direction, point in self.calibration.items():
            distances[direction] = float(
                np.linalg.norm((current - np.array(point)) / np.array([18, 15, 0.18]))
            )
        best = min(distances, key=distances.get)
        if best != "center" and distances[best] < 2.0:
            return best
        return "away"

    def reset(self):
        self.phone_sample_at = 0
        self.phone_crop_cycle = 0
        self.phone_cache = []
        self.calibration = {}
        self.samples.clear()
        self.identity_result = {"state": "not_enrolled", "score": None}
        if self.identity:
            self.identity.reference = None
        self.last_identity_at = 0

    def close(self):
        for task in (self.landmarker, self.detector):
            if task:
                task.close()


class TemporalRules:
    def __init__(self):
        self.active = {}
        self.last_frame = None

    def update(self, signals, policy, stamp):
        if self.last_frame is not None and stamp - self.last_frame > 2:
            self.active.clear()
        self.last_frame = stamp
        mapping = {
            "face_absent": (
                signals.get("faces", 0) == 0 and signals.get("quality") == "good",
                policy.absence_seconds,
            ),
            "multiple_faces": (signals.get("faces", 0) > 1, policy.multi_face_seconds),
            "identity_mismatch": (
                signals.get("identity", {}).get("state") == "mismatch",
                policy.identity_seconds,
            ),
            "gaze_down": (
                signals.get("gaze") == "down" and not policy.paper_allowed
                and signals.get("faces") == 1 and signals.get("quality") == "good"
                and signals.get("confidence", 0) >= 0.75,
                policy.gaze_seconds,
            ),
            "gaze_side": (
                signals.get("gaze") in ("left", "right", "away")
                and signals.get("faces") == 1 and signals.get("quality") == "good"
                and signals.get("confidence", 0) >= 0.75,
                policy.gaze_seconds,
            ),
            "camera_obscured": (signals.get("quality") in ("dark", "blur"), 3.0),
            "presentation_attack": (signals.get('faces') == 1 and signals.get('presentation',{}).get('state') == 'spoof', 6.0),
        }
        events = self.update_phone(signals, policy, stamp)
        for kind, (condition, threshold) in mapping.items():
            if not condition:
                item = self.active.get(kind)
                if item and item["emitted"]:
                    item.setdefault("clear_since", stamp)
                    if stamp - item["clear_since"] >= 1:
                        self.active.pop(kind, None)
                else:
                    self.active.pop(kind, None)
                continue
            item = self.active.setdefault(kind, {"start": stamp, "emitted": False})
            item.pop("clear_since", None)
            if stamp - item["start"] >= threshold and not item["emitted"]:
                item["emitted"] = True
                events.append(
                    (
                        kind,
                        {
                            "duration_seconds": round(stamp - item["start"], 2),
                            "signals": signals,
                            "threshold_seconds": threshold,
                        },
                    )
                )
        return events

    def update_phone(self, signals, policy, stamp):
        sample = signals.get("phone_sample_at", stamp)
        item = self.active.get("phone_detected")
        if item and sample == item.get("sample"):
            return []  # Cached detections cannot become extra independent evidence.
        if not signals.get("phone", False):
            if item:
                item["sample"] = sample
                item.setdefault("clear_since", stamp)
                grace = 1.0 if item['emitted'] else 1.8
                if stamp - item["last_positive"] >= grace:
                    self.active.pop("phone_detected", None)
            return []
        if item is None:
            item = {"start": stamp, "last_positive": stamp, "samples": 0, "emitted": False}
            self.active["phone_detected"] = item
        item.update(sample=sample, last_positive=stamp, samples=item["samples"] + 1)
        item.pop("clear_since", None)
        if stamp - item["start"] >= policy.phone_seconds and item["samples"] >= 3 and not item["emitted"]:
            item["emitted"] = True
            return [("phone_detected", {"duration_seconds": round(stamp - item["start"], 2),
                     "threshold_seconds": policy.phone_seconds, "independent_samples": item["samples"],
                     "signals": signals})]
        return []
