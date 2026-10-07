"""Streaming Silero VAD v6.0, 16 kHz. No transcription or speaker identification."""
from pathlib import Path
import numpy as np


class SpeechDetector:
    def __init__(self, models):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(Path(models) / "silero_vad.onnx"),
            sess_options=options, providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)
        self.buffer = np.empty(0, dtype=np.float32)

    def probability(self, samples):
        self.buffer = np.concatenate((self.buffer, samples))
        probabilities = []
        while len(self.buffer) >= 512:
            chunk = self.buffer[:512].reshape(1, 512)
            self.buffer = self.buffer[512:]
            batch = np.concatenate((self.context, chunk), axis=1)
            result, self.state = self.session.run(None, {
                "input": batch, "state": self.state, "sr": np.array(16000, dtype=np.int64)})
            self.context = batch[:, -64:]
            probabilities.append(float(result.item()))
        return float(np.mean(probabilities)) if probabilities else 0.0
