use shopping_sessions::{csv, fast::Source, input, key::IdKey};
use std::path::Path;
#[test]
fn vector_tail_and_long_keys() {
    for n in [15, 16, 17, 31, 32, 63, 64, 65, 127, 128, 129] {
        let mut v = vec![b'a'; n];
        v[1] = b',';
        v[n - 2] = b',';
        assert_eq!(csv::split_line::<3>(&v), csv::scalar::<3>(&v));
        v[2] = b'"';
        v[n - 3] = b'"';
        assert_eq!(csv::split_line::<3>(&v), csv::scalar::<3>(&v));
    }
    let a = IdKey::encode(b"aaaaaa-long-shared-prefix-a");
    let b = IdKey::encode(b"aaaaaa-long-shared-prefix-b");
    assert!(a.cmp_bytes(&b).is_lt());
}
#[test]
#[cfg_attr(
    miri,
    ignore = "Miri does not implement file-backed mmap; run the native contract too"
)]
fn readonly_mapped_records() {
    let p = Path::new("testdata/fixtures/E20/input/events/part-00000.csv");
    let bytes = std::fs::read(p).unwrap();
    let mapped = Source::open(p).unwrap();
    assert_eq!(mapped.data(), bytes);
    let mut rows = 0;
    for offset in (0..bytes.len()).step_by(7) {
        input::lines(mapped.data(), offset, offset + 7, |_, _| rows += 1);
    }
    assert_eq!(rows, bytes.split_inclusive(|&b| b == b'\n').count() - 1);
}
