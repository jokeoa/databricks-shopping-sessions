use std::{fs, path::Path, process::Command};
#[test]
fn configuration_input_and_publication_errors() {
    let bin = env!("CARGO_BIN_EXE_shopping-sessions");
    let dir = std::env::temp_dir().join(format!("ss-errors-{}", std::process::id()));
    fs::create_dir(&dir).unwrap();
    let input = Path::new("testdata/fixtures/E8/input");
    assert_eq!(
        Command::new(bin).arg("bad").status().unwrap().code(),
        Some(2)
    );
    assert_eq!(
        Command::new(bin)
            .arg(dir.join("missing"))
            .arg(&dir)
            .status()
            .unwrap()
            .code(),
        Some(3)
    );
    fs::create_dir(dir.join("campaign_daily")).unwrap();
    let existing = dir.join("campaign_daily/part-0.parquet");
    fs::write(&existing, b"old").unwrap();
    assert_eq!(
        Command::new(bin)
            .arg(input)
            .arg(&dir)
            .status()
            .unwrap()
            .code(),
        Some(4)
    );
    assert_eq!(fs::read(existing).unwrap(), b"old");
    assert_eq!(fs::read_dir(dir.join("user_daily")).unwrap().count(), 0);
    assert!(
        Command::new(bin)
            .arg(input)
            .arg(dir.join("retry"))
            .status()
            .unwrap()
            .success()
    );
    fs::remove_dir_all(dir).unwrap();
}
