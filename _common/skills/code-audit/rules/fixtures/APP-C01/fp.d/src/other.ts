// 内部辅助：不 export，交由本模块使用
function internalThing() {
  return 1;
}

export function otherThing() {
  return internalThing();
}
