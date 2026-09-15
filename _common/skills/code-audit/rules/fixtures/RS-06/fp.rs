const MAX: usize = 1 << 20;

pub fn buffer(n: usize) -> Vec<u8> {
    Vec::with_capacity(n.min(MAX))
}
