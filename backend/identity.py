"""Per-exam photo reference, local SFace embedding comparison. No identity database."""

import cv2
import numpy as np


class FaceIdentity:
    def __init__(self, models):
        self.detector = cv2.FaceDetectorYN.create(
            str(models / "face_detection_yunet.onnx"),
            "",
            (320, 320),
            0.85,
            0.3,
            5000,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            str(models / "face_recognition_sface.onnx"), ""
        )
        self.reference = None

    def feature(self, frame):
        height, width = frame.shape[:2]
        scale = min(640 / width, 480 / height, 1.0)
        image = cv2.resize(frame, (round(width * scale), round(height * scale)))
        self.detector.setInputSize((image.shape[1], image.shape[0]))
        _, faces = self.detector.detect(image)
        if faces is None or len(faces) != 1:
            return None
        aligned = self.recognizer.alignCrop(image, faces[0])
        embedding = self.recognizer.feature(aligned).astype(np.float32).reshape(-1)
        norm = np.linalg.norm(embedding)
        return embedding / norm if norm > 0 else None

    @staticmethod
    def similarity(a, b):
        return float(np.clip(np.dot(a, b), -1, 1))

    def enroll(self, frame):
        embedding = self.feature(frame)
        if embedding is None:
            raise ValueError(
                "Фото үшін камераға тура қарап, бір бетті анық көрсетіңіз."
            )
        self.reference = embedding
        return embedding

    def compare(self, frame, threshold):
        if self.reference is None:
            return {"state": "not_enrolled", "score": None}
        embedding = self.feature(frame)
        if embedding is None:
            return {"state": "not_comparable", "score": None}
        score = self.similarity(self.reference, embedding)
        return {
            "state": "match" if score >= threshold else "mismatch",
            "score": round(score, 4),
            "threshold": threshold,
        }
