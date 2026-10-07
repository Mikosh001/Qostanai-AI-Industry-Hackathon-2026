"""Passive local presentation-attack scoring; observations require human review."""
import time
import cv2
import numpy as np


class PresentationDetector:
    def __init__(self, models):
        import onnxruntime as ort
        options=ort.SessionOptions();options.intra_op_num_threads=1
        self.models=[(ort.InferenceSession(str(models/name),sess_options=options,providers=['CPUExecutionProvider']),scale)
                     for name,scale in [('MiniFASNetV2.onnx',2.7),('MiniFASNetV1SE.onnx',4.0)]]
        self.last_at=0;self.result={'state':'unknown','score':None,'sample_at':0}

    @staticmethod
    def crop(frame, box, scale):
        h,w=frame.shape[:2];x,y,bw,bh=box
        scale=min((h-1)/max(bh,1),(w-1)/max(bw,1),scale)
        cw,ch=bw*scale,bh*scale;cx,cy=x+bw/2,y+bh/2
        x1=max(0,min(w-1-cw,cx-cw/2));y1=max(0,min(h-1-ch,cy-ch/2))
        return cv2.resize(frame[int(y1):int(y1+ch)+1,int(x1):int(x1+cw)+1],(80,80))

    def analyze(self, frame, box):
        now=time.monotonic()
        if now-self.last_at<0.35:return self.result
        scores=[]
        for model,scale in self.models:
            image=self.crop(frame,box,scale).astype(np.float32)
            tensor=np.ascontiguousarray(image.transpose(2,0,1)[None]) # Upstream expects unnormalized BGR 0..255.
            logits=model.run(None,{model.get_inputs()[0].name:tensor})[0].reshape(-1)
            probability=np.exp(logits-logits.max());probability/=probability.sum()
            scores.append(float(probability[1]))
        score=float(np.mean(scores));self.last_at=now
        self.result={'state':'live' if score>=0.65 else 'uncertain' if score>=0.35 else 'spoof',
                     'score':round(score,4),'scores':[round(v,4) for v in scores],'sample_at':now,
                     'model':'MiniFASNetV2+V1SE'}
        return self.result

