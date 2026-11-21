use parquet::{
    file::reader::{FileReader, SerializedFileReader},
    record::Field,
};
use shopping_sessions::{config::Config, run, ts};
use std::{fs, fs::File, path::Path};
fn expected(case: &Path, table: &str) -> Vec<Vec<String>> {
    let text = fs::read_to_string(case.join("expected").join(format!("{table}.csv"))).unwrap();
    let mut rows = Vec::new();
    for raw in text.split_terminator('\n').skip(1) {
        let mut row: Vec<_> = raw.split(',').map(str::to_owned).collect();
        let day = usize::from(table == "campaign_daily") + 1;
        row[day] =
            (ts::f1(format!("{}T00:00:00Z", row[day]).as_bytes()).unwrap() / ts::DAY).to_string();
        rows.push(row);
    }
    rows.sort();
    rows
}
fn actual(path: &Path) -> Vec<Vec<String>> {
    let mut rows = Vec::new();
    for file in fs::read_dir(path).unwrap() {
        let reader = SerializedFileReader::new(File::open(file.unwrap().path()).unwrap()).unwrap();
        for row in reader.get_row_iter(None).unwrap() {
            rows.push(
                row.unwrap()
                    .get_column_iter()
                    .map(|(_, f)| match f {
                        Field::Str(v) => v.clone(),
                        Field::Date(n) => n.to_string(),
                        Field::Long(v) => v.to_string(),
                        Field::Null => String::new(),
                        _ => panic!("unexpected field {f:?}"),
                    })
                    .collect(),
            );
        }
    }
    rows.sort();
    rows
}
#[test]
fn both_drivers_match_all_hand_written_cases() {
    let tmp = std::env::temp_dir().join(format!("ss-cases-{}", std::process::id()));
    fs::create_dir(&tmp).unwrap();
    for suite in ["fixtures", "fixtures-extra"] {
        let root = Path::new("testdata").join(suite);
        let descriptions = fs::read_to_string(root.join("README.md")).unwrap();
        for d in fs::read_dir(root).unwrap() {
            let case = d.unwrap().path();
            if !case.is_dir() {
                continue;
            }
            for mode in ["simple", "fast"] {
                let id = case.file_name().unwrap().to_str().unwrap();
                let out = tmp.join(format!("{id}-{mode}"));
                let mut cfg =
                    Config::load(&[case.join("input").into(), out.clone().into()], mode).unwrap();
                cfg.mode = mode.into();
                cfg.threads = 3;
                cfg.chunk = 64;
                run(&cfg).unwrap();
                for table in ["user_daily", "campaign_daily"] {
                    assert_eq!(
                        expected(&case, table),
                        actual(&out.join(table)),
                        "{mode} {id} {table}: {}",
                        descriptions
                            .lines()
                            .find(|s| s.starts_with(&format!("| {id} |")))
                            .unwrap_or("")
                    );
                }
            }
        }
    }
    fs::remove_dir_all(tmp).unwrap();
}
