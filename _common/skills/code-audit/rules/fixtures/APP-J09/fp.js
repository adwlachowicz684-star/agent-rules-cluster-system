// 案例1：注册在新建子节点 + 容器清空 → 不泄漏（作者实测成立）
function renderList() {
  const list = document.getElementById('l');
  list.innerHTML = '';
  for (const p of items) {
    const btn = document.createElement('button');
    btn.addEventListener('click', () => nav(p.id));
    list.appendChild(btn);
  }
}
