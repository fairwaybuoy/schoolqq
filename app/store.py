import hashlib,json,sqlite3,time,uuid
from datetime import datetime,timedelta
from pathlib import Path
from .models import MessageIn,Extracted,TZ

def now():return datetime.now(TZ).isoformat()
def dump(x):return json.dumps(x,ensure_ascii=False)

class Conflict(Exception):pass

class Store:
    def __init__(self,data_dir):
        self.path=Path(data_dir);self.path.mkdir(parents=True,exist_ok=True)
        self.conn=sqlite3.connect(self.path/'schedule.sqlite3',check_same_thread=False)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute('PRAGMA secure_delete=ON');self.conn.execute('PRAGMA journal_mode=WAL');self.conn.execute('PRAGMA busy_timeout=5000')
        for f in sorted((Path(__file__).parent.parent/'migrations').glob('*.sql')):self.conn.executescript(f.read_text(encoding='utf-8'))
        self.conn.commit()
    _INSERT_MESSAGE = (
        'INSERT INTO messages(account_id,group_id,message_id,source,sent_at,payload,text,fingerprint,received_at) '
        'VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,group_id,message_id) DO NOTHING'
    )

    @staticmethod
    def _message_values(message, received_at):
        text = message.text
        normalized = text.strip()
        fingerprint = hashlib.sha256(normalized.encode()).hexdigest() if normalized else None
        return (message.account_id, message.group_id, message.message_id, message.source,
                message.sent_at.isoformat(), dump(message.model_dump(mode='json')), text,
                fingerprint, received_at)

    def ingest(self, m: MessageIn, groups):
        if m.group_id not in groups:
            return {'state': 'filtered', 'id': None}
        with self.conn:
            cursor = self.conn.execute(self._INSERT_MESSAGE, self._message_values(m, now()))
        row = self.conn.execute(
            'SELECT id,state FROM messages WHERE account_id=? AND group_id=? AND message_id=?',
            (m.account_id, m.group_id, m.message_id),
        ).fetchone()
        return {'id': row['id'], 'state': row['state'], 'duplicate': cursor.rowcount == 0}

    def history_cursor(self, account_id, group_id):
        row = self.conn.execute(
            "SELECT message_id,sent_at FROM messages WHERE account_id=? AND group_id=? AND source='qq' "
            "ORDER BY sent_at,id LIMIT 1",
            (account_id, group_id),
        ).fetchone()
        if not row:
            return None
        checkpoint = self.runtime(f'history-cursor:{account_id}:{group_id}')
        if checkpoint:
            sent_at, _, message_id = json.loads(checkpoint)
            if sent_at <= row['sent_at']:
                return message_id
        return row['message_id']

    def ingest_history(self, messages, account_id, group_id, oldest_sequence, from_cursor):
        """按发送顺序追加同群消息，并在同一事务中保存续读位置。"""
        received_at = now()
        values = [self._message_values(message, received_at) for message in messages]
        if not values:
            return 0, 0
        if any(row[:2] != (account_id, group_id) for row in values):
            raise ValueError('历史消息必须来自同一账号和群')
        key = f'history-cursor:{account_id}:{group_id}'
        sent_at, message_id = values[0][4], values[0][2]
        checkpoint = (sent_at, oldest_sequence, message_id)
        with self.conn:
            inserted = self.conn.executemany(self._INSERT_MESSAGE, values).rowcount
            stored = self.runtime(key)
            advance = not stored
            if stored:
                previous_at, previous_seq, previous_id = json.loads(stored)
                if oldest_sequence and previous_seq:
                    older_in_same_second = oldest_sequence < previous_seq
                else:
                    older_in_same_second = from_cursor == previous_id and message_id != previous_id
                advance = sent_at < previous_at or (sent_at == previous_at and older_in_same_second)
            if advance:
                self.conn.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)', (key, dump(checkpoint)))
        return inserted, len(values) - inserted

    def recover(self):
        with self.conn:self.conn.execute("UPDATE messages SET state='pending' WHERE state='processing'")
        self.runtime('connected','false')
        self.runtime('gap','程序启动前、离线及断线期间消息可能缺失；可在数据与连接页按需读取群历史，无法保证补齐所有缺口')
    def claim(self):
        with self.conn:
            r=self.conn.execute("SELECT * FROM messages WHERE state='pending' AND next_attempt<=? ORDER BY id LIMIT 1",(time.time(),)).fetchone()
            if r:self.conn.execute("UPDATE messages SET state='processing',attempts=attempts+1 WHERE id=?",(r['id'],))
        return dict(r) if r else None
    def finish(self,mid,state,error=None):
        with self.conn:self.conn.execute('UPDATE messages SET state=?,error=? WHERE id=?',(state,error,mid))
    def fail(self,mid,error,max_attempts):
        attempts=self.conn.execute('SELECT attempts FROM messages WHERE id=?',(mid,)).fetchone()[0]
        with self.conn:self.conn.execute('UPDATE messages SET state=?,error=?,next_attempt=? WHERE id=?',('failed' if attempts>=max_attempts else 'pending',error,time.time()+min(60,2**attempts),mid))
    def retry(self,mid):
        with self.conn:self.conn.execute("UPDATE messages SET state='pending',attempts=0,error=NULL,next_attempt=0 WHERE id=? AND state IN ('failed','review')",(mid,))
    def runtime(self,key,value=None):
        if value is not None:
            with self.conn:self.conn.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',(key,value))
        r=self.conn.execute('SELECT value FROM runtime WHERE key=?',(key,)).fetchone()
        return r[0] if r else None
    def budget(self,day):
        r=self.conn.execute('SELECT calls FROM budget WHERE day=?',(day,)).fetchone();return r[0] if r else 0
    def consume(self,day):
        with self.conn:self.conn.execute('INSERT INTO budget VALUES(?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1',(day,))
    def context(self,group,account):
        rows=self.conn.execute('SELECT id,data FROM events WHERE group_id=? AND account_id=? AND ignored=0 ORDER BY updated_at DESC LIMIT 5',(group,account)).fetchall()
        return [{'id':r['id'],'title':json.loads(r['data'])['title'],'schedules':[{'kind':x['kind'],'value':x['start']['value'],'precision':x['start']['precision']} for x in json.loads(r['data'])['schedules'][:8]]} for r in rows]
    def event(self, eid):
        return next(iter(self._events(eid=eid)), None)

    def events(self, *, include_history=True):
        return self._events(include_history=include_history)

    def _events(self, eid=None, *, include_history=True):
        where_event, where_related, params = '', '', ()
        if eid is not None:
            where_event, where_related, params = ' WHERE id=?', ' WHERE event_id=?', (eid,)
        events = {}
        for row in self.conn.execute('SELECT * FROM events' + where_event + ' ORDER BY updated_at DESC', params):
            event = dict(row)
            event['data'] = json.loads(row['data'])
            event['locked'] = json.loads(row['locked'])
            event['sources'] = []
            event['history'] = []
            events[row['id']] = event
        if not events:
            return []
        if eid is None:
            where_related = ' WHERE event_id IN (SELECT id FROM events)'
        sources = self.conn.execute(
            'SELECT event_id,id,payload,text,state,error,recalled FROM messages' + where_related + ' ORDER BY event_id,id',
            params,
        )
        for row in sources:
            source = dict(row)
            event = events.get(source.pop('event_id'))
            if event is not None:
                source['payload'] = json.loads(row['payload'])
                event['sources'].append(source)
        if include_history:
            for row in self.conn.execute('SELECT * FROM versions' + where_related + ' ORDER BY event_id,version', params):
                event = events.get(row['event_id'])
                if event is not None:
                    event['history'].append({**dict(row), 'data': json.loads(row['data'])})
        return list(events.values())

    def _save(self,eid,group,account,data,version,reason,mid=None,locked=None,confirmed=False,ignored=False):
        for schedule in data.get('schedules',[]):
            if not schedule.get('slot_id'):schedule['slot_id']=str(uuid.uuid4())
        self.conn.execute('INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?,?,?,?)',(eid,group,account,dump(data),version,dump(locked or []),int(confirmed),int(ignored),now()))
        self.conn.execute('INSERT INTO versions(event_id,version,data,reason,message_id,created_at) VALUES(?,?,?,?,?,?)',(eid,version,dump(data),reason,mid,now()))
    def apply(self,row,ex:Extracted,forced=None):
        mid=row['id'];d=ex.model_dump(mode='json');
        for schedule in d['schedules']:schedule['slot_id']=None
        group=row['group_id'];account=row['account_id']
        if forced:
            old=self.event(forced)
            if not old or old['group_id']!=group or old['account_id']!=account:raise Conflict('关联必须来自同一账号和群')
        else:old=None
        # 完全相同正文、同账号同群才重复归并，不按标题相似归并。
        if not old and row['fingerprint'] and ex.action=='new':
            duplicate=self.conn.execute('SELECT event_id FROM messages WHERE fingerprint=? AND account_id=? AND group_id=? AND id!=? AND event_id IS NOT NULL AND state IN (\'done\',\'review\') ORDER BY id LIMIT 1',(row['fingerprint'],account,group,mid)).fetchone()
            if duplicate:old=self.event(duplicate[0])
        if not old and ex.action!='new':
            payload=json.loads(row['payload'])
            if payload.get('reply_to'):
                r=self.conn.execute('SELECT event_id FROM messages WHERE account_id=? AND group_id=? AND message_id=?',(account,group,payload['reply_to'])).fetchone()
                if r and r[0]:old=self.event(r[0])
            if not old:
                matches = [candidate['id'] for candidate in self.conn.execute(
                    "SELECT id FROM events WHERE group_id=? AND account_id=? AND ignored=0 "
                    "AND json_extract(data,'$.title')=? ORDER BY updated_at DESC",
                    (group, account, ex.target_title),
                )]
                # 需明确指代或完整赛事名，且唯一候选。无指代短变更保留待关联。
                title = ex.target_title or ''
                if len(matches) == 1 and ('该' + title in row['text'] or len(title) >= 5):
                    old = self.event(matches[0])
                if not old:
                    with self.conn:
                        self.conn.execute(
                            "UPDATE messages SET state='review',extracted=?,error=? WHERE id=?",
                            (dump(d), dump({'reason': '关联不明，请选择活动或拆为新活动',
                                            'candidate_ids': matches}), mid),
                        )
                    return None
        if old:
            eid=old['id'];merged=old['data'].copy();review=[];locked=old['locked']
            if ex.action=='new' and not forced:
                reason='重复正文转发（保留来源）'
            else:
                # 多截止/场次时不猜哪个被改，保留原值并提示人工。
                incoming={x['kind'] for x in d['schedules']}
                if 'schedules'in locked:review.append('时间字段已锁定，自动变更未覆盖')
                elif any(sum(x['kind']==k for x in merged['schedules'])>1 or sum(x['kind']==k for x in d['schedules'])>1 for k in incoming):review.append('存在多个同类日期，请人工选择要变更的场次/截止')
                elif incoming:
                    for schedule in d['schedules']:
                        prior=[x for x in merged['schedules'] if x['kind']==schedule['kind']]
                        schedule['slot_id']=prior[0].get('slot_id') if len(prior)==1 and sum(x['kind']==schedule['kind'] for x in d['schedules'])==1 else None
                    merged['schedules']=[x for x in merged['schedules'] if x['kind'] not in incoming]+d['schedules']
                for k in ['organizer','eligibility','registration_method','contact','fee','location']:
                    if d[k] is not None:
                        if k in locked:review.append(k+'已锁定，未覆盖')
                        elif merged[k] is not None and merged[k]!=d[k]:review.append(k+'冲突，未覆盖')
                        else:merged[k]=d[k];merged['evidence'][k]=d['evidence'].get(k,'')
                if ex.action=='cancel':
                    if 'status' in locked:review.append('活动状态已锁定')
                    else:merged['status']='cancelled';merged['evidence']['status']=d['evidence'].get('status','')
                elif ex.status=='postponed' and 'status' not in locked:merged['status']='postponed'
                merged['review_reasons']=list(dict.fromkeys(d['review_reasons']+review))
                merged['missing_fields']=[k for k in merged['missing_fields'] if k!='registration_deadline' or not any(x['kind']=='registration_deadline' for x in merged['schedules'])]
                reason='人工关联变更' if forced else '通知变更（旧版本保留）'
            version=old['version']+1
            confirmed=bool(old['confirmed']) if reason.startswith('重复') else False
            with self.conn:
                self._save(eid,group,account,merged,version,reason,mid,locked,confirmed,old['ignored'])
                self.conn.execute('UPDATE messages SET event_id=?,extracted=?,state=?,error=NULL WHERE id=?',(eid,dump(d),'review' if merged['review_reasons'] and not confirmed else 'done',mid))
            return eid
        eid=str(uuid.uuid4())
        with self.conn:
            self._save(eid,group,account,d,1,'新通知',mid)
            self.conn.execute('UPDATE messages SET event_id=?,extracted=?,state=?,error=NULL WHERE id=?',(eid,dump(d),'review' if d['review_reasons'] else 'done',mid))
        return eid
    def edit(self,eid,edit):
        old=self.event(eid)
        if not old:raise KeyError(eid)
        if old['version']!=edit.expected_version:raise Conflict('活动已更新，请刷新后重试')
        valid=set(Extracted.model_fields)
        if any(k not in valid for k in edit.locked_fields):raise Conflict('未知锁定字段')
        d=edit.event.model_dump(mode='json')
        if edit.confirmed:
            d['review_reasons']=[]
            for x in d['schedules']:
                for k in ['start','end']:
                    if x.get(k):x[k]['needs_confirmation']=False
        with self.conn:
            self._save(eid,old['group_id'],old['account_id'],d,old['version']+1,edit.reason,None,edit.locked_fields,edit.confirmed,edit.ignored)
            if edit.confirmed:self.conn.execute("UPDATE messages SET state='done' WHERE event_id=? AND state='review'",(eid,))
        return self.event(eid)
    def recall(self,account,group,message_id):
        with self.conn:
            self.conn.execute('UPDATE messages SET recalled=1 WHERE account_id=? AND group_id=? AND message_id=?',(account,group,message_id))
            r=self.conn.execute('SELECT event_id FROM messages WHERE account_id=? AND group_id=? AND message_id=?',(account,group,message_id)).fetchone()
            if r and r[0]:
                e=self.event(r[0]);d=e['data'];d['review_reasons']=list(dict.fromkeys(d['review_reasons']+['来源已撤回，请核对；不等于活动取消']))
                self._save(e['id'],group,account,d,e['version']+1,'来源消息撤回',None,e['locked'],False,e['ignored'])
    def pending(self):
        return [{**dict(r),'payload':json.loads(r['payload']),'extracted':json.loads(r['extracted']) if r['extracted'] else None} for r in self.conn.execute("SELECT * FROM messages WHERE state IN ('pending','processing','failed','review') ORDER BY id DESC LIMIT 200")]
    def stats(self):
        counts={r[0]:r[1] for r in self.conn.execute('SELECT state,COUNT(*) FROM messages GROUP BY state')}
        last=self.conn.execute('SELECT MAX(received_at) FROM messages WHERE source=\'qq\'').fetchone()[0]
        return {'counts':counts,'last_message':last,'connected':self.runtime('connected')=='true','membership':json.loads(self.runtime('membership') or '{}'),'plain_message_probe':json.loads(self.runtime('plain_message_probe') or '{}'),'gap':self.runtime('gap'),'last_disconnect':self.runtime('last_disconnect'),'last_connect':self.runtime('last_connect')}
    def purge(self,days=None,mid=None):
        if mid is not None:
            state=self.conn.execute('SELECT state FROM messages WHERE id=?',(mid,)).fetchone()
            if state and state[0]=='processing':raise Conflict('消息正在处理，请完成后删除')
            rows=self.conn.execute('SELECT id,event_id,payload FROM messages WHERE id=?',(mid,)).fetchall()
        else:rows=self.conn.execute("SELECT id,event_id,payload FROM messages WHERE received_at<? AND state!='processing'",((datetime.now(TZ)-timedelta(days=days)).isoformat(),)).fetchall()
        def scrub(d):
            d['evidence']={};d['original_links']=[]
            for x in d.get('schedules',[]):
                for k in ['start','end']:
                    if x.get(k):x[k]['raw']='[原文已删除]';x[k]['evidence']='[原文已删除]'
            return d
        with self.conn:
            for r in rows:
                p=json.loads(r['payload'])
                for seg in p.get('segments',[]):
                    f=seg.get('data',{}).get('local_file')
                    if f and Path(f).name==f:(self.path/'images'/f).unlink(missing_ok=True)
                p['text']='[原文已删除]';p['segments']=[];p['reply_text']=None
                self.conn.execute('UPDATE messages SET text=?,payload=?,extracted=NULL,fingerprint=NULL WHERE id=?',('[原文已删除]',dump(p),r['id']))
                if r['event_id']:
                    e=self.event(r['event_id']);self.conn.execute('UPDATE events SET data=? WHERE id=?',(dump(scrub(e['data'])),r['event_id']))
                    for v in e['history']:self.conn.execute('UPDATE versions SET data=? WHERE id=?',(dump(scrub(v['data'])),v['id']))
        self.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)');self.conn.execute('VACUUM')
        return len(rows)
    def backup(self,target):
        out=sqlite3.connect(target);self.conn.backup(out);out.close()

