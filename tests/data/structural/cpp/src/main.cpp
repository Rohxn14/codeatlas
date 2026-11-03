#include <algorithm>
#include <vector>
#include "shapes/shape.hpp"
#include "util/math.hpp"

int main() {
    shapes::Circle c = shapes::Circle::unit();
    std::vector<double> values{c.area(), legacy::half(4.0)};
    std::sort(values.begin(), values.end());
    return shapes::total(c, c) > 0 ? 0 : 1;
}
