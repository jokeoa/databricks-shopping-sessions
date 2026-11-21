#![no_main]
use libfuzzer_sys::fuzz_target;
use shopping_sessions::Map;
#[allow(dead_code)]
mod key {
    include!("../../src/key.rs");
    pub fn check(a: &[u8], b: &[u8]) {
        let ka = IdKey::encode(a);
        let kb = IdKey::encode(b);
        assert_eq!(ka.cmp_bytes(&kb), a.cmp(b));
        assert_eq!(ka == kb, a == b);
        assert_eq!(ka.bytes(), a);
        // Long strings normally live for one dataset. A fuzzer tests millions
        // of unrelated datasets in one process, so each input gets a fresh pool.
        *strings().lock().unwrap() = Long::default();
    }
}
fuzz_target!(|v: &[u8]| {
    if let Some((&at, body)) = v.split_first() {
        let (a, b) = body.split_at(usize::from(at) % (body.len() + 1));
        key::check(a, b);
    }
});
