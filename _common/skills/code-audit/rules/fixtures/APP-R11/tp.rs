// 对外命令：path 直接来自 IPC，无任何路径约束 → 可读取任意文本文件
pub fn read_preview(path: &str, max: usize) -> Result<String, String> {
    let p = Path::new(path);
    if !p.is_file() {
        return Err(format!("不是文件或不存在: {path}"));
    }
    let mut text = fs::read_to_string(p).map_err(|e| format!("读取失败: {e}"))?;
    if text.len() > max {
        text.truncate(max);
    }
    Ok(text)
}
