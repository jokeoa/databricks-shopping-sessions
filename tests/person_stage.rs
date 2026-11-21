use shopping_sessions::{
    Map,
    campaign::CampaignDays,
    key::IdKey,
    person,
    record::{Click, Event},
    refdata::Refs,
    ts,
};
use std::{
    fs::{self, File},
    io::{BufWriter, Write},
    path::Path,
};

#[test]
fn gap_midnight_attribution_and_ties() {
    let refs = Refs::load(Path::new("testdata/fixtures/A11/input")).unwrap();
    let (one, two) = (refs.campaigns[&b"c_1"[..]], refs.campaigns[&b"c_2"[..]]);
    let start = refs.first + ts::DAY - 1;
    let last = start + 2 * ts::GAP + 1;
    let event = |ts, cents, category| Event {
        ts,
        cents,
        category,
    };
    let click = |ts, id: &[u8], campaign| Click {
        ts,
        id: IdKey::encode(id),
        campaign,
    };
    let mut events = [
        event(last, 0, 0),
        event(start + ts::GAP, 13, 1),
        event(start, 13, 0),
        event(start, 0, 0),
    ];
    let mut clicks = [
        click(start - ts::WEEK - 1, b"past", two),
        click(start - ts::WEEK, b"week", two),
        click(start, b"k9", two),
        click(start, b"k10", one),
        click(start + 1, b"future", two),
    ];
    let mut batch = person::Batch::default();
    person::process(
        IdKey::encode(b"user"),
        &mut events,
        &mut clicks,
        &refs,
        &mut batch,
    );
    let first_day = (start / ts::DAY) as i32;
    let days: Vec<_> = batch
        .users
        .iter()
        .map(|r| (r.day, r.sessions, r.events, r.cents, r.top))
        .collect();
    assert_eq!(
        days,
        [
            (first_day, 1, 3, 26, Some(0)),
            (first_day + 1, 1, 1, 0, None)
        ]
    );
    let mut aggregate = Map::default();
    batch.campaigns.merge_into(&mut aggregate);
    assert_eq!(aggregate[&(one, first_day)], [1, 1, 26, 1]);
    assert_eq!(aggregate[&(two, first_day)], [0, 0, 0, 1]);
    assert_eq!(aggregate[&(one, first_day + 1)], [0, 0, 0, 1]);
    assert_eq!(aggregate[&(two, first_day + 1)], [1, 0, 0, 1]);

    let mut edge = person::Batch::default();
    person::process(
        IdKey::encode(b"user"),
        &mut [event(start, 0, 0)],
        &mut [
            click(start - ts::WEEK, b"inside", one),
            click(start - ts::WEEK - 1, b"outside", two),
        ],
        &refs,
        &mut edge,
    );
    let mut aggregate = Map::default();
    edge.campaigns.merge_into(&mut aggregate);
    assert_eq!(aggregate.len(), 1);
    assert_eq!(aggregate[&(one, first_day)], [1, 0, 0, 1]);
}

#[test]
fn wide_category_ranks_and_sparse_campaigns() {
    let root = std::env::temp_dir().join(format!("ss-wide-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let fixture = Path::new("testdata/fixtures/A11/input");
    for name in ["manifest.json", "campaigns.csv"] {
        fs::copy(fixture.join(name), root.join(name)).unwrap();
    }
    let mut products = BufWriter::new(File::create(root.join("products.csv")).unwrap());
    writeln!(products, "product_id,category").unwrap();
    for i in 0..=65536 {
        writeln!(products, "p{i},a{i:05}").unwrap();
    }
    products.flush().unwrap();
    let mut refs = Refs::load(&root).unwrap();
    fs::remove_dir_all(root).unwrap();
    assert_eq!(refs.products[&b"p65536"[..]], 65536);
    assert_eq!(refs.cats[refs.unknown], b"unknown");
    let ts = refs.first + ts::DAY;
    refs.end = ts + 3650 * ts::DAY;
    let day = (ts / ts::DAY) as i32;
    let mut dense = CampaignDays::new(&refs, 2, 32 << 20);
    let mut sparse = CampaignDays::new(&refs, 2, 1024);
    assert!(matches!(dense, CampaignDays::Dense { .. }));
    assert!(matches!(sparse, CampaignDays::Sparse(_)));
    for counts in [&mut dense, &mut sparse] {
        *counts.get(0, day) = [0, 0, 0, 2];
        *counts.get(refs.organic, day + 3600) = [1, 1, 17, 0];
    }
    let (mut a, mut b) = (Map::default(), Map::default());
    dense.merge_into(&mut a);
    sparse.merge_into(&mut b);
    assert_eq!(a.len(), 2);
    assert_eq!(a, b);

    // Both timestamps differ by more than 31 bits in milliseconds.
    let mut events = [
        Event {
            ts: ts + 3600 * ts::DAY,
            category: refs.unknown,
            cents: 3,
        },
        Event {
            ts,
            category: 65536,
            cents: 5,
        },
    ];
    let mut batch = person::Batch::default();
    person::process(
        IdKey::encode(b"wide"),
        &mut events,
        &mut [],
        &refs,
        &mut batch,
    );
    let rows: Vec<_> = batch
        .users
        .iter()
        .map(|r| (r.day, r.top, r.cents))
        .collect();
    assert_eq!(
        rows,
        [(day, Some(65536), 5), (day + 3600, Some(refs.unknown), 3)]
    );
}
