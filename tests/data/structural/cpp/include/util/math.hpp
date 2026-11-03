#pragma once

namespace util {
inline double half(double x) {
    return x / 2;
}
}  // namespace util

namespace legacy {
inline double half(double x) {
    return x * 0.5;
}
}  // namespace legacy
