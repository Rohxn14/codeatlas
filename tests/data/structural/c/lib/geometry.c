#include "geometry.h"

static double square(double x);

double area(double width, double height) {
    if (width == height) {
        return square(width);
    }
    return width * height;
}

int clamp(int value) {
    return value < 0 ? 0 : value;
}

static double square(double x) {
    return x * x;
}
