mod item;

pub use item::Item;

pub struct Store {
    items: Vec<Item>,
}

impl Store {
    pub fn new() -> Self {
        Store { items: Vec::new() }
    }

    pub fn add(&mut self, item: Item) {
        self.items.push(item);
        self.recount();
    }

    fn recount(&self) {}

    pub fn total(&self) -> i64 {
        self.items.iter().map(|i| i.price()).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adds_an_item() {
        let mut store = Store::new();
        store.add(Item::new("tea"));
    }
}
