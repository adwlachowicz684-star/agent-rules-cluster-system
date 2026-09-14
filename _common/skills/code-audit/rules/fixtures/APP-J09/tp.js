// 案例2：有清空，但注册在 window 上 → 真泄漏（window 永远不会被清空）
function renderPanel() {
  const box = document.getElementById('p');
  box.innerHTML = '';
  window.addEventListener('resize', () => relayout());
  window.addEventListener('keydown', onKey);
}
