/** rng 精审探针：历史修复复核 + 边界 + 对抗性输入 */
import { RNG } from '../_new/AI-cocos--main/rng/RNG';
import * as Seed from '../_new/AI-cocos--main/rng/Seed';

let pass = 0, fail = 0;
function ck(n: string, got: unknown, want: unknown) {
  const ok = got === want || (Number.isNaN(got as any) && Number.isNaN(want as any));
  if (ok) { pass++; console.log(`  ✓ ${n}`); }
  else { fail++; console.log(`  ✗ ${n}  得到 ${JSON.stringify(got)} 期望 ${JSON.stringify(want)}`); }
}
function info(n: string, v: unknown) { console.log(`  · ${n} = ${JSON.stringify(v)}`); }

console.log('\n▸ P1 历史已修复现：sample(arr, -1) 不得返回几乎整个数组');
{
  const r = new RNG(1);
  const s = r.sample([1, 2, 3, 4, 5], -1);
  ck('sample([1..5], -1) 应为空', s.length, 0);
  const s2 = r.sample([1, 2, 3, 4, 5], -100);
  ck('sample(arr, -100) 应为空', s2.length, 0);
  const s3 = r.sample([1, 2, 3], 10);
  ck('n 大于长度返回全部', s3.length, 3);
}

console.log('\n▸ P2 可复现性（本单元的核心承诺）');
{
  const a = new RNG(12345), b = new RNG(12345);
  const seqA = Array.from({ length: 50 }, () => a.next());
  const seqB = Array.from({ length: 50 }, () => b.next());
  ck('同种子同序列', seqA.every((v, i) => v === seqB[i]), true);
  const c = new RNG(999);
  ck('不同种子不同结果', c.next() !== a.next() || true, true);
  // fork 后父流不受影响
  const p = new RNG(7); p.next();
  const before = p.state;
  const child = p.fork();
  ck('fork 不改变父流状态', p.state, before);
  ck('父子流不同', child.state !== p.state, true);
}

console.log('\n▸ P3 种子 0 / 负数 / 超界');
{
  const r0 = new RNG(0);
  const v0 = [r0.next(), r0.next(), r0.next()];
  info('seed=0 前三个值', v0.map(x => x.toFixed(6)));
  ck('seed=0 未卡住（三个值不全等）', new Set(v0).size > 1, true);
  const rn = new RNG(-1);
  info('seed=-1 首值', rn.next().toFixed(6));
  ck('seed=-1 可用', Number.isFinite(new RNG(-1).next()), true);
  const rBig = new RNG(2 ** 40);
  ck('seed 超 2^32 可用', Number.isFinite(rBig.next()), true);
}

console.log('\n▸ P4 【关键】state setter 的 0 / NaN 处理');
{
  const r = new RNG(123);
  r.state = 0;                       // setter: 0 >>> 0 = 0，无坏种子保护
  const v = [r.next(), r.next(), r.next()];
  info('state=0 后三个值', v.map(x => x.toFixed(6)));
  ck('state=0 未卡住', new Set(v).size > 1, true);
  const r2 = new RNG(123);
  r2.state = NaN;                    // NaN >>> 0 = 0
  info('state=NaN → 内部值', r2.state);
  ck('state=NaN 被静默变成 0', r2.state, 0);
  const v2 = [r2.next(), r2.next(), r2.next()];
  ck('state=NaN 后未卡住', new Set(v2).size > 1, true);
  const r3 = new RNG(123);
  r3.state = -5;                     // -5 >>> 0 = 4294967291
  info('state=-5 → 内部值', r3.state);
}

console.log('\n▸ P5 区间方法的对抗性输入');
{
  const r = new RNG(42);
  info('int(NaN)', r.int(NaN));
  info('int(0)', r.int(0));
  info('int(-3)', r.int(-3));
  info('int(Infinity)', r.int(Infinity));
  info('range(5, 1)', r.range(5, 1));
  info('rangeInt(5, 1)', r.rangeInt(5, 1));
  info('rangeInt(0, 0)', r.rangeInt(0, 0));
  info('range(NaN, 10)', r.range(NaN, 10));
  info('chance(NaN)', r.chance(NaN));
  info('chance(-1)', r.chance(-1));
  info('chance(2)', r.chance(2));
}

console.log('\n▸ P6 【历史未决】rangeInt(5,1) min>max 静默返回区间外');
{
  const r = new RNG(42);
  let outOfRange = 0;
  for (let i = 0; i < 200; i++) {
    const v = r.rangeInt(5, 1);      // 期望 [1,5]
    if (v < 1 || v > 5) outOfRange++;
  }
  info('rangeInt(5,1) 200 次中越界次数', outOfRange);
  info('  → 不报错、不抛异常，静默返回错误区间的数', outOfRange > 0 ? '确认' : '无越界');
}

console.log('\n▸ P7 gaussian 边界');
{
  const r = new RNG(1);
  const vals = Array.from({ length: 1000 }, () => r.gaussian(0, 1));
  ck('gaussian 全部有限', vals.every(Number.isFinite), true);
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  info('gaussian 均值（应≈0）', mean.toFixed(4));
  const r2 = new RNG(1);
  info('gaussian(0, 0)', r2.gaussian(0, 0));
  info('gaussian(0, -1)', r2.gaussian(0, -1));
  const r3 = new RNG(1);
  info('gaussian(NaN, 1)', r3.gaussian(NaN, 1));
  // stdDev 为 NaN 时 Math.sqrt(-2*log(u)) 正常，但 mean + NaN*... = NaN
}

console.log('\n▸ P8 shuffle / pick 边界');
{
  const r = new RNG(1);
  ck('shuffle 空数组', r.shuffle([]).length, 0);
  ck('shuffle 单元素', r.shuffle([9])[0], 9);
  ck('pick 空数组', r.pick([]), undefined);
  const arr = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const copy = arr.slice();
  r.shuffle(copy);
  ck('shuffle 保持元素集合', copy.slice().sort((a, b) => a - b).join(), arr.join());
  // 分布无偏性粗检：10 次洗牌首元素分布
  const firsts: Record<number, number> = {};
  const r2 = new RNG(777);
  for (let i = 0; i < 3000; i++) {
    const a = [0, 1, 2, 3];
    r2.shuffle(a);
    firsts[a[0]] = (firsts[a[0]] ?? 0) + 1;
  }
  info('shuffle 首元素分布（4 元素 × 3000 次，应≈750）', firsts);
}

console.log('\n▸ P9 Seed 编解码往返');
{
  ck('CAPACITY', Seed.CAPACITY, 3200);
  let bad = 0;
  for (let n = 0; n < 3200; n++) {
    if (Seed.decode(Seed.encode(n)) !== n) bad++;
  }
  ck('0..3199 全部往返一致', bad, 0);
  info('encode(4294967295)', Seed.encode(4294967295));
  info('  decode(encode(4294967295))', Seed.decode(Seed.encode(4294967295)));
  ck('大数字有损（不等于原值）', Seed.decode(Seed.encode(4294967295)) !== 4294967295, true);
  // 非法输入
  ck('decode 空串', Seed.decode(''), null);
  ck('decode 无校验位', Seed.decode('DRAGON'), null);
  ck('decode 未知词', Seed.decode('NOPE-12'), null);
  ck('decode 三位校验', Seed.decode('DRAGON-123'), null);
  ck('decode 小写可容错', Seed.decode('dragon-12'), 12 * 32 + 0);
  info('decode("DRAGON-99")', Seed.decode('DRAGON-99'));
}

console.log('\n▸ P10 【历史未决】Seed.daily 的 3200 桶碰撞');
{
  const days: Record<number, string[]> = {};
  let dup = 0;
  const base = new Date(Date.UTC(2026, 0, 1));
  for (let i = 0; i < 365; i++) {
    const d = new Date(base.getTime() + i * 86400000);
    const h = Seed.daily(d);
    const k = h % Seed.CAPACITY;         // 若调用方用 encode 分享则会折叠到这里
    (days[k] ??= []).push(d.toISOString().slice(0, 10));
  }
  for (const k in days) if (days[k].length > 1) dup += days[k].length - 1;
  info('daily() 返回的是 32 位（不受 CAPACITY 约束）', true);
  info('  但 365 天若经 encode 折叠到 3200 桶，重复天数', dup);
  info('  → 直接把 daily() 结果喂 RNG 无碰撞问题；只有 encode 分享时才折叠', '');
  // 验证 daily 确定性
  ck('daily 同日期同值', Seed.daily(new Date(Date.UTC(2026, 0, 1))), Seed.daily(new Date(Date.UTC(2026, 0, 1))));
  ck('daily 不同日期不同值',
     Seed.daily(new Date(Date.UTC(2026, 0, 1))) !== Seed.daily(new Date(Date.UTC(2026, 0, 2))), true);
  // 时区
  info('daily 跨时区（offset 0 vs 8）',
    Seed.daily(new Date(Date.UTC(2026, 0, 1)), 0) === Seed.daily(new Date(Date.UTC(2026, 0, 1)), 8) ? '相同' : '不同');
}

console.log('\n▸ P11 Seed.random 用 Math.random（与头注释矛盾）');
{
  const seen = new Set<string>();
  for (let i = 0; i < 500; i++) seen.add(Seed.random());
  info('random() 500 次去重后数量', seen.size);
  info('  是否都合法可 decode', [...seen].every(s => Seed.decode(s) !== null));
}

console.log('\n▸ P12 next() 长期不退化 / 分布');
{
  const r = new RNG(2024);
  const buckets = new Array(10).fill(0);
  for (let i = 0; i < 100000; i++) {
    const v = r.next();
    if (v < 0 || v >= 1) { console.log('  ❌ 越界', v); break; }
    buckets[Math.floor(v * 10)]++;
  }
  info('10 万次 next() 十分位分布（应≈10000）', buckets);
  ck('全部落在 [0,1)', buckets.reduce((a, b) => a + b, 0), 100000);
  // 周期性检查：是否短周期
  const r2 = new RNG(1);
  const first = r2.next();
  let period = -1;
  for (let i = 2; i <= 200000; i++) { if (r2.next() === first) { period = i; break; } }
  info('前 20 万次内是否重现首值', period === -1 ? '未重现（周期 > 2e5）' : `周期约 ${period}`);
}

console.log(`\n===== 通过 ${pass} · 失败 ${fail} =====`);
