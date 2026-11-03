#pragma once

namespace shapes {

class Circle {
public:
    explicit Circle(double radius);
    double area() const;
    double scaled(double factor) const;
    static Circle unit();

private:
    double radius_;
};

double total(const Circle& a, const Circle& b);

}  // namespace shapes
