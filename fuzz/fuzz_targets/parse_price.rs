#![no_main]
use libfuzzer_sys::fuzz_target;
fuzz_target!(|v: &[u8]| {
    if let Some(n) = shopping_sessions::price::parse(v) {
        assert!((1..=10_000_000).contains(&n));
        assert!(v.iter().all(u8::is_ascii_digit));
    }
});
