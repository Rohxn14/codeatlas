use crate::store::Store;
use money_fmt::format::round;

pub fn print(store: &Store) {
    let rounded = round(store.total());
    println!("{}", rounded);
}

pub fn tax(value: i64) -> i64 {
    value / 10
}
