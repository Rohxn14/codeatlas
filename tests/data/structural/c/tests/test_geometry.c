#include <assert.h>
#include "../lib/api/geometry.h"

int main(void) {
    assert(area(2.0, 2.0) == 4.0);
    assert(clamp(-5) == 0);
    return 0;
}
