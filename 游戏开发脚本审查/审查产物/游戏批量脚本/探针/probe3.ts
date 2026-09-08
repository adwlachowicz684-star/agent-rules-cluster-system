import { Scheduler } from '../src/scheduler/Scheduler';
const log = (t: string, v: unknown) => console.log(`  ${t}: ${JSON.stringify(v)}`);

console.log('\n=== S1 重测 · repeat 次数语义（用 dt=0.1 跑足够帧）===');
for (const times of [0, 1, 3, 5]) {
  const s = new Scheduler(); let n = 0;
  s.repeat(0.5, () => n++, times);
  for (let i=0;i<60;i++) s.update(0.1);   // 6 秒游戏时间
  log(`repeat(0.5,fn,times=${times}) 执行次数`, n);
}
{
  const s = new Scheduler(); let n = 0;
  s.repeat(0.5, () => n++);               // 无限
  for (let i=0;i<60;i++) s.update(0.1);
  log('repeat 无限（6秒内期望约12次）', n);
}

console.log('\n=== S1b · 长期节奏是否漂移（interval=0.5，跑 100 次）===');
{
  const s = new Scheduler(); const fireAt: number[] = [];
  let t = 0;
  s.everyFrame((dt) => { t += dt; });
  s.repeat(0.5, () => fireAt.push(+t.toFixed(4)));
  for (let i=0;i<600;i++) s.update(0.1);
  log('前 6 次触发时刻', fireAt.slice(0,6));
  log('第 95~100 次触发时刻', fireAt.slice(95,100));
  log('总次数', fireAt.length);
  const ideal = fireAt.map((_,i)=>+(0.5*(i+1)).toFixed(4));
  const drift = Math.max(...fireAt.map((v,i)=>Math.abs(v-ideal[i])));
  log('最大漂移（秒）', +drift.toFixed(4));
}

console.log('\n=== S7 重测 · A 先注册，A 回调中取消 B ===');
{
  const s = new Scheduler(); const order: string[] = [];
  let offB: () => void = () => {};
  s.delay(0.2, () => { order.push('A'); offB(); });      // A 先注册先执行
  offB = s.delay(0.2, () => order.push('B'));
  for (let i=0;i<4;i++) s.update(0.1);
  log('执行顺序（期望只有 A）', order);
}

console.log('\n=== S7b · 同帧取消已在 snapshot 中但未执行的任务 ===');
{
  const s = new Scheduler(); const order: string[] = [];
  const offB = s.everyFrame(() => order.push('B'));
  s.everyFrame(() => { order.push('A'); offB(); });
  s.update(0.1);
  log('第1帧（A 注册在后，应 A 后执行；B 已取消则只有 A）', order);
  s.update(0.1);
  log('第2帧（B 应不再出现）', order);
}

console.log('\n=== S2 确认 · NaN 参数 ===');
{
  const s = new Scheduler(); let n = 0;
  s.repeat(NaN, () => n++);
  for (let i=0;i<5;i++) s.update(0.1);
  log('repeat(NaN) 5 帧执行次数（期望 0，实际每帧都跑）', n);
}
{
  const s = new Scheduler(); let n = 0;
  s.delay(NaN, () => n++);
  for (let i=0;i<3;i++) s.update(0.1);
  log('delay(NaN) 3 帧执行次数（期望 0）', n);
}
{
  const s = new Scheduler();
  try { s.delay(-1, () => {}); log('delay(-1)', '未抛错'); }
  catch(e){ log('delay(-1) 抛错 ✓', String(e).slice(0,40)); }
  try { s.delay(Infinity, () => {}); log('delay(Infinity)', '未抛错'); }
  catch(e){ log('delay(Infinity) 抛错', String(e).slice(0,40)); }
}

console.log('\n=== S8 确认 · destroy 后行为 ===');
{
  const s = new Scheduler(); let n = 0;
  s.everyFrame(() => n++);
  for (let i=0;i<2;i++) s.update(0.1);
  const before = n;
  s.destroy();
  log('destroy 时已执行', before);
  s.everyFrame(() => n++);
  for (let i=0;i<2;i++) s.update(0.1);
  log('destroy 后新任务执行次数（期望 0 或报错）', n - before);
  log('taskCount', s.taskCount);
}

console.log('\n=== S11 · update 传入负数/NaN dt ===');
{
  const s = new Scheduler(); let sum = 0;
  s.everyFrame((dt) => { sum += dt; });
  s.update(-5);  log('dt=-5 后回调收到的 dt（期望 0）', sum);
  s.update(NaN); log('dt=NaN 后累计（期望仍 0）', sum);
  s.update(Infinity); log('dt=Infinity 后累计（期望 clamp 到 0.1）', +sum.toFixed(3));
}

console.log('\n=== S12 · 顿帧期间游戏逻辑是否仍推进（scale=0.05）===');
{
  const s = new Scheduler(); let adv = 0;
  s.everyFrame((dt) => { adv += dt; });
  s.hitStop(0.08, 0.05);
  s.update(0.1);
  log('顿帧中一帧推进的游戏时间（0.1*0.05=0.005）', +adv.toFixed(5));
  log('timeScale.value', s.timeScale.value);
}
