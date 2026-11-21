#![no_main]
use libfuzzer_sys::fuzz_target;
use shopping_sessions::csv::{scalar, split_line};
fuzz_target!(|v: &[u8]| {
    assert_eq!(split_line::<2>(v), scalar::<2>(v));
    assert_eq!(split_line::<4>(v), scalar::<4>(v));
    assert_eq!(split_line::<7>(v), scalar::<7>(v));
});
