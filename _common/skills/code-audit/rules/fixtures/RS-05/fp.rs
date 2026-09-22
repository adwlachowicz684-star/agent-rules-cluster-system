use std::io::Read;

const MAX: u64 = 1 << 20;

#[tauri::command]
pub fn open(p: &std::path::Path) -> Result<String, String> {
    let c = p.canonicalize().map_err(|e| e.to_string())?;
    if !c.starts_with(&app_root()) {
        return Err("outside root".into());
    }
    let mut f = std::fs::File::open(c).map_err(|e| e.to_string())?;
    let mut buf = Vec::new();
    f.take(MAX).read_to_end(&mut buf).map_err(|e| e.to_string())?;
    String::from_utf8(buf).map_err(|e| e.to_string())
}
