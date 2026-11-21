#![no_main]
use libfuzzer_sys::fuzz_target;
use shopping_sessions::ts::{f1, parse};
fuzz_target!(|v: &[u8]| {
    let result = parse(v);
    if let Some(expected) = f1(v) {
        assert_eq!(result, Ok(expected));
    }
});
