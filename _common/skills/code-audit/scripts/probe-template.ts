/**
 * probe-template.ts —— 单元审查探针模板
 *
 * 用法：
 *   1. cp scripts/probe-template.ts audit/probe_<单元>.ts
 *   2. 改 import 指向被测单元，按 P1~P12 替换为真实断言
 *   3. npx tsc --outDir build --module commonjs --target ES2019 \
 *          --skipLibCheck --lib ES2019,DOM audit/probe_<单元>.ts
 *      node build/audit/probe_<单元>.js
 *
 * 设计原则：
 *   - 每组打印「期望 vs 实际」，失败时一眼能看出哪里错
 *   - 每组独立作用域（{} 包裹），避免状态串扰
 *   - 命名写清期望：'repeat(NaN) 应拒绝注册，而非每帧执行'
 *   - 九类对抗性输入必测（见 P1，速查卡 assets/adversarial-inputs-card.md）
 *   - 序列化时把 NaN/Infinity/函数转成可读字符串，否则 JSON.stringify 会丢信息
 */

import { /* TargetClass */ } from '../src/<单元>/<文件>';

const log = (label: string, v: unknown) =>
  console.log(`  ${label}: ${JSON.stringify(v)}`);

/** 安全序列化：JSON.stringify 默认会把 NaN 变 null、丢弃函数，信息静默丢失 */
const safe = (v: unknown): unknown =>
  JSON.parse(JSON.stringify(v, (_k, x) => {
    if (typeof x === 'number' && !Number.isFinite(x)) return String(x);
    if (typeof x === 'function') return `[Function ${(x as Function).name || 'anonymous'}]`;
    return x;
  }));

const step = (tick: (dt: number) => void, n: number, dt = 0.1) => {
  for (let i = 0; i < n; i++) tick(dt);
};

/** 九类对抗性输入 —— 每个数值/字符串入口都要过一遍
 *  只测 0 / 负数 / 正常值测不出 NaN 类缺陷 */
const ADVERSARIAL: Array<[string, unknown]> = [
  ['NaN', NaN], ['Infinity', Infinity], ['-Infinity', -Infinity],
  ['null', null], ['undefined', undefined], ['空串', ''],
  ['负数', -1], ['零', 0], ['小数', 1.5], ['超大值', 1e9],
  ['原型键', '__proto__'], ['constructor', 'constructor'],
  ['含点号键', 'a.b'], ['含逗号键', 'a,b'],
];

/* P1 · 数值入口的九类对抗性输入
 * 判据：非法值必须被拒绝或收口，不得静默穿透
 * 陷阱：Math.max(1, NaN)=NaN，Math.max 不是有效守卫 */
console.log('\n=== P1 · 数值入口对抗性输入 ===');
for (const [label, bad] of ADVERSARIAL) {
  try {
    // const r = target.method(bad as number);
    // log(`输入 ${label}`, safe(r));
    log(`输入 ${label}`, 'TODO: 替换为真实调用');
  } catch (e) {
    log(`输入 ${label} 抛错`, String(e).slice(0, 60));
  }
}

/* P2 · 循环上界 / 数组尺寸
 * 判据：Infinity 不得导致挂死；NaN 不得静默返回空
 * 危险：这类问题会冻结主线程，探针要有超时保护，别真传 Infinity 死等 */
console.log('\n=== P2 · 循环上界与分配尺寸 ===');
log('times=1e9 是否在合理时间内返回', 'TODO');

/* P3 · 原型键查表
 * 判据：外部键必须当作普通不存在的键处理，不得返回继承成员 */
console.log('\n=== P3 · 原型键 ===');
for (const k of ['__proto__', 'constructor', 'toString', 'valueOf', 'hasOwnProperty']) {
  try {
    // const v = target.get(k);
    log(`get('${k}')`, 'TODO');
  } catch (e) {
    log(`get('${k}') 抛错`, String(e).slice(0, 50));
  }
}

/* P4 · 含分隔符的动态键（路径 / 复合 key 往返）
 * 判据：{'a.b':1} 往返后必须还是 {'a.b':1}，不能变成 {a:{b:1}} */
console.log('\n=== P4 · 动态键往返 ===');
{
  const before = { 'a.b': 1, 'x,y': 2 };
  log('TODO', JSON.stringify(before));
}

/* P5 · 交易 / 批量数量
 * 判据：负数量不得反向增钱/增库存 */
console.log('\n=== P5 · 负数量 ===');
log('TODO', '');

/* P6 · 遍历中修改集合
 * 判据：A 在回调里退订，B、C 必须仍然执行 */
console.log('\n=== P6 · 订阅者在回调内退订 ===');
{
  const order: string[] = [];
  // let offA = target.onXxx(() => { order.push('A'); offA(); });
  // target.onXxx(() => order.push('B'));
  // target.onXxx(() => order.push('C'));
  // target.trigger();
  log('期望 A/B/C 都执行，实际', order);
}

/* P7 · 时间 / 随机源可注入性
 * 判据：注入假时钟后，依赖时间的行为应完全可控（无需真 sleep） */
console.log('\n=== P7 · 时间源注入 ===');
{
  let fakeNow = 1000;
  log('TODO (fakeNow=' + fakeNow + ')', '');
}

/* P8 · 长跑无漂移
 * 判据：累积数千帧后，周期行为不得产生累积误差 */
console.log('\n=== P8 · 长跑漂移 ===');
log('TODO', '');

/* P9 · 返回引用安全性
 * 判据：调用方持有的返回值不得被后续操作改写 */
console.log('\n=== P9 · 返回内部引用 ===');
log('TODO', '');

/* P10 · destroy 幂等
 * 判据：destroy 后不得再接受注册，或至少早退不执行 */
console.log('\n=== P10 · destroy 后行为 ===');
log('TODO', '');

/* P11 · 容量上限
 * 判据：日志/历史/缓存类字段必须有上限，不得无限增长 */
console.log('\n=== P11 · 容量增长 ===');
log('TODO', '');

/* P12 · 照 README 调用
 * 判据：README/JSDoc 的示例代码必须能真实跑通 */
console.log('\n=== P12 · 照 README 调用 ===');
try {
  log('README 示例是否可运行', 'TODO');
} catch (e) {
  log('README 示例报错', String(e).slice(0, 80));
}

console.log('\n探针执行完毕。每组必须给出「期望 vs 实际」的对照结论。');
console.log('污染类 probe（原型污染）测完记得 delete Object.prototype.xxx 清理。');
