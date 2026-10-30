import logging

log = logging.getLogger(__name__)


def make_default():
    return 1


def register(fn):
    return fn


class Handler:
    timeout = compute_timeout()

    def __init__(self, repo):
        self.repo = repo

    @register_method(name="handle")
    def handle(self, users, limit=make_default()):
        self.repo.save(users[0])
        build().run()
        names = [str(u) for u in users]
        key = lambda u: u.name.lower()
        sorted(names, key=key)
        self.repo \
            .flush()
        handlers[0]()
        return super().handle(users)


@register
def top():
    print(f"{make_default()} done")
