// 整文件读入同样来自外部 path，但先经 resolve_within 收敛到授权根目录内
// → 读不到根外的文件，不构成越权
pub fn read_preview(path: &str, root: &Path, max: usize) -> Result<String, String> {
    let p = resolve_within(root, Path::new(path))?;
    if !p.is_file() {
        return Err(format!("不是文件或不存在: {}", p.display()));
    }
    let mut text = fs::read_to_string(p).map_err(|e| format!("读取失败: {e}"))?;
    if text.len() > max {
        text.truncate(max);
    }
    Ok(text)
}
