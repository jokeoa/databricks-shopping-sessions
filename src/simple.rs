use crate::{
    Map, Result,
    input::{self, Files},
    key::IdKey,
    links::Names,
    person::{self, Batch, Person},
    record::{self, Candidate, Counters, Fate},
    refdata::Refs,
};
pub fn run(files: &Files, names: &Names, r: &Refs) -> Result<(Vec<Batch>, Counters)> {
    let mut winners: Map<IdKey, Candidate> = Map::default();
    let mut counts = Counters::default();
    for path in &files.events {
        let data = input::read(path)?;
        input::lines(&data, 0, data.len(), |_, line| {
            match record::event(line, r) {
                Ok((key, c)) => {
                    counts.events[c.fate as usize] += 1;
                    winners
                        .entry(key)
                        .and_modify(|w| {
                            if w.ingest == c.ingest && *w != c {
                                counts.equal_diff += 1;
                            }
                            if c.ingest < w.ingest {
                                *w = c;
                            }
                        })
                        .or_insert(c);
                }
                Err(f) => counts.events[f as usize] += 1,
            }
        });
    }
    let mut people: Map<IdKey, Person> = Map::default();
    for (_, c) in winners {
        counts.winners[c.fate as usize] += 1;
        if c.fate == Fate::Valid {
            people
                .entry(*names.get(&c.user).unwrap_or(&c.user))
                .or_default()
                .events
                .push(c.event);
        }
    }
    for path in &files.clicks {
        let data = input::read(path)?;
        input::lines(&data, 0, data.len(), |_, line| {
            match record::click(line, r) {
                Ok((user, click)) => {
                    counts.clicks[0] += 1;
                    people
                        .entry(*names.get(&user).unwrap_or(&user))
                        .or_default()
                        .clicks
                        .push(click);
                }
                Err(f) => counts.clicks[f as usize] += 1,
            }
        });
    }
    let mut out = Batch::default();
    for (name, mut p) in people {
        person::process(name, &mut p.events, &mut p.clicks, r, &mut out);
    }
    Ok((vec![out], counts))
}
