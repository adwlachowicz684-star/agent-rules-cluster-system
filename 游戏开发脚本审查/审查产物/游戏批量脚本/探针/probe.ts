import { DamagePipeline } from '../src/damage-pipeline/DamagePipeline';
import { ModifierSet } from '../src/damage-pipeline/Modifier';
import { IDamageable, DamageResult } from '../src/damage-pipeline/IDamageable';

const log = (t: string, v: unknown) => console.log(`  ${t}: ${JSON.stringify(v)}`);

class Dummy implements IDamageable {
  hp = 1000; maxHp = 1000; armor = 0; resistances = {};
  applyDamage(r: DamageResult) { this.hp -= r.value; }
  isAlive() { return this.hp > 0; }
}

console.log('\n===== P1 · onResult 在回调内取消订阅 =====');
{
  const p = DamagePipeline.createDefault();
  const order: string[] = [];
  const offA = p.onResult(() => { order.push('A'); offA(); });
  p.onResult(() => order.push('B'));
  p.onResult(() => order.push('C'));
  p.apply({ raw: 10 }, new Dummy());
  log('期望 A/B/C 都执行，实际', order);
}

console.log('\n===== P2 · simulate 是否有随机性 =====');
{
  const p = DamagePipeline.createDefault();
  const t = new Dummy();
  const r = p.simulate({ raw: 20, crit: false }, t, 5);
  log('simulate x5', r);
  log('是否完全相同', r.every(x => x === r[0]));
}

console.log('\n===== P3 · 自定义 stage 返回 NaN 是否拦截 =====');
{
  const p = DamagePipeline.createDefault();
  p.addStage('bad', () => NaN, 35);
  const res = p.calculate({ raw: 20 }, new Dummy());
  log('value', res.value);
  log('是 NaN 吗', Number.isNaN(res.value));
}

console.log('\n===== P4 · hitId 重复是否去重 =====');
{
  const p = DamagePipeline.createDefault();
  const t = new Dummy();
  p.apply({ raw: 10, hitId: 'swing1' }, t);
  p.apply({ raw: 10, hitId: 'swing1' }, t);
  p.apply({ raw: 10, hitId: 'swing1' }, t);
  log('同 hitId 打 3 次后扣血', 1000 - t.hp);
}

console.log('\n===== P5 · Modifier: cached !== Number.NaN 恒真 =====');
{
  log('NaN !== Number.NaN', NaN !== Number.NaN);
  log('正确写法 !Number.isNaN(NaN)', !Number.isNaN(NaN));
}

console.log('\n===== P6 · Modifier.add 返回值 =====');
{
  const m = new ModifierSet();
  const ret = m.add('atk', { type: 'add', value: 5 });
  log('add() 返回', ret);
  log('typeof', typeof ret);
}

console.log('\n===== P7 · Modifier.remove 签名 =====');
{
  const m = new ModifierSet();
  m.add('atk', { type: 'add', value: 5, source: 'weapon', tag: 'equip' });
  m.add('atk', { type: 'add', value: 3, source: 'ring', tag: 'equip' });
  log('初始 count', m.count('atk'));
  try {
    (m as any).remove('atk', 'weapon');
    log('remove(attr,"weapon") 后 count（若报异常说明签名不符）', m.count('atk'));
  } catch (e) { log('remove(attr,string) 抛错', String(e).slice(0, 80)); }
}

console.log('\n===== P8 · 缓存：base 变化与 NaN 组合 =====');
{
  const m = new ModifierSet();
  m.add('atk', { type: 'add', value: 5, source: 'weapon' });
  log('get(atk,10)', m.get('atk', 10));
  log('get(atk,100) base 变了', m.get('atk', 100));
  m.add('atk', { type: 'add', value: NaN, source: 'curse' });
  log('加 NaN 后 get(atk,10)', m.get('atk', 10));
  log('再 get(atk,10)', m.get('atk', 10));
}

console.log('\n===== P9 · 保底 vs immune 边界 =====');
{
  const p = DamagePipeline.createDefault();
  const t = new Dummy();
  const a = p.calculate({ raw: 20 }, t);
  p.addStage('zero', () => 0, 35);
  const b = p.calculate({ raw: 20 }, t);
  p.removeStage('zero');
  p.addStage('tiny', () => 0.02, 35);
  const c = p.calculate({ raw: 20 }, t);
  p.removeStage('tiny');
  p.addStage('neg', () => -5, 35);
  const d = p.calculate({ raw: 20 }, t);
  log('正常', a.value);
  log('stage 归零 -> immune?', { value: b.value, immune: b.immune });
  log('stage 给 0.02', { value: c.value, immune: c.immune });
  log('stage 给 -5', { value: d.value, immune: d.immune });
}

console.log('\n===== P10 · critMul 无 clamp =====');
{
  const p = DamagePipeline.createDefault();
  const t = new Dummy();
  log('critMul=-1', p.calculate({ raw: 20, crit: true, critMul: -1 }, t).value);
  log('critMul=NaN', p.calculate({ raw: 20, crit: true, critMul: NaN }, t).value);
}
