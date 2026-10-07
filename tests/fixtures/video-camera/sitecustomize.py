"""Opt-in development recording fixture; never used by the packaged application."""
import os
if os.environ.get('SERGEK_VIDEO_FIXTURE'):
    import time
    from pathlib import Path
    import cv2
    import numpy as np
    folder = Path(os.environ['SERGEK_VIDEO_FIXTURE'])

    class VideoCapture:
        def __init__(self, *args):
            self.images = {}
            for name in ('portrait.jpg', 'lena.jpg', 'phone.jpg'):
                image = cv2.imread(str(folder/name))
                if image is None: raise ValueError('Missing recording fixture '+name)
                h,w = image.shape[:2];scale=min(1280/w,720/h)
                resized=cv2.resize(image,(round(w*scale),round(h*scale)))
                canvas=np.full((720,1280,3),114,np.uint8)
                y=(720-resized.shape[0])//2;x=(1280-resized.shape[1])//2
                canvas[y:y+resized.shape[0],x:x+resized.shape[1]]=resized
                self.images[name]=canvas
        def set(self, *args): pass
        def isOpened(self): return True
        def read(self):
            time.sleep(1/30)
            name=(folder/'choice.txt').read_text().strip()
            return True,self.images.get(name,self.images['portrait.jpg']).copy()
        def release(self): pass

    cv2.VideoCapture=VideoCapture
