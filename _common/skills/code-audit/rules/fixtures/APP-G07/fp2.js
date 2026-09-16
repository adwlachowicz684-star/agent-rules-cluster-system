// FP2：失效路径只出现在注释里 —— 必须剥注释后再判，否则会误报
// 早期版本曾把 vite.config.ts 注释里的 `from '../../js/plugin-sdk.js'`
// 当成真实 import，产生误报。
export function build() {
  return 1
}
