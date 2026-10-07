"""Render a 60-second Kazakh walkthrough from captured real application frames."""
from pathlib import Path
import json, bisect, subprocess, re
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

root=Path(__file__).resolve().parent.parent
work=(root/'../../work/demo-v142').resolve()
source=Path((work/'latest-recording.txt').read_text(encoding='utf-8').strip())
meta=json.loads((source/'recording.json').read_text(encoding='utf-8'))
render=source/'render';render.mkdir(exist_ok=True)
output=root.parent/'sergek-demo';output.mkdir(exist_ok=True)
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',24)
heading=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf',28)
brand=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf',30)
small=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',18)
ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
concat=[];count=0;seconds=0
for phase in meta['phases']:
    frames=[f for f in meta['frames'] if f.get('phase')==phase['id']]
    assert frames,phase['title']
    stamps=[f['stamp'] for f in frames]
    # Keep the whole action sequence; waiting is compressed between chapters.
    for tick in range(phase['target']*5):
        t=stamps[0]+(stamps[-1]-stamps[0])*tick/max(1,phase['target']*5-1)
        frame=frames[min(len(frames)-1,bisect.bisect_left(stamps,t))]
        main=Image.open(source/frame['parts'][0]['file']).convert('RGB').resize((1600,900),Image.Resampling.LANCZOS)
        for part in frame['parts'][1:]:
            b=part['bounds'];image=Image.open(source/part['file']).convert('RGB')
            main.paste(image.resize((b['width'],b['height']),Image.Resampling.LANCZOS),(b['x'],b['y']))
        canvas=Image.new('RGB',(1920,1080),'#eff4fd');draw=ImageDraw.Draw(canvas)
        draw.text((160,14),'Sergек',font=brand,fill='#163b70')
        draw.text((1445,22),'Платформаның жұмысы',font=small,fill='#527397')
        canvas.paste(main,(160,64))
        draw.rounded_rectangle((152,972,1768,1066),radius=18,fill='white')
        draw.text((182,980),phase['title'],font=heading,fill='#225ce2')
        draw.text((182,1020),phase['text'],font=font,fill='#173459')
        progress=(seconds+tick/5)/60
        draw.rectangle((0,1074,round(1920*progress),1079),fill='#2861e8')
        name=f'frame-{count:04}.png';canvas.save(render/name)
        concat.extend([f"file '{name}'",'duration 0.2']);count+=1
    seconds+=phase['target']
assert seconds==60
concat.append(f"file 'frame-{count-1:04}.png'")
(render/'frames.txt').write_text('\n'.join(concat)+'\n',encoding='utf-8')
target=output/'Sergек-Demo-1min.mp4'
r=subprocess.run([ffmpeg,'-y','-hide_banner','-f','concat','-safe','0','-i',str(render/'frames.txt'),'-t','60','-vf','fps=30,format=yuv420p','-c:v','libx264','-crf','19','-preset','medium','-movflags','+faststart','-an',str(target)],capture_output=True,text=True)
(source/'encode.log').write_text(r.stderr,encoding='utf-8');assert r.returncode==0,r.stderr[-2000:]
r=subprocess.run([ffmpeg,'-v','error','-i',str(target),'-f','null','-'],capture_output=True,text=True)
assert r.returncode==0 and not r.stderr.strip(),r.stderr
checks={'passed':True,'seconds':60,'resolution':[1920,1080],'codec':'H.264','audio':'Kazakh captions, no narration','source':meta['source'],'phoneEvidenceConfirmed':meta['phoneEvidenceConfirmed'],'framesDecoded':True,'bytes':target.stat().st_size}
(output/'demo-validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
for second in [8,18,29,35,47,54,58]:
    r=subprocess.run([ffmpeg,'-y','-v','error','-ss',str(second),'-i',str(target),'-frames:v','1',str(output/f'preview-{second}.png')],capture_output=True,text=True)
    assert r.returncode==0
print(json.dumps(checks,ensure_ascii=False))
