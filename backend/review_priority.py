"""Explainable duration-based review queue, never guilt or an exam grade."""
from .event_policy import review_category
from .observation_scoring import SCALE,event_points,episode_key

def review_summary(events,journal_count=None):
    observations=[];systems=0;technical=0
    for event in events:
        category=review_category(event['kind'],event.get('detail'))
        if category=='observation':observations.append(event)
        elif category=='system':systems+=1
        else:technical+=1
    pending=[e for e in observations if e.get('verdict','pending')=='pending']
    groups={}
    for event in pending:
        key=episode_key(event)
        if key not in groups or event_points(event)>=event_points(groups[key]):groups[key]=event
    reasons={}
    for event in groups.values():
        points=event_points(event)
        reason=reasons.setdefault(event['kind'],{'kind':event['kind'],'count':0,'points':0,'weight':0})
        reason['count']+=1;reason['points']+=points;reason['weight']=max(reason['weight'],points)
    raw_score=sum(event_points(e) for e in groups.values());score=min(100,raw_score)
    total=len(events) if journal_count is None else journal_count
    return {'score':score,'total_points':raw_score,'level':'high' if score>=60 else 'medium' if score>=25 else 'low' if score else 'clear',
        'pending_count':len(pending),'pending_episodes':len(groups),'observation_count':len(observations),
        'system_count':systems,'technical_count':max(technical,total-len(observations)-systems),
        'reviewed_count':len(observations)-len(pending),
        'reasons':sorted(reasons.values(),key=lambda r:(-r['points'],-r['count'],r['kind'])),
        'scale':SCALE,'meaning':'Maximum duration tier per pending episode; review priority, not cheating probability or an exam grade.'}
