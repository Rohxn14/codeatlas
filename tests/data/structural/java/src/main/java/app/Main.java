package app;

import app.service.UserService;
import app.util.*;
import static app.util.Strings.slug;

public class Main {
    void run() {
        UserService service = new UserService();
        service.save("ada");
        String tag = slug("Ada L");
        Format.pad(tag);
        helper();
    }

    void helper() {
    }
}
