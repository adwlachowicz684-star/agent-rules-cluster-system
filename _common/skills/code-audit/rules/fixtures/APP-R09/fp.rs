fn check(token: &str) -> bool {
    if token.is_empty() {
        return false;
    }
    verify(token)
}
