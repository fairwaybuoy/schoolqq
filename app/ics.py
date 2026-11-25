from collections import defaultdict
from datetime import date,datetime,timedelta
from icalendar import Calendar,Event,Alarm,Timezone
from .models import TZ

LABELS={'registration_start':'报名开始','registration_deadline':'报名截止','material_deadline':'材料截止','activity':'活动'}
def export_ics(events,kind):
    c=Calendar();c.add('prodid','-//QQ班级通知日程助手//ZH');c.add('version','2.0');c.add('x-wr-calname','班级通知 · '+('报名截止' if kind=='deadlines' else '活动时间'))
    c.add_component(Timezone.from_tzinfo(TZ,first_date=date(2025,1,1),last_date=date(2035,1,1)))
    for e in events:
        if e['ignored'] or not e['confirmed']:continue
        data=e['data'];indices=defaultdict(int)
        for s in data['schedules']:
            k=s['kind'];i=indices[k];indices[k]+=1
            if (kind=='deadlines' and k not in ('registration_deadline','material_deadline')) or (kind=='activities' and k!='activity'):continue
            m=s['start']
            if m['needs_confirmation'] or (s.get('end') and s['end']['needs_confirmation']):continue
            ev=Event();ev.add('uid',f'{e["id"]}-{s.get("slot_id") or (k+str(i))}@qq-class.local');ev.add('sequence',e['version']);ev.add('dtstamp',datetime.fromisoformat(e['updated_at']));ev.add('last-modified',datetime.fromisoformat(e['updated_at']));ev.add('summary',f'【{LABELS[k]}】{data["title"]}')
            parse=lambda x:date.fromisoformat(x['value']) if x['precision']=='date' else datetime.fromisoformat(x['value']).astimezone(TZ)
            ev.add('dtstart',parse(m))
            if s.get('end'):
                end=parse(s['end']);ev.add('dtend',end+timedelta(days=1) if s['end']['precision']=='date' else end)
            ev.add('status','CANCELLED' if data['status']=='cancelled' else 'CONFIRMED')
            ev.add('description','来源：班级通知助手。下载导入为快照，更新需重新导入；请核对原通知。')
            if data['location']:ev.add('location',data['location'])
            if m['precision']=='minute' and data['status']!='cancelled':
                a=Alarm();a.add('action','DISPLAY');a.add('description',data['title']);a.add('trigger',timedelta(days=-1));ev.add_component(a)
            c.add_component(ev)
    return c.to_ical()
