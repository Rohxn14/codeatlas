#include "shapes/shape.hpp"
#include "util/math.hpp"

namespace shapes {

Circle::Circle(double radius) : radius_(radius) {}

double Circle::area() const {
    return 3.14159 * radius_ * radius_;
}

double Circle::scaled(double factor) const {
    return area() * factor;
}

Circle Circle::unit() {
    return Circle(1.0);
}

double total(const Circle& a, const Circle& b) {
    return a.area() + util::half(b.area() * 2);
}

}  // namespace shapes
