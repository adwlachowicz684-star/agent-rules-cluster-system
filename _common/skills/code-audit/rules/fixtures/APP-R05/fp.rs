use std::path::Path;

pub fn allowed(p: &Path, root: &Path) -> bool {
    match p.canonicalize() {
        Ok(c) => c.starts_with(root),
        Err(_) => false,
    }
}
