use shopping_sessions::{
    campaign::CampaignDays,
    key::IdKey,
    output,
    person::{Batch, UserDay},
    refdata::Refs,
};
use std::{fs, path::Path};
#[test]
fn published_failures_distinguish_totals_and_global_duplicate_keys() {
    let refs = Refs::load(Path::new("testdata/fixtures/E8/input")).unwrap();
    let root = std::env::temp_dir().join(format!("ss-selfcheck-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    for (code, multiple) in [
        (0, false),
        (5, false),
        (6, false),
        (7, false),
        (8, false),
        (5, true),
    ] {
        let user = UserDay {
            person: IdKey::encode(b"k"),
            day: 0,
            sessions: 1,
            events: 1,
            cents: 3,
            top: Some(0),
        };
        let mut batch = Batch {
            users: vec![user.clone()],
            campaigns: CampaignDays::default(),
            ..Default::default()
        };
        let mut batches = vec![];
        let duplicate = code == 8 || multiple;
        if duplicate {
            batches.push(Batch {
                users: vec![user],
                ..Default::default()
            });
        }
        let n = 1 + i64::from(duplicate);
        *batch.campaigns.get(0, 0) = [
            n + i64::from(code == 5),
            n,
            3 * n + i64::from(code == 6 || multiple),
            if code == 7 || multiple { 0 } else { n },
        ];
        batches.push(batch);
        let dir = root.join(format!("{code}-{multiple}"));
        let status = output::publish(&dir, batches, &refs)
            .err()
            .map_or(0, |e| e.0);
        assert_eq!(status, code);
        assert!(dir.join("campaign_daily/part-0.parquet").is_file());
    }
    fs::remove_dir_all(root).unwrap();
}
