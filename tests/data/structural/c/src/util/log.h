#ifndef LOG_H
#define LOG_H

void log_line(const char *message);

static inline int log_level(void) {
    return 1;
}

#endif
