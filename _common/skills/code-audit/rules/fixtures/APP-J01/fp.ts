export function listen(trusted: string): () => void {
    const h = (e: MessageEvent) => {
        if (e.origin !== trusted) return;
        handle(e.data);
    };
    window.addEventListener('message', h);
    // 返回取消函数：注册了就要有注销路径
    return () => window.removeEventListener('message', h);
}
