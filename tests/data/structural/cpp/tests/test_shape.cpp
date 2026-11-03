#include <cassert>
#include "../include/shapes/shape.hpp"

int main() {
    shapes::Circle c(2.0);
    assert(c.scaled(2.0) > c.area());
    return 0;
}
