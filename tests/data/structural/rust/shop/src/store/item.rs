pub struct Item {
    name: String,
}

impl Item {
    pub fn new(name: &str) -> Self {
        Item { name: name.to_string() }
    }

    pub fn price(&self) -> i64 {
        Self::base() + crate::report::tax(Self::base())
    }

    fn base() -> i64 {
        100
    }
}
