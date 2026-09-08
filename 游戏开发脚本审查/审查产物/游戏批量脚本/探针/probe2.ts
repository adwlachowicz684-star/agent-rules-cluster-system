import { Scheduler } from '../src/scheduler/Scheduler';
import { TimeScale } from '../src/scheduler/TimeScale';

const log = (t: string, v: unknown) => console.log(`  ${t}: ${JSON.stringify(v)}`);
const step = (s: Scheduler, dt: number, n: number) => { for (let i=0;i<n;i++) s.update(dt); };

console.log('\n=== S1 · repeat(interval, fn, times=0) 应执行 0 次 ===');
{
  const s = new Scheduler(); let n = 0;
  s.repeat(0.5, () => n++, 0);
  step(s, 0.5, 5);
  log('times=0 实际执行次数', n);
}
console.log('=== S1b · repeat(interval, fn, times=-3) ===');
{
  const s = new Scheduler(); let n = 0;
  s.repeat(0.5, () => n++, -3);
  step(s, 0.5, 5);
  log('times=-3 实际执行次数', n);
}
console.log('=== S1c · repeat 正常 times=3 ===');
{
  const s = new Scheduler(); let n = 0;
  s.repeat(0.5, () => n++, 3);
  step(s, 0.5, 10);
  log('times=3 实际执行次数', n);
}

console.log('\n=== S2 · 参数 NaN 是否绕过校验 ===');
{
  const s = new Scheduler(); let n = 0;
  try { s.repeat(NaN, () => n++); log('repeat(NaN) 未抛错', true); }
  catch (e) { log('repeat(NaN) 抛错', String(e).slice(0,50)); }
  step(s, 0.1, 5);
  log('repeat(NaN) 5帧内执行次数（期望 0）', n);
}
{
  const s = new Scheduler(); let n = 0;
  try { s.delay(NaN, () => n++); log('delay(NaN) 未抛错', true); }
  catch (e) { log('delay(NaN) 抛错', String(e).slice(0,50)); }
  step(s, 0.1, 3);
  log('delay(NaN) 执行次数（期望 0）', n);
}

console.log('\n=== S3 · 顿帧是否真按真实时间过期（快速循环模拟）===');
{
  const s = new Scheduler();
  s.hitStop(0.08, 0.05);
  log('刚 hitStop 后 value', s.timeScale.value);
  // 快速跑 20 帧 * 0.1s = 模拟 2 秒游戏时间，但真实耗时 <1ms
  step(s, 0.1, 20);
  log('跑完 2 秒游戏时间后 value（期望回到 1，顿帧已过期）', s.timeScale.value);
  log('layerCount（期望 0）', s.timeScale.layerCount);
}

console.log('\n=== S4 · pause 时受缩放任务是否完全冻结 ===');
{
  const s = new Scheduler(); let n = 0; let d = 0;
  s.everyFrame((dt) => { n++; d += dt; });
  step(s, 0.1, 3);
  const before = { n, d: +d.toFixed(3) };
  s.pause();
  step(s, 0.1, 5);
  const during = { n, d: +d.toFixed(3) };
  s.unpause();
  step(s, 0.1, 2);
  log('暂停前', before);
  log('暂停中(5帧)', during);
  log('恢复后 n', n);
  log('=> 暂停期间是否完全冻结', before.n === during.n);
}

console.log('\n=== S5 · unscaled 通道在暂停时是否仍走 ===');
{
  const s = new Scheduler(); let ui = 0;
  s.everyFrameUnscaled(() => ui++);
  step(s, 0.1, 3);
  s.pause();
  step(s, 0.1, 5);
  log('暂停后 unscaled 累计（期望 8）', ui);
}

console.log('\n=== S6 · 回调中新增任务：是否本帧执行 ===');
{
  const s = new Scheduler(); const order: string[] = [];
  s.delay(0.1, () => { order.push('A'); s.delay(0.1, () => order.push('B')); });
  step(s, 0.1, 1);
  log('第1帧后', order);
  step(s, 0.1, 1);
  log('第2帧后', order);
  step(s, 0.1, 1);
  log('第3帧后（B 应已执行）', order);
}

console.log('\n=== S7 · 回调中取消另一个待执行任务 ===');
{
  const s = new Scheduler(); const order: string[] = [];
  const offB = s.delay(0.1, () => order.push('B'));
  s.delay(0.1, () => { order.push('A'); offB(); });
  step(s, 0.1, 1);
  log('执行顺序（A 取消 B，B 不应执行）', order);
}

console.log('\n=== S8 · destroy 后仍可 update / add ===');
{
  const s = new Scheduler(); let n = 0;
  s.everyFrame(() => n++);
  step(s, 0.1, 2);
  s.destroy();
  log('destroy 后 taskCount', s.taskCount);
  s.everyFrame(() => n++);
  step(s, 0.1, 2);
  log('destroy 后新注册任务执行次数（期望报错或忽略，实际）', n);
}

console.log('\n=== S9 · maxDeltaTime clamp 是否生效 ===');
{
  const s = new Scheduler(); let sum = 0;
  s.everyFrame((dt) => { sum += dt; });
  s.update(10);   // 模拟切后台 10 秒
  log('传入 dt=10，回调收到的 dt（期望 0.1）', sum);
  log('lastRealDt', s.lastRealDt);
}

console.log('\n=== S10 · TimeScale 多层相乘 + suspend ===');
{
  const ts = new TimeScale();
  ts.add('hitstop', 0.05, 0.08, 1000);
  ts.add('slowmo', 0.5);
  log('value (0.05*0.5)', ts.value);
  ts.suspend('hitstop');
  log('suspend hitstop 后（期望 0.5）', ts.value);
  ts.resume('hitstop');
  ts.update(1000 + 80);
  log('update 到 80ms 后（hitstop 应过期，期望 0.5）', ts.value);
  log('layerCount（期望 1）', ts.layerCount);
}
