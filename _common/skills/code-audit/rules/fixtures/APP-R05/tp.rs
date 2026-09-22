const FORBIDDEN: &[&str] = &["/etc", "/root"];

pub fn allowed(p: &str) -> bool {
    !FORBIDDEN.iter().any(|f| p.starts_with(f))
}
