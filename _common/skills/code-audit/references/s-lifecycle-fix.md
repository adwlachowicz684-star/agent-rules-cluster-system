# 正确写法 · 成对契约与热路径（X–Y 族）

修 X / Y 族缺陷时从这里取代码。
A–H 族见 `fix-code-core.md`，I–O 族见 `fix-code-data.md`，P–W 族见 `fix-code-advanced.md`。

## X 族 · 成对 API 配对

```typescript
// 注册与注销在同一生命周期层级对称出现
onLoad()   { this.node.on(EVT, this.onTouch, this); }          // 只注册一次
onEnable() { this.target?.on('custom', this.onCustom, this); }  // 每次激活
onDisable(){ this.target?.off('custom', this.onCustom, this); } // 必须配对
onDestroy(){
  this.node.off(EVT, this.onTouch, this);
  this.unscheduleAllCallbacks();          // 只清 this.schedule 的
  this._timer && clearInterval(this._timer);  // setInterval 要各自 clear
  this._tw?.stop();
  this._sp?.decRef();
}
private onTouch() { }    // 具名方法，不能匿名——off 需要同一函数引用
private onCustom() { }
```

```typescript
// 循环任务：持有引用才能停止
private _tw: Tween<Node> = null!;
onLoad()  { this._tw = tween(this.node).repeatForever(tween().to(1, {angle:360})).start(); }
onDestroy(){ this._tw?.stop(); }   // stop() 可重启；clear() 额外释放对象

// 资源：引用计数
resources.load('bg/spriteFrame', SpriteFrame, (err, sp) => {
  if (err || !sp) return;
  this._sp = sp; this._sp.addRef();
});
onDestroy() { this._sp?.decRef(); }

// 成对契约：用 try/finally 兜住释放
const h = acquire();
try { use(h); } finally { release(h); }
```

**⚠ 三套定时器机制各自配对**：`schedule`↔`unschedule`、`setInterval`↔`clearInterval`、
`setTimeout`↔`clearTimeout`，`unscheduleAllCallbacks()` 清不掉 `setInterval`。

**⚠ 自动释放通常不覆盖动态加载的资源**：宿主销毁时的自动清理只管它自己管理的部分，
`load` 来的必须手动释放。释放共享资源前先查依赖树，确认无人使用。

## Y 族 · 热路径

```typescript
// 缓存到初始化，回调内只做增量
private _player: Node = null!;
private _acc = 0;
private readonly _tmp: Item[] = [];      // 复用，不要每帧 new

onLoad() { this._player = find('Canvas/Player')!; }   // 一次

update(dt: number) {
  this._acc += dt;
  if (this._acc < 0.2) return;           // 降频，不必每帧
  this._acc = 0;
  this._tmp.length = 0;                  // 复用而非重新分配
  for (const x of this.items) this._tmp.push(x);
  this.heavyWork();
}
```

**⚠ 每帧的开销会乘 60**：`find` / `getComponent` / `instantiate` / `new` / `JSON.parse`
放进 `update`，在 60fps 下每秒执行 60 次。缓存到 `onLoad`/`start`，回调内只做增量计算。
