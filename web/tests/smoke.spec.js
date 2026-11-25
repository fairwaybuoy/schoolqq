import {test,expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const env=fs.readFileSync(path.resolve('../.env'),'utf8');
const token=env.match(/^APP_TOKEN=(.+)$/m)[1].trim();
const activate=locator=>locator.evaluate(button=>button.click());
test('中文导入、详情版本、人工确认、ICS、月周日历与手机布局',async({page})=>{
 await page.clock.setFixedTime(new Date('2026-10-18T12:00:00+08:00'));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let queueRequests=0;
 page.on('request',request=>{if(new URL(request.url()).pathname==='/assistant/api/queue')queueRequests++;});
 await page.goto('/assistant/');
 await page.locator('#login').evaluate((form, appToken)=>{
  form.querySelector('input').value=appToken;
  form.requestSubmit();
 },token);
 await expect(page.locator('[data-view="list"]')).toBeVisible();
 expect((await page.request.post('/assistant/api/demo')).ok()).toBeTruthy();
 await expect.poll(async()=>{const r=await page.request.get('/assistant/api/events');return (await r.json()).length;}).toBeGreaterThanOrEqual(4);
 await page.reload();
 await expect(page.getByText('模拟数据演示中')).toBeVisible();
 await activate(page.getByRole('button',{name:'商赛',exact:true}));
 const dialog=page.locator('dialog');await expect(dialog).toBeVisible();
 await expect(dialog).toContainText('10 月 20 日 18:00');
 await expect(dialog).toContainText('10 月 25 日 14:00');
 await expect(dialog).toContainText('来源消息');
 await expect(dialog).toContainText('变更与人工修改记录');
 await dialog.locator('#confirmed').evaluate(checkbox=>{checkbox.checked=true;});
 await activate(dialog.getByRole('button',{name:'保存修改',exact:true}));
 await expect(dialog).not.toBeVisible();
 const ics=await page.request.get('/assistant/api/calendar/deadlines.ics');expect(ics.status()).toBe(200);expect(await ics.text()).toContain('TZID=Asia/Shanghai:20261020T180000');
 await activate(page.getByRole('button',{name:'月 / 周日历'}));await expect(page.locator('.fc-dayGridMonth-view')).toBeVisible();
 await expect(page.locator('.fc-event').filter({hasText:'商赛'}).first()).toBeAttached();
 await activate(page.getByRole('button',{name:'周',exact:true}));await expect(page.locator('.fc-timeGridWeek-view')).toBeVisible();
 await activate(page.locator('#add'));
 await page.locator('#text').evaluate(input=>{input.value='手机演示活动 2026年10月30日 09:00 活动。地点：模拟教室';});
 await activate(page.getByRole('button',{name:'加入处理队列'}));
 await expect.poll(async()=>{const r=await page.request.get('/assistant/api/events');return (await r.json()).length;}).toBe(5);
 expect(queueRequests).toBe(0);
 await Promise.all([
  page.waitForResponse(response=>new URL(response.url()).pathname==='/assistant/api/queue'&&response.ok()),
  activate(page.locator('[data-view="queue"]')),
 ]);
 expect(queueRequests).toBe(1);
 await page.setViewportSize({width:390,height:844});await activate(page.locator('[data-view="list"]'));
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.clock.setFixedTime(new Date('2026-11-18T12:00:00+08:00'));
 await activate(page.locator('[data-filter="past"]'));
 await expect(page.getByRole('button',{name:'商赛',exact:true})).toBeAttached();
 expect(errors).toEqual([]);
});
