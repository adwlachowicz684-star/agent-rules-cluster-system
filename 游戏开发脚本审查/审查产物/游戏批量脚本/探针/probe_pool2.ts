/** pool 补测：归属校验缺失导致的 active 漂移 + maxSize 失效后果 */
import { Pool } from '../_new/AI-cocos--main/pool/Pool';

function info(n: string, v: unknown = '') { console.log(`  · ${n} = ${JSON.stringify(v)}`); }

console.log('▸ A. 【新】put 外部对象会扣 active —— 泄漏检测可被"刷"成 0');
{
  console.warn = () => {};
  const p = new Pool<any>(() => ({ tag: 'mine' }));
  const a = p.get(), b = p.get(), c = p.get();
  info('借出 3 个后 active', p.active);
  // 混入 5 个从未借出的外部对象
  for (let i = 0; i < 5; i++) p.put({ tag: 'stranger' + i });
  info('put 5 个外部对象后 active（仍欠 3 个真实对象）', p.active);
  info('  → active 已被扣到 0，而 a/b/c 三个真实对象根本没还', p.active === 0 ? '确认：泄漏指标被抹平' : '');
  // 此时归还真实对象
  p.put(a); p.put(b); p.put(c);
  info('归还真实 3 个后 active', p.active);
  info('  → 全程 active 恒为 0，泄漏检测完全失效', '');
  info('idle（含 5 个外部对象）', p.idle);
  const got = p.get();
  info('get 拿到的对象', got.tag);
  info('  → 外部对象被当作池对象复用', got.tag.startsWith('stranger') ? '确认' : '');
}

console.log('\n▸ B. maxSize=NaN 的完整后果：池彻底退化为工厂');
{
  console.warn = () => {};
  const p = new Pool<any>(() => ({}), undefined, undefined, { maxSize: NaN });
  for (let round = 0; round < 100; round++) { const o = p.get(); p.put(o); }
  info('100 轮 get/put 后 created', p.created);
  info('100 轮 get/put 后 idle', p.idle);
  info('  → created=100 说明每次都在新建（正常池应 created=1）', p.created === 100 ? '确认：零复用' : '');
  info('  → 池静默退化为 new 工厂，无报错无警告', '');
  // 对照正常
  const p2 = new Pool<any>(() => ({}), undefined, undefined, { maxSize: 1000 });
  for (let round = 0; round < 100; round++) { const o = p2.get(); p2.put(o); }
  info('对照：maxSize=1000 时 created', p2.created);
}

console.log('\n▸ C. onGet / onPut 抛异常后的状态（对照正常）');
{
  console.error = () => {};
  // 正常基线
  const base = new Pool<any>(() => ({}));
  const b1 = base.get(); base.put(b1);
  info('正常：get+put 后 active/idle', `${base.active}/${base.idle}`);

  // onGet 抛
  const p1: any = new Pool<any>(() => ({}), () => { throw new Error('get'); });
  p1.prewarm(5);
  let n1 = 0;
  for (let i = 0; i < 5; i++) { try { p1.get(); } catch { n1++; } }
  info('onGet 抛 5 次后 active/idle（对象全丢，active 虚高）', `${p1.active}/${p1.idle}`);
  info('  → 5 个对象永久丢失，created 却记为 5', `created=${p1.created}`);

  // onPut 抛
  const p2: any = new Pool<any>(() => ({}), undefined, () => { throw new Error('put'); });
  p2.prewarm(5);
  let n2 = 0;
  for (let i = 0; i < 5; i++) { const o = p2.get(); try { p2.put(o); } catch { n2++; } }
  info('onPut 抛 5 次后 active/idle（对象全丢，active 少计）', `${p2.active}/${p2.idle}`);
  info('  → 借出 5 个、全部"归还"失败，active 应为 5 实为', p2.active);
}

console.log('\n▸ D. guardDuplicate 默认开 —— Set 的 O(1) 与内存代价');
{
  console.warn = () => {};
  const p: any = new Pool<any>(() => ({}));
  info('_inIdle 是否创建', p._inIdle !== null);
  p.prewarm(1000);
  info('预热 1000 个后 _inIdle.size', p._inIdle.size);
  info('  → 每个空闲对象在数组 + Set 各存一份（额外引用表，内存约翻倍）', '');
  info('  → 文档已声明开销 O(1) 可接受，且可显式关', '');
}
