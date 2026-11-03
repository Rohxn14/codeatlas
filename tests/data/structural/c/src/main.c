#include <stdio.h>
#include "geometry.h"
#include "util/log.h"

int main(void) {
    double a = area(2.0, 3.0);
    log_line("computed");
    printf("%f %d\n", a, clamp(-1));
    return 0;
}
