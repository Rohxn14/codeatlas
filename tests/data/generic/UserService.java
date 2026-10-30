package app;

/** Saves users through a repository. */
public class UserService {
    private final UserRepository repo;

    public UserService(UserRepository repo) {
        this.repo = repo;
    }

    /** Validates and saves one user. */
    public void save(User user) {
        validate(user);
        this.repo.save(user);
    }

    private void validate(User user) {
        Objects.requireNonNull(user);
    }

    static class Audit {
        void record(String event) {
            System.out.println(event);
        }
    }
}

interface UserRepository {
    void save(User user);
}
