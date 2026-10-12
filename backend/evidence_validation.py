"""Bound untrusted evidence before ZIP decompression or teacher playback."""
import io
import json
import zipfile
import math
import re


def seconds(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and 0<=value<=120


def validate_clip(raw, event_id):
    if len(raw)>12_000_000:
        raise ValueError('Evidence budget exceeded')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files=archive.infolist()
            names=[f.filename for f in files]
            if len(files)>1000 or len(names)!=len(set(names)) or sum(f.file_size for f in files)>24_000_000:
                raise ValueError('Unsafe evidence archive size')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>200_000:
                raise ValueError('Invalid evidence manifest')
            for f in files:
                if f.file_size>2_000_000 and f.filename!='audio.wav':
                    raise ValueError('Oversized evidence frame')
                if f.flag_bits&1 or (f.filename not in ('manifest.json','audio.wav') and not re.fullmatch(r'(camera|screen)/[0-9]{4}\.jpg',f.filename)):
                    raise ValueError('Invalid evidence entry')
            value=json.loads(archive.read('manifest.json'),parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Non-finite manifest')))
            if not isinstance(value,dict) or value.get('event_id')!=event_id:
                raise ValueError('Evidence belongs to another event')
            tracks=value.get('tracks') or {'camera':value.get('frames',[])}
            if not isinstance(tracks,dict) or not tracks or set(tracks)-{'camera','screen'}:
                raise ValueError('Invalid evidence tracks')
            if not seconds(value.get('event_offset',0)):raise ValueError('Invalid event offset')
            if value.get('primary','camera') not in ('camera','screen'):raise ValueError('Invalid primary track')
            for track,rows in tracks.items():
                if not isinstance(rows,list) or len(rows)>1000:raise ValueError('Invalid evidence track')
                for row in rows:
                    if not isinstance(row,dict) or row.get('file') not in names or not row['file'].startswith(track+'/') or not seconds(row.get('time')):raise ValueError('Invalid evidence frame reference')
                if any(a['time']>b['time'] for a,b in zip(rows,rows[1:])):raise ValueError('Unordered evidence frames')
            audio=value.get('audio')
            if audio is not None and (not isinstance(audio,dict) or audio.get('file')!='audio.wav' or 'audio.wav' not in names or not seconds(audio.get('time')) or not seconds(audio.get('duration')) or audio.get('sample_rate')!=16000):
                raise ValueError('Invalid evidence audio')
            return value
    except (zipfile.BadZipFile,KeyError,TypeError,AttributeError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ValueError('Invalid evidence archive') from exc
