pub struct Formatter {
    cents: bool,
}

impl Formatter {
    pub fn new() -> Self {
        Formatter { cents: true }
    }

    pub fn format(&self, value: i64) -> String {
        round(value).to_string()
    }
}

pub fn round(value: i64) -> i64 {
    value
}
