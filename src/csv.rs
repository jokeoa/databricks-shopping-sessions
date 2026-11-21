#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum Bad {
    EmptyLine,
    Fields,
    Quote,
}
impl Bad {
    pub fn label(self) -> &'static str {
        match self {
            Self::EmptyLine => "empty_line",
            Self::Fields => "field_count",
            Self::Quote => "quote",
        }
    }
}
#[inline]
pub fn split_line<const N: usize>(line: &[u8]) -> Result<[&[u8]; N], Bad> {
    if line.is_empty() {
        return Err(Bad::EmptyLine);
    }
    let mut fields = [&[][..]; N];
    let mut count = 0;
    for field in line.split(|&b| b == b',') {
        if count == N {
            return Err(Bad::Fields);
        }
        fields[count] = field;
        count += 1;
    }
    if count != N {
        return Err(Bad::Fields);
    }
    for field in &mut fields {
        if field.first() == Some(&b'"') {
            if field.len() < 2 || field.last() != Some(&b'"') {
                return Err(Bad::Quote);
            }
            *field = &field[1..field.len() - 1];
        }
        if memchr::memchr(b'"', field).is_some() {
            return Err(Bad::Quote);
        }
    }
    Ok(fields)
}
