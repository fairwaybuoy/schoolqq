from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.extract import rules
from app.history import backfill, to_message
from app.models import TZ
from app.store import Store
from app.worker import Worker


class FakeBot:
    self_id = '123456'

    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    async def get_group_list(self):
        return [{'group_id': 10001}]

    async def call_api(self, name, **params):
        assert name == 'get_group_msg_history'
        assert params['reverseOrder'] is True
        self.calls.append(params)
        items = self.messages
        if 'message_id' in params:
            anchor = next(i for i, m in enumerate(items) if m['message_id'] == params['message_id'])
            items = items[:anchor + 1]
        return {'messages': items[-params['count']:]}


def raw(i):
    return {'group_id': 10001, 'message_id': str(i), 'message_seq': i,
            'time': 1790900000 + i, 'message': [{'type': 'text', 'data': {
                'text': ('商赛 10 月 18 日 18:00 截止报名，10 月 25 日 14:00 比赛' if i == 20
                         else '该商赛报名延至 10 月 20 日 18:00' if i == 100 else f'聊天 {i}')}}]}


@pytest.mark.asyncio
async def test_history_pages_and_idempotence(tmp_path):
    db = Store(tmp_path)
    bot = FakeBot([raw(i) for i in range(1, 121)])
    first = await backfill(bot, db, '10001', 105)
    assert (first['fetched'], first['inserted'], first['duplicates']) == (105, 105, 0)
    assert bot.calls[1]['message_id'] == '21'
    assert db.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 105
    again = await backfill(bot, db, '10001', 105)
    assert (again['inserted'], again['duplicates']) == (0, 105)
    assert db.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 105
    s = Settings(_env_file=None, app_token='a' * 30, onebot_access_token='b' * 30,
                 data_dir=tmp_path, group_whitelist='10001', model_min_interval=0)
    worker = Worker(s, db)
    for _ in range(105):
        await worker.once()
    event = db.events()[0]
    assert len(event['sources']) == 2
    assert all(src['payload']['source'] == 'qq' for src in event['sources'])
    assert any(s['start']['value'] == '2026-10-20T18:00+08:00' for s in event['data']['schedules'])


def test_history_conversion_and_group_guard():
    assert to_message({**raw(1), 'group_id': 20002}, '123456', '10001') is None
    m = to_message(raw(20), '123456', '10001')
    assert m.sent_at == datetime.fromtimestamp(raw(20)['time'], m.sent_at.tzinfo)
    assert '截止报名' in m.text


def test_old_competition_notices_are_kept():
    sent = datetime(2026, 9, 28, tzinfo=TZ)
    # 合成通知，用于验证已过期赛事和缺日期赛事的提取。
    photo = '''【校园光影摄影大赛】开始征稿
👥参与对象：示例高校全体学生
⏰投稿截止：2026年10月7日中午12:00前
✅作品要求：原创实拍，图片JPG/PNG，附带创作说明'''
    play = '''示例高校第十届校园心理情景剧大赛现已启动。
本次比赛面向25-27级学生。'''
    first, second = rules(photo, sent), rules(play, sent)
    assert first.is_event and first.category == '比赛'
    assert [(s.kind, s.start.value) for s in first.schedules] == [('material_deadline', '2026-10-07T12:00+08:00')]
    assert second.is_event and second.category == '比赛'
    assert second.schedules == [] and second.eligibility == '25-27级学生'
    assert 'registration_deadline' in second.missing_fields


def test_history_endpoint_auth_and_membership(tmp_path, monkeypatch):
    s = Settings(_env_file=None, app_token='a' * 30, onebot_access_token='b' * 30,
                 data_dir=tmp_path, group_whitelist='10001,demo-class')
    db = Store(tmp_path)
    bot = FakeBot([raw(i) for i in range(1, 31)])
    monkeypatch.setattr('nonebot.get_bots', lambda: {'123456': bot})
    with TestClient(create_app(s, db, manage_worker=False)) as c:
        assert c.post('/api/history/backfill', json={'group_id': '10001'}).status_code == 401
        assert c.post('/api/login', json={'token': s.app_token}).status_code == 200
        assert c.post('/api/history/backfill', json={'group_id': '20002'}).status_code == 403
        assert c.post('/api/history/backfill', json={'group_id': 'demo-class'}).status_code == 403
        assert c.post('/api/history/backfill', json={'group_id': '10001', 'limit': 2001}).status_code == 422
        r = c.post('/api/history/backfill', json={'group_id': '10001', 'limit': 10})
        assert r.status_code == 200
        assert r.json()['inserted'] == 10
        older = c.post('/api/history/backfill', json={'group_id': '10001', 'limit': 10, 'older': True})
        assert older.status_code == 200 and older.json()['inserted'] == 10
        assert bot.calls[-1]['message_id'] == '21'
        assert db.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 20
        bot.get_group_list = lambda: empty_groups()
        assert c.post('/api/history/backfill', json={'group_id': '10001'}).status_code == 403


async def empty_groups():
    return []


@pytest.mark.asyncio
async def test_large_backfill_and_retry_after_interruption(tmp_path):
    class InterruptedBot(FakeBot):
        async def call_api(self, name, **params):
            if len(self.calls) == 3:
                raise TimeoutError('模拟翻页时断线')
            return await super().call_api(name, **params)

    db = Store(tmp_path)
    messages = [raw(i) for i in range(1, 2051)]
    with pytest.raises(TimeoutError):
        await backfill(InterruptedBot(messages), db, '10001', 2000)
    assert db.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0

    statements = []
    db.conn.set_trace_callback(statements.append)
    bot = FakeBot(messages)
    result = await backfill(bot, db, '10001', 2000)
    db.conn.set_trace_callback(None)
    assert (result['fetched'], result['inserted'], result['duplicates']) == (2000, 2000, 0)
    assert sum(s == 'COMMIT' for s in statements) == 1
    assert sum(s.startswith('SELECT') for s in statements) == 1
    ordered = db.conn.execute('SELECT message_id FROM messages ORDER BY id')
    assert [int(row[0]) for row in ordered] == list(range(51, 2051))
    repeat = await backfill(bot, db, '10001', 2000)
    assert (repeat['inserted'], repeat['duplicates']) == (0, 2000)
    older = await backfill(bot, db, '10001', 2000, cursor='51')
    assert (older['inserted'], older['duplicates']) == (50, 0)


@pytest.mark.asyncio
async def test_history_batch_rolls_back_when_write_fails(tmp_path):
    import sqlite3

    db = Store(tmp_path)
    db.conn.execute("""
        CREATE TRIGGER fail_history_write BEFORE INSERT ON messages
        WHEN NEW.message_id = '3'
        BEGIN SELECT RAISE(ABORT, '模拟写入故障'); END;
    """)
    bot = FakeBot([raw(i) for i in range(1, 6)])
    with pytest.raises(sqlite3.IntegrityError):
        await backfill(bot, db, '10001', 5)
    assert db.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0
    db.conn.execute('DROP TRIGGER fail_history_write')
    assert (await backfill(bot, db, '10001', 5))['inserted'] == 5


@pytest.mark.asyncio
async def test_history_cursor_progresses_with_same_second_messages(tmp_path):
    db = Store(tmp_path)
    messages = [{**raw(i), 'time': raw(1)['time']} for i in range(1, 31)]
    bot = FakeBot(messages)
    await backfill(bot, db, '10001', 10)
    assert db.history_cursor(bot.self_id, '10001') == '21'
    await backfill(bot, db, '10001', 10, cursor='21')
    assert db.history_cursor(bot.self_id, '10001') == '11'
    assert (await backfill(bot, db, '10001', 10))['duplicates'] == 10
    reopened = Store(tmp_path)
    cursor = reopened.history_cursor(bot.self_id, '10001')
    assert cursor == '11'
    assert (await backfill(bot, reopened, '10001', 10, cursor=cursor))['inserted'] == 10
    assert reopened.history_cursor(bot.self_id, '10001') == '1'
