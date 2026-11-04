export class BaseRepo {
  find(id: string) { return id; }
}

export class UserRepo extends BaseRepo {
  save(user: string) { return user; }
  get(id: string) { return id; }
}

export interface Store {
  save(x: string): void;
}

export class Other {
  save() { return 1; }
}

export class Wrapper {
  inner: UserRepo;
}
