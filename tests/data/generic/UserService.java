package app;

interface Repository {
    void save(String name);
}

public class UserService {
    private final Repository repo;

    public UserService(Repository repo) {
        this.repo = repo;
    }

    public void register(String name) {
        validate(name);
        this.repo.save(name);
    }

    private void validate(String name) {
        System.out.println(name.trim());
    }
}
