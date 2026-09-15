// G07：import 的模块不存在 → 整个模块图加载失败
import * as picons from './preset-icons.js';
export function build() { return picons.loadLibrary(); }
