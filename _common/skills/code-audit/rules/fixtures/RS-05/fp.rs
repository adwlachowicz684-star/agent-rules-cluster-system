#[tauri::command]
pub fn open(p: String) -> Result<String, String> {
    let c = std::path::Path::new(&p).canonicalize().map_err(|e| e.to_string())?;
    if !c.starts_with(&app_root()) {
        return Err("outside root".into());
    }
    std::fs::read_to_string(c).map_err(|e| e.to_string())
}
