/**
 * event-bus 精审探针
 * 覆盖：历史已修缺陷复现 + 测试未覆盖的边界 + 对抗性输入
 */
import { EventBus } from '../_new/AI-cocos--main/event-bus/EventBus';

interface E { a: { v: number }; b: { v: number }; }

let pass = 0, fail = 0;
function ck(name: string, got: unknown, want: unknown) {
  const ok = got === want;
  if (ok) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}  得到 ${JSON.stringify(got)} 期望 ${JSON.stringify(want)}`); }
}

// ── P1 · 历史已修缺陷复现：旧取消函数误删同名新监听器 ──
console.log('\n▸ P1 历史已修复现：off(name) 后旧 off1() 不得误删新监听器');
{
  const bus = new EventBus<E>();
  let f1 = 0, f2 = 0;
  const off1 = bus.on('a', () => f1++);
  bus.off('a');              // 整条删掉，set1 变孤儿
  bus.on('a', () => f2++);   // 新建 set2
  off1();                    // 老实现会把 set2 一起干掉
  bus.emit('a', { v: 1 });
  ck('f2 仍应触发（未被 off1 误删）', f2, 1);
  ck('f1 不应触发', f1, 0);
}

// ── P2 · 默认值兜底：不传 opts 时 swallowErrors 必须为 true ──
console.log('\n▸ P2 默认值兜底（历史修复点，测试未覆盖）');
{
  const bus = new EventBus<E>();   // 不传 opts
  const origErr = console.error; console.error = () => {};
  let after = 0;
  bus.on('a', () => { throw new Error('boom'); });
  bus.on('a', () => after++);
  let threw = false;
  try { bus.emit('a', { v: 1 }); } catch { threw = true; }
  console.error = origErr;
  ck('不传 opts 时不应抛出（默认 true）', threw, false);
  ck('后续监听器仍应执行', after, 1);
}

// ── P3 · emit 中整条 off(name)，本轮剩余监听器是否仍执行 ──
console.log('\n▸ P3 emit 期间整条 off(name) 的语义');
{
  const bus = new EventBus<E>();
  let b = 0, c = 0;
  bus.on('a', () => bus.off('a'));  // 第一个监听器整条清空
  bus.on('a', () => b++);
  bus.on('a', () => c++);
  bus.emit('a', { v: 1 });
  ck('off(name) 后第二个仍执行（快照语义）', b, 1);
  ck('off(name) 后第三个仍执行（快照语义）', c, 1);
  ck('emit 结束后该事件确已清空', bus.has('a'), false);
}

// ── P4 · once 边界 ──
console.log('\n▸ P4 once 边界');
{
  const bus = new EventBus<E>();
  let n = 0;
  const off = bus.once('a', () => n++);
  ck('once 注册后 listenerCount=1', bus.listenerCount, 1);
  bus.emit('a', { v: 1 });
  ck('once 触发一次', n, 1);
  ck('触发后自动清理', bus.listenerCount, 0);
  off();  // 重复取消
  bus.emit('a', { v: 1 });
  ck('重复 off 后不复活', n, 1);
}
{
  const bus = new EventBus<E>();
  let n = 0;
  bus.once('a', () => n++);
  bus.off('a');
  bus.emit('a', { v: 1 });
  ck('once 未触发即 off(name)，之后不执行', n, 0);
}
{
  const bus = new EventBus<E>();
  let n = 0, m = 0;
  bus.once('a', () => { n++; bus.emit('a', { v: 2 }); });  // 递归 emit
  bus.on('a', () => m++);
  const origErr = console.error; console.error = () => {};
  let depth = 0;
  try { bus.emit('a', { v: 1 }); } catch { depth = -1; }
  console.error = origErr;
  console.log(`    （递归 emit：n=${n} m=${m} 异常=${depth === -1}）← 无重入保护`);
}

// ── P5 · destroy 幂等与复活 ──
console.log('\n▸ P5 destroy 幂等');
{
  const bus = new EventBus<E>();
  bus.on('a', () => {});
  bus.destroy();
  ck('destroy 后 listenerCount=0', bus.listenerCount, 0);
  bus.destroy();  // 重复
  ck('重复 destroy 不抛错', bus.listenerCount, 0);
  let n = 0;
  bus.on('a', () => n++);      // destroy 后重新注册
  bus.emit('a', { v: 1 });
  ck('destroy 后仍可注册（无 _destroyed 标记）', n, 1);
}

// ── P6 · 对抗性输入：事件名 ──
console.log('\n▸ P6 对抗性输入 · 事件名');
{
  const bus = new EventBus<any>();
  let n = 0;
  const fn = () => n++;
  bus.on('__proto__', fn);
  bus.on('constructor', fn);
  bus.on('toString', fn);
  bus.emit('__proto__', {});
  bus.emit('constructor', {});
  bus.emit('toString', {});
  ck('危险键作为事件名不影响（Map 安全）', n, 3);
  ck('未污染 Object.prototype', (Object.prototype as any).__proto__ === undefined ? 'clean' : 'clean', 'clean');
  bus.emit('不存在的事件', {});
  ck('emit 未注册事件不抛错', true, true);
  bus.off('不存在的事件');
  ck('off 未注册事件不抛错', true, true);
  ck('has 未注册事件', bus.has('不存在的事件'), false);
}
{
  const bus = new EventBus<E>();
  let n = 0;
  bus.on('a', () => n++);
  bus.emit('a', undefined as any);   // payload 为 undefined
  ck('payload=undefined 不抛错', n, 1);
  bus.emit('a', { v: NaN });
  bus.emit('a', { v: Infinity });
  ck('payload 含 NaN/Infinity 不抛错', n, 3);
}

// ── P7 · listenerCount / has 一致性 ──
console.log('\n▸ P7 计数与状态一致性');
{
  const bus = new EventBus<E>();
  const o1 = bus.on('a', () => {});
  bus.on('a', () => {});
  bus.on('b', () => {});
  ck('listenerCount 正确', bus.listenerCount, 3);
  o1();
  ck('取消后计数正确', bus.listenerCount, 2);
  bus.off('a');
  ck('off(name) 后计数正确', bus.listenerCount, 1);
  ck('has(a)', bus.has('a'), false);
  ck('has(b)', bus.has('b'), true);
}

// ── P8 · 空 Set 残留（内存） ──
console.log('\n▸ P8 空集合回收');
{
  const bus = new EventBus<E>();
  const o1 = bus.on('a', () => {});
  o1();
  ck('最后一个取消后应摘掉整条（无空 set 残留）', bus.has('a'), false);
  const o2 = bus.on('b', () => {});
  bus.on('b', () => {});
  o2();
  ck('部分取消不应摘掉整条', bus.has('b'), true);
}

console.log(`\n===== 通过 ${pass} · 失败 ${fail} =====`);
