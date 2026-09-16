const MAX_BODY: usize = 8 * 1024 * 1024;

pub fn read_body(req: &Request) -> Vec<u8> {
    let n = req.content_length();
    Vec::with_capacity(n.min(MAX_BODY))
}
