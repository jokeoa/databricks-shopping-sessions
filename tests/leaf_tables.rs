use shopping_sessions::{csv::split_line, price, ts};
#[test]
fn quotes_and_bytes() {
    for bad in [
        b"\"".as_slice(),
        b"\"\"\"",
        b"\"\"x\"",
        b"\"x\"\"",
        b"x\"",
        b"\"a,b\"",
    ] {
        assert!(split_line::<1>(bad).is_err());
    }
    assert_eq!(
        split_line::<3>(b"\"\", u1,\r").unwrap(),
        [b"".as_slice(), b" u1", b"\r"]
    );
}
#[test]
fn calendar_and_digits() {
    assert_eq!(
        ts::parse(b"2028-03-01T00:15:00+01:00"),
        ts::parse(b"2028-02-29T23:15:00Z")
    );
    for bad in [
        b"1900-02-29T00:00:00Z".as_slice(),
        b"2026-01-01T24:00:00Z",
        b"2026-01-01T00:00:00+24:00",
        b"2026-01-01T00:00:60Z",
        b"-1",
        b"1e6",
        b"",
    ] {
        assert_eq!(ts::parse(bad), Err(ts::Bad::Format));
    }
    assert!(ts::parse(b"2000-02-29T00:00:00-00:00").is_ok());
    assert_eq!(ts::parse(b"99999999999999999999999"), Err(ts::Bad::Range));
    assert_eq!(ts::parse(b"000000000000000000000123"), Ok(123));
    for bad in ["", "000", "10000001", "٢٥٠", "２５０", "19.99", "-5", "5\r"] {
        assert_eq!(price::parse(bad.as_bytes()), None);
    }
    assert_eq!(
        price::parse(b"0000000000000000000000010000000"),
        Some(10_000_000)
    );
}
#[test]
fn every_chunk_boundary() {
    let input = b"head\n\nabc\r,xx\nvery long line crossing several chunks\ntail";
    let mut expected = vec![];
    shopping_sessions::input::lines(input, 0, input.len(), |off, v| {
        expected.push((off, v.to_vec()))
    });
    for size in 1..input.len() {
        let mut found = vec![];
        for start in (0..input.len()).step_by(size) {
            shopping_sessions::input::lines(input, start, start + size, |off, v| {
                found.push((off, v.to_vec()))
            });
        }
        assert_eq!(found, expected);
    }
}
#[test]
fn vector_masks_match_scalar_on_all_lengths() {
    let alphabet = b"ab,\",ab\r01,\0\xff";
    let mut rng = 61234567u64;
    for len in 0..=180 {
        for _ in 0..100 {
            let bytes: Vec<u8> = (0..len)
                .map(|_| {
                    rng ^= rng << 13;
                    rng ^= rng >> 7;
                    rng ^= rng << 17;
                    alphabet[rng as usize % alphabet.len()]
                })
                .collect();
            macro_rules! check {
                ($n:expr) => {
                    assert_eq!(
                        split_line::<$n>(&bytes),
                        shopping_sessions::csv::scalar::<$n>(&bytes)
                    );
                };
            }
            check!(2);
            check!(4);
            check!(7);
        }
    }
}
