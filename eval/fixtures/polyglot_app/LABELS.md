# Labels for the polyglot fixture

`expected_graph.json` lists what a perfect indexer would produce for this app. These labels
count as ground truth only after the owner has reviewed this page. Each line below explains
one label, or one group of labels, that is not obvious.

## Running the app's own tests

```
pip install -r requirements.txt && pytest backend      # from this folder
cd frontend && npm ci && npx vitest run
```

## Scope

- Only source files are nodes. Config and text files (`package.json`, `tsconfig.json`,
  `requirements.txt`, this page) and package nodes are left out, so the scorer ignores
  predicted package CONTAINS, DEPENDS_ON and CO_CHANGES edges.
- Edges into third-party code (`fastapi`, `axios`, `react`, `vitest`, builtins) are left
  out, so the scorer ignores predicted edges to EXTERNAL nodes instead of counting them as
  false positives.
- Every edge has `"resolution": "label"` and confidence 1.0, because it was written by hand.

## Nodes and keys

- Python spans include decorators: `UserService.create_user` starts at the `@logged` line (16).
  SCIP's enclosing ranges do the same.
- `logged.wrapper` is a nested function. It is a FUNCTION node contained by `logged`.
- `TestUserService.test_*` methods have kind TEST and are contained by the class
  `TestUserService`. `make_service` has no `test_` prefix, so it is an ordinary helper FUNCTION.
- A TypeScript test's key is its `describe` titles and `it` title joined with ` > `:
  `UserApi > getUser > fetches a user once and caches it`. `describe` blocks and the
  `afterEach` hook are not nodes.
- Interface method signatures (`UserSource.listUsers`) are not nodes. Only the interfaces are.
- Route keys are `backend/routes.py::route:<METHOD> <full path>`, where the full path
  includes the router's `/api` prefix. The contract does not define route keys, so this
  format is a proposal.
- `http.ts` is a module node with no symbols: `http` is a variable, not a function.

## CONTAINS

- One edge for each symbol, from its module, its class (methods, test methods) or its
  enclosing function (`logged.wrapper`). The line is the symbol's first line.

## IMPORTS

- `from X import Y` and `import { Y } from "X"` give one edge per name, from the module to
  the symbol `Y`. When `Y` is a variable (`CALL_LOG`, `router`, `http`), the edge goes to its
  module instead.
- `from .repo import Repo as BaseRepo`: the alias does not change the target, `repo.py::Repo`.
- `index.ts` re-exports: an edge from the barrel to each re-exported symbol.
- Importing through the barrel (`from "../api"` or `"../src/api"`) is labelled with the
  symbol's real definition (`client.ts::UserApi`, `types.ts::User`), not with `index.ts`.
  A perfect resolver follows re-exports.
- `import type` counts as an import.

## CALLS

- `UserRepo.save` calls `Repo.save` through `super().save(...)` (line 9).
- `self.all()` in `UserRepo.find_by_name` goes to the inherited `Repo.all`. `UserRepo` does
  not define `all`.
- `self.repo` in `UserService` is typed `UserRepo`, so `self.repo.save` is `UserRepo.save`,
  and `self.repo.all` and `self.repo.get` resolve to `Repo.all` and `Repo.get`.
- `@logged` above `create_user` is a CALLS edge from `create_user` to `logged` (line 16),
  because the decorator runs `logged(create_user)`. `@router.get` and `@dataclass` point at
  third-party code, so they are out of scope.
- A constructor call goes to the `__init__` that runs: `UserService(...)` goes to
  `UserService.__init__`, and `UserRepo()` goes to the inherited `Repo.__init__`. `User(...)`
  is a dataclass with no written `__init__`, and `new UserApi()` has no written constructor,
  so neither has an edge.
- `routes.py` line 10 and `app.py` line 12 are module-level calls. The contract has CALLS
  edges only from functions and tests, so they have no edges.
- `<UserCard ... />` in `UserList` is a CALLS edge to `UserCard` (line 8), because a rendered
  component is a function call.
- `UserList({ users })` in the component test is a plain call (line 11).
  `toBe(UserCard)` on line 14 only mentions `UserCard` as a value, so it has no edge.
- `return wrapper` in `logged` returns the function without calling it, so it has no edge.
- Two `api.getUser(7)` calls in one test make one edge, at the first line (20). The same
  holds for every repeated caller and callee pair.
- Same-named functions are deliberate traps for name guessing. `routes.list_users`,
  `routes.get_user` and `routes.create_user` share their names with `UserService` methods,
  and `fetchUser` is one letter away from `fetchUsers`.

## Unresolvable (not CALLS edges)

- `HANDLERS[name](service, payload)` in `dispatch`: the handler is looked up by a runtime
  string. The real targets are `handle_list` and `handle_create`, which are therefore never
  called statically.
- `getattr(service, method_name)()` in `call_service`: the method is chosen by a runtime string.
- `func(*args, **kwargs)` in `logged.wrapper`: it calls whatever function was decorated.

## TESTS

- From a test to each function it calls directly, when that function is outside the test
  files. A test that calls only helpers, like `make_service` or `stubFetch`, gets no TESTS
  edge to them.
- Module level, by naming convention (the repository layer's rule): `test_services.py` →
  `services.py`, `test_routes.py` → `routes.py`, `client.test.ts` → `client.ts`,
  `UserList.test.tsx` → `UserList.tsx`. These edges have no line.

## INHERITS

- `UserRepo` inherits `Repo`, reached through the alias `BaseRepo`.
- `UserApi implements UserSource` counts as INHERITS to the interface.
- `NewUser(BaseModel)` inherits from pydantic, which is third-party, so it is out of scope.

## HANDLES and CALLS_HTTP

- There are three routes. Each `@router.get`/`@router.post` path gets the
  `APIRouter(prefix="/api")` prefix.
- `fetch("/api/users")` (literal) goes to `GET /api/users`, and fetch's default method is GET.
- `` fetch(`/api/users/${id}`) `` (template) goes to `GET /api/users/{id}`.
- `http.post("/users")` goes to `POST /api/users` through `axios.create({baseURL: "/api"})`
  in another file.
- The backend test's `TestClient` is an httpx client. Its `post("/api/users")`,
  `` get(f"/api/users/{user_id}") `` and `get("/api/users")` calls are CALLS_HTTP edges.
  `get("/api/users/999")` is a second call to `GET /api/users/{id}`, so it adds no new edge.
