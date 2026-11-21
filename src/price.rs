#[inline]
pub fn parse(raw: &[u8]) -> Option<u32> {
    let mut n = 0u32;
    for &byte in raw {
        if !byte.is_ascii_digit() {
            return None;
        }
        n = n * 10 + u32::from(byte - b'0');
        if n > 10_000_000 {
            return None;
        }
    }
    (n > 0).then_some(n)
}
