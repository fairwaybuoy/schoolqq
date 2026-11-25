"""保守中文日期解析；不将纯日期补成 23:59，也不使用回放当天日期。"""
import re
from datetime import datetime, timedelta
from .models import Moment, TZ
DATE_RE = re.compile(r'(?:(?:20\d{2})[年/-])?\d{1,2}\s*月\s*\d{1,2}\s*[日号]?|20\d{2}-\d{2}-\d{2}|(?:今天|今晚|明天|后天|本周[一二三四五六日天]|这周[一二三四五六日天]|周[一二三四五六日天])|\d{1,2}\s*[日号]')
TIME_RE = re.compile(r'(\d{1,2})[:：](\d{2})|(?:上午|下午|晚上|中午)?\s*(\d{1,2})点(?:(\d{1,2})分|半)?')

def parse_moment(raw: str, sent: datetime, evidence: str) -> Moment | None:
    sent=sent.astimezone(TZ); m=DATE_RE.search(raw)
    if not m:return None
    token=m.group(); assumption=None; confirm=False
    try:
        if re.fullmatch(r'20\d{2}-\d{2}-\d{2}',token):d=datetime.strptime(token,'%Y-%m-%d').date()
        elif '月' in token:
            nums=[int(x) for x in re.findall(r'\d+',token)]
            if len(nums)==3:y,mo,day=nums
            else:
                y=sent.year; mo,day=nums; assumption=f'未给年份，暂按发送年份 {y}';confirm=True
            d=sent.date().replace(year=y,month=mo,day=day)
        elif token in ('今天','今晚','明天','后天'):
            d=sent.date()+timedelta(days={'今天':0,'今晚':0,'明天':1,'后天':2}[token])
        elif '周' in token:
            wd='一二三四五六日'.index(token[-1].replace('天','日'))
            d=sent.date()+timedelta(days=wd-sent.weekday())
            assumption='按发送时间所在自然周（周一至周日）';confirm=True
        else:
            d=sent.date().replace(day=int(re.search(r'\d+',token).group()))
            assumption=f'未给月份和年份，暂按发送月份 {sent:%Y-%m}';confirm=True
        t=TIME_RE.search(raw[m.end():])
        if t:
            hour=int(t.group(1) or t.group(3));minute=int(t.group(2) or t.group(4) or (30 if '半'in t.group() else 0))
            if any(x in raw for x in ('下午','晚上')) and hour<12:hour+=12
            dt=datetime(d.year,d.month,d.day,hour,minute,tzinfo=TZ)
            return Moment(value=dt.isoformat(timespec='minutes'),precision='minute',raw=raw,evidence=evidence,assumption=assumption,needs_confirmation=confirm)
        if token=='今晚': assumption='今晚未提供具体时刻';confirm=True
        return Moment(value=d.isoformat(),precision='date',raw=raw,evidence=evidence,assumption=assumption,needs_confirmation=confirm)
    except (ValueError,OverflowError):return None
