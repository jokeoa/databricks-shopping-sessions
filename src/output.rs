use crate::{
    Error, Map, Result,
    person::{Batch, UserDay},
    refdata::Refs,
};
use parquet::{
    data_type::{ByteArray, ByteArrayType, DataType, Int32Type, Int64Type},
    errors::ParquetError,
    file::{
        properties::{EnabledStatistics, WriterProperties},
        writer::{SerializedFileWriter, SerializedRowGroupWriter},
    },
    schema::parser::parse_message_type,
};
use std::{
    collections::HashSet,
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
    sync::Arc,
};

const USER: &str = "message user_daily { REQUIRED BINARY user_id (STRING); REQUIRED INT32 day (DATE); REQUIRED INT64 sessions; REQUIRED INT64 events; REQUIRED INT64 revenue_cents; OPTIONAL BINARY top_category (STRING); }";
const CAMPAIGN: &str = "message campaign_daily { REQUIRED BINARY campaign_id (STRING); REQUIRED BINARY channel (STRING); REQUIRED INT32 day (DATE); REQUIRED INT64 sessions; REQUIRED INT64 purchasing_sessions; REQUIRED INT64 revenue_cents; REQUIRED INT64 assisted_sessions; }";
type PResult<T> = std::result::Result<T, ParquetError>;
fn column<T: DataType>(
    group: &mut SerializedRowGroupWriter<'_, File>,
    values: Vec<T::T>,
    levels: Option<&[i16]>,
) -> PResult<()> {
    let mut col = group.next_column()?.expect("schema column");
    col.typed::<T>().write_batch(&values, levels, None)?;
    col.close()
}
fn write<R>(
    file: File,
    schema: &str,
    rows: &[R],
    mut emit: impl FnMut(&mut SerializedRowGroupWriter<'_, File>, &[R]) -> PResult<()>,
) -> PResult<()> {
    let props = WriterProperties::builder()
        .set_dictionary_enabled(false)
        .set_statistics_enabled(EnabledStatistics::None)
        .build();
    let mut writer =
        SerializedFileWriter::new(file, Arc::new(parse_message_type(schema)?), Arc::new(props))?;
    for chunk in rows.chunks(1_000_000) {
        let mut group = writer.next_row_group()?;
        emit(&mut group, chunk)?;
        group.close()?;
    }
    writer.close()?;
    Ok(())
}
fn users(file: File, rows: &[UserDay], r: &Refs) -> PResult<()> {
    write(file, USER, rows, |g, rows| {
        column::<ByteArrayType>(
            g,
            rows.iter().map(|u| u.person.bytes().into()).collect(),
            None,
        )?;
        column::<Int32Type>(g, rows.iter().map(|u| u.day).collect(), None)?;
        for f in [
            |u: &UserDay| u.sessions,
            |u: &UserDay| u.events,
            |u: &UserDay| u.cents,
        ] {
            column::<Int64Type>(g, rows.iter().map(f).collect(), None)?;
        }
        let levels: Vec<i16> = rows.iter().map(|u| i16::from(u.top.is_some())).collect();
        column::<ByteArrayType>(
            g,
            rows.iter()
                .filter_map(|u| u.top.map(|k| ByteArray::from(r.cats[k].as_slice())))
                .collect(),
            Some(&levels),
        )
    })
}
type CampaignRow = ((usize, i32), [i64; 4]);
fn campaigns(file: File, rows: &[CampaignRow], r: &Refs) -> PResult<()> {
    write(file, CAMPAIGN, rows, |g, rows| {
        column::<ByteArrayType>(
            g,
            rows.iter()
                .map(|((c, _), _)| r.channels[*c].0.as_slice().into())
                .collect(),
            None,
        )?;
        column::<ByteArrayType>(
            g,
            rows.iter()
                .map(|((c, _), _)| r.channels[*c].1.as_slice().into())
                .collect(),
            None,
        )?;
        column::<Int32Type>(g, rows.iter().map(|((_, d), _)| *d).collect(), None)?;
        for i in 0..4 {
            column::<Int64Type>(g, rows.iter().map(|(_, v)| v[i]).collect(), None)?;
        }
        Ok(())
    })
}
fn problem(path: &Path, e: impl std::fmt::Display) -> Error {
    Error(4, format!("{}: {e}", path.display()))
}
#[derive(Default)]
struct Publication {
    temporary: Vec<(PathBuf, PathBuf)>,
    published: Vec<PathBuf>,
    committed: bool,
}
impl Publication {
    fn part(&mut self, dir: &Path, n: usize) -> Result<File> {
        fs::create_dir_all(dir).map_err(|e| problem(dir, e))?;
        let final_path = dir.join(format!("part-{n}.parquet"));
        let tmp = dir.join(format!(".part-{n}-{}.tmp", std::process::id()));
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&tmp)
            .map_err(|e| problem(&tmp, e))?;
        self.temporary.push((tmp, final_path));
        Ok(file)
    }
    fn commit(&mut self) -> Result<()> {
        for (tmp, dest) in &self.temporary {
            // link is atomic and refuses to overwrite a part belonging to another run.
            fs::hard_link(tmp, dest).map_err(|e| problem(dest, e))?;
            self.published.push(dest.clone());
            fs::remove_file(tmp).map_err(|e| problem(tmp, e))?;
        }
        self.committed = true;
        Ok(())
    }
}
impl Drop for Publication {
    fn drop(&mut self) {
        if !self.committed {
            for p in self
                .published
                .iter()
                .chain(self.temporary.iter().map(|(p, _)| p))
            {
                if let Err(e) = fs::remove_file(p)
                    && e.kind() != std::io::ErrorKind::NotFound
                {
                    eprintln!("cleanup {}: {e}", p.display());
                }
            }
        }
    }
}
pub fn publish(out: &Path, batches: Vec<Batch>, r: &Refs) -> Result<()> {
    let mut tx = Publication::default();
    let mut totals: Map<_, [i64; 4]> = Map::default();
    let capacity = batches.iter().map(|b| b.users.len()).sum();
    let mut check =
        HashSet::with_capacity_and_hasher(capacity, foldhash::fast::RandomState::default());
    let (mut count, mut revenue) = (0, 0);
    let mut dup = false;
    let (mut max_events, mut max_clicks, mut max_active) = (0, 0, 0);
    let dir = out.join("user_daily");
    std::thread::scope(|scope| -> Result<()> {
        let mut handles = Vec::new();
        for (i, batch) in batches.into_iter().enumerate() {
            max_events = max_events.max(batch.max_events);
            max_clicks = max_clicks.max(batch.max_clicks);
            max_active = max_active.max(batch.max_active);
            for u in &batch.users {
                #[cfg(feature = "diag")]
                crate::diag::user(u, r);
                dup |= !check.insert((u.person, u.day));
                count += u.sessions;
                revenue += u.cents;
            }
            let part = tx.part(&dir, i)?;
            handles.push(
                std::thread::Builder::new()
                    .spawn_scoped(scope, move || users(part, &batch.users, r))
                    .map_err(|e| problem(&dir, e))?,
            );
            batch.campaigns.merge_into(&mut totals);
        }
        for handle in handles {
            handle
                .join()
                .map_err(|_| problem(&dir, "writer panicked"))?
                .map_err(|e| problem(&dir, e))?;
        }
        Ok(())
    })?;
    let rows: Vec<_> = totals.into_iter().collect();
    #[cfg(feature = "diag")]
    for ((c, day), v) in &rows {
        crate::diag::campaign(*c, *day, v, r);
    }
    let dir = out.join("campaign_daily");
    campaigns(tx.part(&dir, 0)?, &rows, r).map_err(|e| problem(&dir, e))?;
    tx.commit()?;
    let sessions = rows.iter().map(|(_, v)| v[0]).sum::<i64>();
    let cents = rows.iter().map(|(_, v)| v[2]).sum::<i64>();
    let assisted = rows.iter().map(|(_, v)| v[3]).sum::<i64>();
    let paid = rows
        .iter()
        .filter(|((k, _), _)| *k != r.organic)
        .map(|(_, v)| v[0])
        .sum::<i64>();
    eprintln!(
        "{}",
        serde_json::json!({"user_days":check.len(),"campaign_days":rows.len(),"sessions":sessions,"revenue_cents":cents,"assist_pairs":assisted,"max_events":max_events,"max_clicks":max_clicks,"max_active":max_active})
    );
    let mut first = None;
    for (bad, code, why) in [
        (count != sessions, 5, "session totals"),
        (revenue != cents, 6, "revenue totals"),
        (assisted < paid, 7, "assist count"),
        (dup, 8, "duplicate daily key"),
    ] {
        if bad {
            eprintln!("self-check failed: {why}");
            first.get_or_insert(Error(code, why.into()));
        }
    }
    first.map_or(Ok(()), Err)
}
