from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Segment(Strict):
    type: str
    data: dict = Field(default_factory=dict)

class MessageIn(Strict):
    account_id: str = 'local'
    group_id: str
    group_name: str | None = None
    message_id: str
    sent_at: datetime
    source: Literal['paste','import','qq','demo','image'] = 'import'
    text: str = Field(default='', max_length=20000)
    segments: list[Segment] = Field(default_factory=list, max_length=100)
    reply_to: str | None = None
    reply_text: str | None = Field(default=None, max_length=12000)
    @field_validator('account_id','group_id','message_id','reply_to', mode='before')
    @classmethod
    def ids(cls,v):
        if v is None:return v
        if not isinstance(v,(str,int)) or isinstance(v,bool):raise ValueError('ID 必须是字符串或整数')
        return str(v)
    @field_validator('sent_at')
    @classmethod
    def aware(cls,v):
        if v.tzinfo is None: raise ValueError('发送时间必须带时区，例如 +08:00')
        return v.astimezone(TZ)

class Moment(Strict):
    value: str
    precision: Literal['date','minute']
    raw: str
    evidence: str
    assumption: str | None = None
    needs_confirmation: bool = False
    @model_validator(mode='after')
    def valid(self):
        if self.precision == 'date': date.fromisoformat(self.value)
        else:
            d=datetime.fromisoformat(self.value)
            if d.tzinfo is None or d.utcoffset().total_seconds()!=28800:
                raise ValueError('时间必须明确 +08:00')
        if not self.raw or not self.evidence:raise ValueError('日期必须有原文证据')
        return self

class Schedule(Strict):
    slot_id: str | None = None
    kind: Literal['registration_start','registration_deadline','material_deadline','activity']
    start: Moment
    end: Moment | None = None
    label: str | None = None
    @model_validator(mode='after')
    def valid(self):
        if self.end:
            if self.kind != 'activity':raise ValueError('只有活动场次允许结束时间')
            if self.end.value < self.start.value:raise ValueError('结束早于开始')
        return self

class Extracted(Strict):
    is_event: bool = True
    title: str = Field(min_length=1,max_length=150)
    category: str = '其他'
    organizer: str | None = None
    eligibility: str | None = None
    registration_method: str | None = None
    original_links: list[str] = Field(default_factory=list, max_length=20)
    contact: str | None = None
    fee: str | None = None
    location: str | None = None
    status: Literal['active','postponed','cancelled'] = 'active'
    personal_status: Literal['interested','to_register','registered','abandoned'] = 'interested'
    schedules: list[Schedule] = Field(default_factory=list,max_length=30)
    missing_fields: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    evidence: dict[str,str] = Field(default_factory=dict)
    action: Literal['new','update','cancel'] = 'new'
    target_title: str | None = None

class EditIn(Strict):
    event: Extracted
    locked_fields: list[str] = Field(default_factory=list)
    confirmed: bool = False
    ignored: bool = False
    reason: str = Field(default='人工修改', max_length=500)
    expected_version: int

class AssociateIn(Strict):
    message_id: int
    expected_version: int

class SplitIn(Strict):
    message_ids: list[int] = Field(min_length=1)
    event: Extracted
    expected_version: int
