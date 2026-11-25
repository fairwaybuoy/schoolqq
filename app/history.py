"""按需从 NapCat 读取有限条群历史，并交给现有的去重处理队列。"""
from datetime import datetime

from pydantic import Field

from .models import MessageIn, Segment, Strict, TZ


class HistoryRequest(Strict):
    group_id: str
    limit: int = Field(default=500, ge=1, le=2000)
    older: bool = False


def sequence(raw):
    try:
        return int(raw.get('message_seq') or 0)
    except (TypeError, ValueError):
        return 0


def to_message(raw, account_id, group_id):
    """只接受指定群的可识别 OneBot 消息；不下载媒体文件。"""
    if not isinstance(raw, dict) or str(raw.get('group_id', group_id)) != group_id:
        return None
    if raw.get('message_id') is None or not raw.get('time'):
        return None
    try:
        sent_at = datetime.fromtimestamp(int(raw['time']), TZ)
        source = raw.get('message', [])
        if isinstance(source, str):
            segments = [Segment(type='text', data={'text': source})]
            text = source
        elif isinstance(source, list):
            segments = [Segment.model_validate(s) for s in source if isinstance(s, dict) and isinstance(s.get('data'), dict) and isinstance(s.get('type'), str)][:100]
            text = ''.join(str(s.data.get('text', '')) for s in segments if s.type == 'text')
        else:
            return None
        reply_to = next((str(s.data['id']) for s in segments if s.type == 'reply' and 'id' in s.data), None)
        return MessageIn(account_id=str(account_id), group_id=group_id,
                         message_id=str(raw['message_id']), sent_at=sent_at,
                         source='qq', text=text[:20000], segments=segments,
                         reply_to=reply_to)
    except (ValueError, TypeError, OverflowError):
        return None


async def backfill(bot, db, group_id, limit, cursor=None):
    """NapCat 的游标页包含锚点；用 message_id 翻页并检查是否前进。"""
    from_cursor = cursor
    fetched = skipped = 0
    seen = set()
    collected = []
    stop = 'limit'
    oldest = newest = None
    while fetched < limit:
        count = min(100, limit - fetched + (1 if cursor is not None else 0))
        params = {'group_id': int(group_id), 'count': count, 'reverseOrder': True}
        if cursor is not None:
            params['message_id'] = cursor
        response = await bot.call_api('get_group_msg_history', **params)
        page = response.get('messages') if isinstance(response, dict) else None
        if not isinstance(page, list):
            raise ValueError('NapCat 未返回可读取的群历史消息')
        if not page:
            stop = 'available_end'
            break
        # NapCat 通常从旧到新返回；不能依赖数组顺序来选择下一页锚点。
        valid = []
        for raw in page:
            if not isinstance(raw, dict) or raw.get('message_id') is None or not raw.get('time'):
                continue
            try:
                timestamp = int(raw['time'])
            except (TypeError, ValueError, OverflowError):
                continue
            valid.append((timestamp, sequence(raw), raw))
        if not valid:
            stop = 'unreadable_page'
            break
        _, _, oldest_raw = min(valid, key=lambda entry: entry[:2])
        next_cursor = str(oldest_raw['message_id'])
        new_page = 0
        for _, message_sequence, raw in valid:
            mid = str(raw['message_id'])
            if mid in seen or (cursor is not None and mid == cursor):
                continue
            seen.add(mid)
            if fetched >= limit:
                break
            fetched += 1
            new_page += 1
            msg = to_message(raw, bot.self_id, group_id)
            if msg is None:
                skipped += 1
                continue
            stamp = msg.sent_at.isoformat()
            oldest = min(oldest, stamp) if oldest else stamp
            newest = max(newest, stamp) if newest else stamp
            collected.append((msg.sent_at, message_sequence, msg))
        if next_cursor == cursor or new_page == 0:
            stop = 'stalled'
            break
        cursor = next_cursor
        if len(page) < count:
            stop = 'available_end'
            break
    # 同一批旧通知与延期消息必须按原发送顺序入队。
    collected.sort(key=lambda entry: entry[:2])
    oldest_sequence = collected[0][1] if collected else 0
    inserted, duplicates = db.ingest_history(
        (msg for _, _, msg in collected), str(bot.self_id), group_id, oldest_sequence, from_cursor,
    )
    return {'group_id': group_id, 'fetched': fetched, 'inserted': inserted,
            'duplicates': duplicates, 'skipped': skipped, 'oldest': oldest,
            'newest': newest, 'stop': stop,
            'note': '返回范围取决于 NapCat/QQ 可取得的历史；不能证明离线期间的消息已全部补齐。'}
