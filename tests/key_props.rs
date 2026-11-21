use shopping_sessions::key::IdKey;
#[test]
fn order_and_equality_use_all_bytes() {
    let mut values = vec![
        vec![],
        vec![0],
        vec![0, 0],
        b"abcdefghijk-long-common-prefix-a".to_vec(),
        b"abcdefghijk-long-common-prefix-b".to_vec(),
    ];
    let mut random = 123456789u64;
    for len in 0..42 {
        for _ in 0..5 {
            values.push(
                (0..len)
                    .map(|_| {
                        random ^= random << 13;
                        random ^= random >> 7;
                        random ^= random << 17;
                        random as u8
                    })
                    .collect(),
            );
        }
    }
    for a in &values {
        let ka = IdKey::encode(a);
        assert_eq!(ka.bytes(), *a);
        for b in &values {
            let kb = IdKey::encode(b);
            assert_eq!(ka == kb, a == b);
            assert_eq!(ka.cmp_bytes(&kb), a.cmp(b));
        }
    }
}
