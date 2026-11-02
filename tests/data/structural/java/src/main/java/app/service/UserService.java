package app.service;

import app.model.User;
import java.util.Objects;

public class UserService {
    public void save(String name) {
        validate(name);
        User user = new User(name);
        log(name);
        Objects.requireNonNull(user);
    }

    private void validate(String name) {
    }

    void log(String message) {
    }

    void log(String message, int level) {
    }
}
