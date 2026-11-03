#include <stdio.h>
#include "log.h"

void log_line(const char *message) {
    if (log_level() > 0) {
        puts(message);
    }
}
