/** rng 补测：rangeInt 值域、int/gaussian 边界、fork 语义、state 往返 */
import { RNG } from '../_new/AI-cocos--main/rng/RNG';
import * as Seed from '../_new/AI-cocos--main/rng/Seed';

console.log('▸ A. rangeInt(min>max) 的真实危害：端点丢失（不是越界）');
{
  const r = new RNG(42);
  const seen = new Set<number>();
  for (let i = 0; i < 5000; i++) seen.add(r.rangeInt(5, 1));
  const vals = [...seen].sort((a, b) => a - b);
  console.log(`  rangeInt(5,1) 5000 次的值域 = [${vals.join(', ')}]`);
  console.log(`  期望值域 = [1, 2, 3, 4, 5]`);
  console.log(`  → 实际只得到 ${vals.length}/5 个值，缺失 ${[1,2,3,4,5].filter(x=>!seen.has(x)).join(',') || '无'}`);
  console.log(`  → 分布本应均匀 5 档，实际被压缩到 ${vals.length} 档\n`);
}
{
  const r = new RNG(42);
  const seen = new Set<number>();
  for (let i = 0; i < 5000; i++) seen.add(r.rangeInt(1, 5));
  console.log(`  正序 rangeInt(1,5) 值域 = [${[...seen].sort((a,b)=>a-b).join(', ')}]  ← 正常 5 档`);
}

console.log('\n▸ B. int(n) 的 n 边界（无校验）');
{
  const r = new RNG(1);
  console.log(`  int(0)        = ${r.int(0)}`);
  console.log(`  int(-5)       = ${r.int(-5)}   ← 返回负数，可能让 pick 索引为负`);
  console.log(`  int(NaN)      = ${r.int(NaN)}`);
  console.log(`  int(Infinity) = ${r.int(Infinity)}`);
  console.log(`  int(1.5)      = ${r.int(1.5)}   ← 小数，floor 后仍是整数`);
  const r2 = new RNG(1);
  console.log(`  pick 在 int(-5) 下：arr[负数] = ${(() => { const a=[1,2,3]; return a[r2.int(-5)]; })()}`);
}

console.log('\n▸ C. gaussian 的 stdDev / mean 污染');
{
  const r = new RNG(1);
  console.log(`  gaussian(NaN, 1)  = ${r.gaussian(NaN, 1)}   ← NaN 直接穿透`);
  console.log(`  gaussian(0, NaN)  = ${r.gaussian(0, NaN)}   ← NaN 直接穿透`);
  console.log(`  gaussian(0, -1)   = ${r.gaussian(0, -1)}   ← 负标准差：合法但语义可疑`);
  console.log(`  gaussian(0, 0)    = ${r.gaussian(0, 0)}    ← 恒等于 mean`);
  // stdDev 为负是否应有约束？Box-Muller 里 stdDev 只是乘数，负值合法但通常无意义
}

console.log('\n▸ D. fork 语义（消耗父流一个值 — 是设计还是缺陷？）');
{
  const p = new RNG(7);
  const s0 = p.state;
  const c1 = p.fork();
  const s1 = p.state;
  const c2 = p.fork();
  const s2 = p.state;
  console.log(`  fork 前 state=${s0}`);
  console.log(`  fork 1 后 state=${s1}  ${s1 !== s0 ? '← 父流被消耗' : ''}`);
  console.log(`  fork 2 后 state=${s2}  ${s2 !== s1 ? '← 继续消耗' : ''}`);
  console.log(`  两次 fork 子流是否相同：${c1.state === c2.state ? '相同（有碰撞风险）' : '不同（正确）'}`);
  console.log(`  → fork 消耗父流是必要的（否则连续 fork 会得到同一子流），但 README 未说明`);
  // fork 的确定性
  const a = new RNG(99), b = new RNG(99);
  console.log(`  fork 可复现：${a.fork().state === b.fork().state ? '是' : '否'}`);
  // fork 后子流质量
  const children = new Set<number>();
  const pa = new RNG(5);
  for (let i = 0; i < 10000; i++) children.add(pa.fork().state);
  console.log(`  10000 次 fork 去重 = ${children.size}  ${children.size < 10000 ? `← 有 ${10000-children.size} 次碰撞` : '（无碰撞）'}`);
}

console.log('\n▸ E. state 存档往返（NaN 污染的实际路径）');
{
  const r = new RNG(12345);
  for (let i = 0; i < 10; i++) r.next();
  const saved = r.state;
  console.log(`  存档 state = ${saved}`);
  const r2 = new RNG(0);
  r2.state = saved;
  console.log(`  读档后 state = ${r2.state}  一致=${r2.state === saved}`);
  console.log(`  读档后继续 next() 与原流一致=${r2.next() === r.next()}`);

  // 模拟存档损坏：JSON 里存成 null / 字符串
  const r3 = new RNG(0);
  r3.state = Number(undefined as any);   // NaN
  console.log(`\n  模拟损坏：state = Number(undefined) = NaN → 实际存为 ${r3.state}`);
  const r4 = new RNG(0);
  r4.state = Number('abc');
  console.log(`  模拟损坏：state = Number('abc') = NaN → 实际存为 ${r4.state}`);
  console.log(`  → 构造函数对 0 有保护（换成 0x9e3779b9），setter 没有 → 行为不一致`);
  console.log(`  → 所有损坏的存档都会收敛到同一个种子，玩家"读档后地图全一样"`);
}

console.log('\n▸ F. Seed.random 分布（用 Math.random）');
{
  const counts = new Map<string, number>();
  for (let i = 0; i < 32000; i++) {
    const s = Seed.random();
    counts.set(s, (counts.get(s) ?? 0) + 1);
  }
  console.log(`  32000 次生成，去重 ${counts.size} 个（理论 3200）`);
  const vals = [...counts.values()];
  console.log(`  每桶出现次数 min=${Math.min(...vals)} max=${Math.max(...vals)} 期望≈10`);
}

console.log('\n▸ G. daily 跨时区（历史关注的点）');
{
  const d = new Date(Date.UTC(2026, 0, 15));
  console.log(`  daily(d, 0) = ${Seed.daily(d, 0)}`);
  console.log(`  daily(d, 8) = ${Seed.daily(d, 8)}`);
  console.log(`  → ${Seed.daily(d,0) === Seed.daily(d,8) ? '相同：offset 只影响"算哪一天"，这里 d 是 UTC 同一时刻故相同' : '不同'}`);
  // offset 的真正作用：改变落在哪一天
  const lateNight = new Date(Date.UTC(2026, 0, 15, 23, 0));  // UTC 23:00
  console.log(`  UTC 23:00 时 daily(_,0)=${Seed.daily(lateNight,0)}  daily(_,8)=${Seed.daily(lateNight,8)}`);
  console.log(`  → offset=8 时 UTC 23:00 已算次日，故不同（符合预期）`);
}
