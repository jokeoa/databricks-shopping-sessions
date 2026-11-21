use crate::{
    Map,
    key::IdKey,
    record::{Click, Event},
    refdata::Refs,
    ts,
};
#[derive(Default)]
pub struct Person {
    pub events: Vec<Event>,
    pub clicks: Vec<Click>,
}
#[derive(Clone, Debug)]
pub struct UserDay {
    pub person: IdKey,
    pub day: i32,
    pub sessions: i64,
    pub events: i64,
    pub cents: i64,
    pub top: Option<usize>,
}
#[derive(Default)]
pub struct Batch {
    pub users: Vec<UserDay>,
    pub campaigns: crate::campaign::CampaignDays,
    pub assist_pairs: u64,
    pub max_active: usize,
    pub max_events: usize,
    pub max_clicks: usize,
}
#[inline]
fn add_category(daily: &mut Map<usize, i64>, event: &Event) {
    if event.cents > 0 {
        *daily.entry(event.category).or_default() += i64::from(event.cents);
    }
}
fn flush(batch: &mut Batch, row: &mut Option<UserDay>, cats: &mut Map<usize, i64>) {
    if let Some(mut row) = row.take() {
        row.top = cats
            .drain()
            .max_by(|(a, x), (b, y)| x.cmp(y).then_with(|| b.cmp(a)))
            .map(|(k, _)| k);
        batch.users.push(row);
    }
}
pub fn process(
    name: IdKey,
    events: &mut [Event],
    clicks: &mut [Click],
    r: &Refs,
    batch: &mut Batch,
) {
    if events.is_empty() {
        return;
    }
    events.sort_unstable_by_key(|e| e.ts);
    let reversed = crate::mutation("reverse_click_tie");
    clicks.sort_unstable_by(|a, b| {
        a.ts.cmp(&b.ts).then_with(|| {
            if reversed {
                a.id.cmp_bytes(&b.id)
            } else {
                b.id.cmp_bytes(&a.id)
            }
        })
    });
    batch.max_events = batch.max_events.max(events.len());
    batch.max_clicks = batch.max_clicks.max(clicks.len());
    let mut active: Map<usize, usize> = Map::default();
    let mut cats = Map::default();
    let mut row: Option<UserDay> = None;
    let (mut at, mut lo, mut hi) = (0, 0, 0);
    let gap = ts::GAP - i64::from(crate::mutation("gap_inclusive"));
    let window = ts::WEEK - i64::from(crate::mutation("exclude_week"));
    while at < events.len() {
        let start = events[at].ts;
        let day = start.div_euclid(ts::DAY) as i32;
        if row.as_ref().is_some_and(|u| u.day != day) {
            flush(batch, &mut row, &mut cats);
        }
        let user_row = row.get_or_insert(UserDay {
            person: name,
            day,
            sessions: 0,
            events: 0,
            cents: 0,
            top: None,
        });
        let mut revenue = 0;
        let first = at;
        loop {
            let e = events[at];
            add_category(&mut cats, &e);
            revenue += i64::from(e.cents);
            at += 1;
            if at == events.len() || events[at].ts - e.ts > gap {
                break;
            }
        }
        user_row.events += (at - first) as i64;
        user_row.sessions += 1;
        user_row.cents += revenue;
        while hi < clicks.len() && clicks[hi].ts <= start {
            *active.entry(clicks[hi].campaign).or_default() += 1;
            hi += 1;
        }
        while lo < hi && clicks[lo].ts < start - window {
            let campaign = clicks[lo].campaign;
            let count = active.get_mut(&campaign).expect("active click");
            *count -= 1;
            if *count == 0 {
                active.remove(&campaign);
            }
            lo += 1;
        }
        let winner = if lo == hi {
            r.organic
        } else {
            clicks[hi - 1].campaign
        };
        #[cfg(feature = "diag")]
        crate::diag::session(
            crate::diag::Session {
                name,
                start,
                day,
                events: at - first,
                cents: revenue,
                winner,
            },
            active.keys().copied(),
            r,
        );
        let credit = batch.campaigns.get(winner, day);
        credit[0] += 1;
        credit[1] += i64::from(revenue > 0);
        credit[2] += revenue;
        for campaign in active.keys() {
            batch.campaigns.get(*campaign, day)[3] += 1;
        }
        batch.assist_pairs += active.len() as u64;
        batch.max_active = batch.max_active.max(active.len());
    }
    flush(batch, &mut row, &mut cats);
}
