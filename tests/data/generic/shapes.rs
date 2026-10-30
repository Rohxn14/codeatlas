/// A point in the plane.
pub struct Point {
    x: f64,
    y: f64,
}

pub trait Shape {
    fn area(&self) -> f64;
    fn describe(&self) -> String {
        format!("area {}", self.area())
    }
}

impl Point {
    /// Makes a point.
    pub fn new(x: f64, y: f64) -> Self {
        Point { x, y }
    }

    pub fn distance(&self, other: &Point) -> f64 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        (dx * dx + dy * dy).sqrt()
    }
}

pub fn origin_distance(p: &Point) -> f64 {
    let o = Point::new(0.0, 0.0);
    p.distance(&o)
}
