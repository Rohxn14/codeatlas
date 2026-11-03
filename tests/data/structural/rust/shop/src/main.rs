mod report;
mod store;

use std::collections::HashMap;

use crate::store::{Item as Product, Store};
use money_fmt::Formatter;

fn main() {
    let mut store = Store::new();
    store.add(Product::new("tea"));
    let formatter = Formatter::new();
    let text = formatter.format(store.total());
    println!("{}", text);
    report::print(&store);
    let _prices: HashMap<String, i64> = HashMap::new();
    helper();
}

fn helper() {}
