import { EventBus } from '../_new/AI-cocos--main/event-bus/EventBus';
interface E { a: { v: number } }
const bus: any = new EventBus<E>();

console.log('▸ 实证 A：off(name) 是否清空 Set 内容');
let n = 0;
const off = bus.on('a', () => n++);
const setRef = bus._map.get('a');          // 拿到内部 Set 引用
console.log(`  on 之后          _map.size=${bus._map.size}  set.size=${setRef.size}`);
bus.off('a');
console.log(`  off(name) 之后   _map.size=${bus._map.size}  set.size=${setRef.size}  ← set 内容是否清空？`);
console.log(`  结论：${setRef.size === 0 ? '已清空（监听器可 GC）' : '❌ 未清空 —— set 仍持有监听器'}`);

console.log('\n▸ 实证 B：offAll() / destroy() 是否清空 Set 内容');
const bus2: any = new EventBus<E>();
const o1 = bus2.on('a', () => {});
const o2 = bus2.on('b', () => {});
const sa = bus2._map.get('a'), sb = bus2._map.get('b');
bus2.offAll();
console.log(`  offAll 后  _map.size=${bus2._map.size}  setA=${sa.size} setB=${sb.size}  ← ${sa.size + sb.size === 0 ? '已清空' : '❌ 未清空'}`);

console.log('\n▸ 实证 C：由此导致的语义不一致');
{
  // C1: 回调中取消「单个」监听器 → 复查生效，本轮跳过
  const b: any = new EventBus<E>();
  let x = 0; let offX: any;
  b.on('a', () => { offX(); });
  offX = b.on('a', () => x++);
  b.emit('a', { v: 1 });
  console.log(`  C1 回调内取消单个监听器 → 后续执行次数=${x}  ${x === 0 ? '✓ 被拦住' : '❌ 未被拦住'}`);
}
{
  // C2: 回调中 off(name) 整条清空 → 复查失效，后续仍执行
  const b: any = new EventBus<E>();
  let y = 0;
  b.on('a', () => b.off('a'));
  b.on('a', () => y++);
  b.emit('a', { v: 1 });
  console.log(`  C2 回调内 off(name) 整条清空 → 后续执行次数=${y}  ${y === 0 ? '✓ 被拦住' : '❌ 未被拦住（与 C1 不一致）'}`);
}

console.log('\n▸ 实证 D：offAll 后旧取消函数仍持有 set（内存可达性）');
{
  const b: any = new EventBus<E>();
  let z = 0;
  const offZ = b.on('a', () => z++);
  const s = b._map.get('a');
  b.offAll();
  console.log(`  offAll 后 set 仍有 ${s.size} 个监听器；offZ 闭包持有该 set`);
  console.log(`  → 只要调用方持有 offZ（组件里存着待销毁时调是常态），监听器闭包就无法 GC`);
}

console.log('\n▸ 实证 E：递归 emit（无重入保护）');
{
  const b: any = new EventBus<E>();
  let depth = 0;
  const origErr = console.error; console.error = () => {};
  try {
    b.on('a', () => { if (++depth < 5) b.emit('a', { v: 1 }); });
    b.emit('a', { v: 1 });
  } catch (e) { console.log(`  抛错: ${e}`); }
  console.error = origErr;
  console.log(`  同事件递归 emit 深度=${depth}（无深度上限，互递归会栈溢出）`);
}
