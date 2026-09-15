#[tauri::command]
pub fn open(p: String) -> String {
    std::fs::read_to_string(&p).unwrap_or_default()
}
