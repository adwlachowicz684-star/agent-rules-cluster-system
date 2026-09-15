#[tauri::command]
pub fn read_config(path: String) -> String {
    std::fs::read_to_string(&path).unwrap()
}
