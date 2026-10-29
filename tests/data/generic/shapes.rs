pub trait Shape {
    fn area(&self) -> f64;

    fn describe(&self) -> String {
        format!("area {}", self.area())
    }
}

pub struct Circle {
    radius: f64,
}

impl Circle {
    pub fn new(radius: f64) -> Self {
        Circle { radius }
    }
}

impl Shape for Circle {
    fn area(&self) -> f64 {
        square(self.radius) * 3.14
    }
}

fn square(x: f64) -> f64 {
    x * x
}

fn main() {
    let c = Circle::new(2.0);
    println!("{}", c.describe());
}
