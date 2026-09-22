use std::io::Read;

const MAX: u64 = 1 << 20;

#[tauri::command]
pub fn read_config(path: &std::path::Path) -> Result<String, String> {
    // 路径约束：先 canonicalize 再确认落在允许根目录内
    let c = path.canonicalize().map_err(|e| e.to_string())?;
    if !c.starts_with(&app_root()) {
        return Err("outside root".into());
    }
    // 大小有界：take 限制读入字节数
    let mut f = std::fs::File::open(&c).map_err(|e| e.to_string())?;
    let mut buf = Vec::new();
    f.take(MAX).read_to_end(&mut buf).map_err(|e| e.to_string())?;
    String::from_utf8(buf).map_err(|e| e.to_string())
}
