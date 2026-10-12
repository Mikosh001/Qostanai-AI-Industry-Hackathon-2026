"""Operator-initiated private webcam recording; no protection, microphone or upload.

Clips are test material, not automatic ground truth. Review the full recording
and correct intervals before setting annotation_verified=true in the manifest.
"""
import argparse,json,time
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont

PLAN=[('Обычная работа: руки пустые, смотрите на экран',15,None),
      ('Держите телефон экраном к камере, полностью в центре',12,'front/center'),
      ('Уберите телефон, обычная работа',6,None),
      ('Держите телефон задней стороной к камере, в центре',12,'back/center'),
      ('Уберите телефон, обычная работа',6,None),
      ('Держите телефон экраном к камере возле плеча',12,'front/shoulder'),
      ('Уберите телефон, обычная работа',6,None),
      ('Держите телефон задней стороной возле плеча',12,'back/shoulder'),
      ('Уберите телефон. Покажите ручку и обычный блокнот',15,None)]


def capture(output,index):
    output.mkdir(parents=True,exist_ok=True);file=output/'phone-qa.mp4'
    if file.exists():raise ValueError('Output already exists; choose another directory')
    cap=cv2.VideoCapture(index,cv2.CAP_DSHOW)
    if not cap.isOpened():raise RuntimeError('Camera unavailable; close the other camera application and retry')
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,1280);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,720)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
    writer=None;frames=0;frame_times=[];intervals=[];ranges=[];started=time.monotonic();next_frame=started;aborted=False
    try:
        for message,seconds,group in PLAN:
            began=time.monotonic();first=began-started
            while time.monotonic()-began<seconds:
                okay,frame=cap.read()
                if not okay:raise RuntimeError('Camera stopped')
                if writer is None:
                    h,w=frame.shape[:2];writer=cv2.VideoWriter(str(file),cv2.VideoWriter_fourcc(*'mp4v'),15,(w,h))
                    if not writer.isOpened():raise RuntimeError('Video writer unavailable')
                now=time.monotonic()
                if now>=next_frame:writer.write(frame);frames+=1;frame_times.append(now-started);next_frame=now+1/15
                image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(image)
                draw.rectangle((0,0,image.width,95),fill='#12213d');draw.text((12,12),message,font=font,fill='white');draw.text((12,48),f'{max(0,int(seconds-(now-began)))} сек. | ESC - отмена | Видео хранится только локально',font=font,fill='#96e8ce')
                cv2.imshow('Sergek - camera QA (no Windows restrictions)',cv2.cvtColor(np.array(image),cv2.COLOR_RGB2BGR))
                if cv2.waitKey(1)&0xff==27:aborted=True;break
            end=time.monotonic()-started
            ranges.append({'start':first,'end':end,'instruction':message,'group':group})
            if group:intervals.append({'start':first,'end':end,'group':group})
            if aborted:break
    finally:
        cap.release()
        if writer:writer.release()
        cv2.destroyAllWindows()
    manifest={'annotation_verified':False,'aborted':aborted,'operator_review_required':'Review every interval and negative segment; instructions are not evidence that the object was actually shown',
              'wall_seconds':round(time.monotonic()-started,2),'recorded_frames':frames,'videos':[{'file':file.name,'phone_intervals':intervals,'frame_times':frame_times}],'expected_instruction_ranges':ranges}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Private recording and unverified annotation: '+str(output))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--camera',type=int,default=0)
    args=parser.parse_args();capture(args.output,args.camera)
