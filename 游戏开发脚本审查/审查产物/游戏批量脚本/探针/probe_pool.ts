/** pool 精审探针：历史修复复核 + 遗留项 + 边界 + 一致性 */
import { Pool } from '../_new/AI-cocos--main/pool/Pool';

let pass = 0, fail = 0;
function ck(n: string, got: unknown, want: unknown) {
  if (got === want) { pass++; console.log(`  ✓ ${n}`); }
  else { fail++; console.log(`  ✗ ${n}  得到 ${JSON.stringify(got)} 期望 ${JSON.stringify(want)}`); }
}
function info(n: string, v: unknown = '') { console.log(`  · ${n} = ${JSON.stringify(v)}`); }
function mk(opts?: any) {
  return new Pool<any>(() => ({ id: Math.random() }), undefined, undefined, opts);
}

console.log('\n▸ P1 历史已修复现：destroy 后归还不得让 active 变负');
{
  const p = mk();
  const a = p.get(), b = p.get();
  ck('get 两次 active=2', p.active, 2);
  p.destroy();
  ck('destroy 后 active=0', p.active, 0);
  p.put(a); p.put(b);
  ck('再 put 两次 active 不得为负', p.active, 0);
  // 重复归还拦截
  const p2 = mk();
  const o = p2.get();
  p2.put(o); p2.put(o);   // 第二次应被拦截
  ck('重复归还后 active=0（未变负）', p2.active, 0);
  ck('重复归还后 idle=1（未塞两个同引用）', p2.idle, 1);
}

console.log('\n▸ P2 【历史遗留①】maxSize 无收口 → NaN 让池静默失效');
{
  const origWarn = console.warn; console.warn = () => {};
  const p = mk({ maxSize: NaN });
  info('_maxSize（NaN 未被 ?? 挡住）', (p as any)._maxSize);
  const o = p.get();
  p.put(o);
  console.warn = origWarn;
  info('put 后 idle（期望 1，若 0 则池完全失效）', p.idle);
  info('  → `_idle.length < NaN` 恒为 false → 每次 put 都丢弃 → 池永不复用', p.idle === 0 ? '确认失效' : '正常');
  // Infinity
  const p2 = mk({ maxSize: Infinity });
  const o2 = p2.get(); p2.put(o2);
  info('maxSize=Infinity 时 idle', p2.idle);
  // 负数
  const p3 = mk({ maxSize: -5 });
  const o3 = p3.get(); p3.put(o3);
  info('maxSize=-5 时 idle（期望 0，负数容量=不缓存）', p3.idle);
}

console.log('\n▸ P3 【历史遗留②】prewarm 是否受 maxSize 限制（既有契约）');
{
  const p = mk({ maxSize: 3 });
  let threw = false;
  try { p.prewarm(20); } catch { threw = true; }
  ck('prewarm(20) 配 maxSize:3 不抛错', threw, false);
  ck('且 idle === 20（既有测试断言的契约）', p.idle, 20);
  // 上界保护
  const p2 = mk();
  for (const [n, label] of [[Infinity, 'Infinity'], [NaN, 'NaN'], [-1, '-1'], [1e9, '1e9']] as const) {
    let e = '';
    try { p2.prewarm(n as number); } catch (err: any) { e = err.constructor.name; }
    info(`prewarm(${label}) → ${e || '未抛错（静默）'}`);
  }
  info('prewarm 后 idle（累加了上面未抛错的）', p2.idle);
}

console.log('\n▸ P4 【历史遗留③】onPut 抛异常 → active 与 idle 不一致');
{
  const origErr = console.error; console.error = () => {};
  let putCalls = 0;
  const p = new Pool<any>(() => ({}), undefined, () => { putCalls++; throw new Error('onPut boom'); });
  const o = p.get();
  ck('get 后 active=1', p.active, 1);
  let threw = false;
  try { p.put(o); } catch { threw = true; }
  info('put 抛错', threw);
  console.error = origErr;
  info('onPut 调用次数', putCalls);
  info('抛错后 active', p.active);
  info('抛错后 idle', p.idle);
  info('  → active 已减、onPut 抛错、对象没进池 → 对象丢失且计数少 1', p.active === 0 && p.idle === 0 ? '确认不一致' : '');
}

console.log('\n▸ P5 【新】onGet 抛异常 → 对象丢失 + active 虚高');
{
  const origErr = console.error; console.error = () => {};
  const p = new Pool<any>(() => ({ v: 0 }), () => { throw new Error('onGet boom'); });
  p.prewarm(3);
  ck('预热后 idle=3', p.idle, 3);
  let threw = 0;
  for (let i = 0; i < 3; i++) { try { p.get(); } catch { threw++; } }
  console.error = origErr;
  info('get 抛错次数', threw);
  info('抛错后 active（对象已出池、已从 idle 摘除，但从未交付调用方）', p.active);
  info('抛错后 idle', p.idle);
  info('  → 对象永久丢失，而 active 虚高', p.active === 3 && p.idle === 0 ? '确认' : '');
  // 对照：正常 get
  const p2 = new Pool<any>(() => ({ v: 0 }), (o) => { o.v = 1; });
  p2.prewarm(2);
  const a = p2.get();
  ck('正常 get 后 idle=1', p2.idle, 1);
  ck('正常 get 后 active=1', p2.active, 1);
  ck('onGet 已生效', a.v, 1);
}

console.log('\n▸ P6 复用正确性（对象池的核心承诺）');
{
  let resets = 0;
  const p = new Pool<any>(() => ({ v: 0 }), (o) => { resets++; o.v = 0; });
  const a = p.get(); a.v = 99;
  p.put(a);
  const b = p.get();
  ck('复用同一对象（引用相同）', b === a, true);
  ck('onGet 已重置（v 回到 0）', b.v, 0);
  ck('onGet 被调用 2 次', resets, 2);
  ck('created 只 1（未反复创建）', p.created, 1);
}

console.log('\n▸ P7 guardDuplicate 关闭时的行为（文档已声明）');
{
  const origWarn = console.warn; console.warn = () => {};
  const p = mk({ guardDuplicate: false });
  const o = p.get();
  p.put(o); p.put(o);
  console.warn = origWarn;
  info('guardDuplicate:false 时重复 put 后 idle', p.idle);
  info('  → 空闲池里两个相同引用', p.idle === 2 ? '确认（文档已声明风险）' : '');
  const a = p.get(), b = p.get();
  info('连续 get 两次是否拿到同一对象', a === b ? '是（子弹池会表现"两颗一起飞"）' : '否');
}

console.log('\n▸ P8 装原始值时的 Set 判等陷阱（文档已声明）');
{
  const origWarn = console.warn; console.warn = () => {};
  const p = new Pool<number>(() => 0);
  const a = p.get();   // 0
  p.put(a);
  const b = p.get();   // 0
  let dupBlocked = false;
  p.put(b);            // 又一个 0
  p.put(a);            // 还是 0
  console.warn = origWarn;
  info('Pool<number> 两个 0 被当同一对象 → idle', p.idle);
  info('  → 文档已明确警告：对象池本就该装对象', '');
}

console.log('\n▸ P9 clear / destroy 语义');
{
  const p = mk({ trackLeaks: true });
  const a = p.get(), b = p.get();
  p.put(a);
  ck('put 一个后 idle=1 active=1', `${p.idle}/${p.active}`, '1/1');
  p.clear();
  ck('clear 只清空闲 → idle=0 active 保持 1', `${p.idle}/${p.active}`, '0/1');
  ck('clear 不动 active（借出的仍在外部）', p.active, 1);
  p.destroy();
  ck('destroy 全清 → active=0', p.active, 0);
  ck('destroy 幂等', (() => { p.destroy(); return p.active; })(), 0);
  // destroy 后可继续用（无 _destroyed 标记）
  const c = p.get();
  ck('destroy 后仍可 get（无状态标记）', p.active, 1);
  p.put(c);
  ck('destroy 后仍可 put', p.active, 0);
}

console.log('\n▸ P10 trackLeaks 的 _out 是否成为泄漏源');
{
  const p = mk({ trackLeaks: true });
  const objs = Array.from({ length: 5 }, () => p.get());
  ck('_out 记录数 = 借出数', (p as any)._out.size, 5);
  p.put(objs[0]);
  ck('put 一个后 _out 减 1', (p as any)._out.size, 4);
  // 只 get 不 put → _out 永久持有引用（这是设计意图：泄漏检测）
  info('  → 未归还的对象被 _out 强引用，GC 无法回收', '（设计如此，但需文档明示）');
  p.destroy();
  ck('destroy 清空 _out', (p as any)._out.size, 0);
}

console.log('\n▸ P11 dump 的时间源（N01：Date.now 硬编码）');
{
  const origErr = console.error; console.error = () => {};
  const p = mk({ trackLeaks: true });
  const o = p.get();
  const s1 = p.dump(5000);
  info('dump(5000) 立即调用', s1.slice(0, 60));
  info('  → 阈值基于真实时间，无法注入 → 单测只能真 sleep', '');
  const p2 = mk();   // 未开 trackLeaks
  info('未开 trackLeaks 时 dump', p2.dump().slice(0, 70));
  console.error = origErr;
  // put 后 dump
  p.put(o);
  info('归还后 dump', p.dump(5000).slice(0, 60));
}

console.log('\n▸ P12 对抗性输入');
{
  const origWarn = console.warn; console.warn = () => {};
  const p = mk();
  // put 一个从未借出的对象（外部对象混入）
  const stranger = { id: 'stranger' };
  p.put(stranger);
  info('put 外部对象后 idle', p.idle);
  info('  → 无归属校验：非本池创建的对象也能进池（历史 Q04 相关）', p.idle === 1 ? '确认可混入' : '');
  const got = p.get();
  info('get 拿到的是混入的外部对象', got === stranger);
  console.warn = origWarn;
  // putAll 含重复
  const p2 = mk();
  const x = p2.get(), y = p2.get();
  p2.putAll([x, y, x]);
  info('putAll([x,y,x]) 后 idle', p2.idle);
  info('  active', p2.active);
}

console.log(`\n===== 通过 ${pass} · 失败 ${fail} =====`);
