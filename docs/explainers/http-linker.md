# HTTP linker

## What

The HTTP linker connects client requests to the server routes they hit, across languages.
`fetch("/api/users/" + id)` in TypeScript becomes an edge to the Python handler declared with
`@router.get("/users/{id}")` under `APIRouter(prefix="/api")`. It creates one ROUTE node per
distinct (method, path), a HANDLES edge from each route to its handler, and a CALLS_HTTP edge
from each calling function to each route it hits. A change to a handler then reaches its callers.

## Why

- **A separate linker, not a resolver.** A resolver works on one language family; this join
  needs the output of two. The contract has a `Linker` for exactly this.
- **Join on method and normalised path.** It is the only information both sides share.
- **Two confidence levels, from the contract.** `ROUTE_EXACT` (0.9) when a literal URL equals a
  route; `ROUTE_PATTERN` (0.7) when a parameter is involved. Rejected: one level, because a
  template matching `/users/{id}` is weaker evidence than two identical strings.
- **Ties: keep the most specific route, split confidence among equals.** `/users/me` beats
  `/users/{id}`; `/users/{id}` and `/users/{name}` each get 0.7 / 2. Rejected: picking one at random.
- **Full-host URLs stay unmatched** (reason `external_host`): CALLS_HTTP is Function → Route in
  the contract, so an EXTERNAL target would break the edge's shape. `localhost`, `127.0.0.1`,
  `0.0.0.0`, `testserver` and `::1` count as local (compared with `urlsplit(...).hostname`, so
  `HTTP://LOCALHOST` and `[::1]:8000` work). A placeholder host (`` http://${API_HOST}:8000 ``,
  `f"http://{host}"`) also counts as local: it is configuration, which in development points at
  this repository's own server. Rejected: calling it external, which lost real matches.
- **Axios instances across files: adapter records, linker joins.** An adapter sees one file, so
  `export const http = axios.create({ baseURL: "/api" })` in `http.ts` and `http.post("/users")`
  in `client.ts` cannot be joined there. The TypeScript adapter writes the exported instances on
  the module node (`attrs["axios_instances"] = {"http": {"base_url": "/api", "url_kind":
  "literal"}}`) and emits the call with client `axios:http`; the linker follows the file's own
  import of `http` to that module and prefixes the base URL. Rejected: a new `RawHttpCall`
  field (a contract change for what an attribute and a client name can carry), and a shared
  cache between adapter runs (it would depend on parse order).
- **Test clients are clients.** `client = TestClient(app)` in Python makes `client.post(...)`
  a request; tests are often the only callers of a route.
- **Unmatched calls are reported.** After linking, one line per reason
  (`unmatched http calls: no_route=3`) goes to `problems`, which the pipeline copies into the
  build report as `linker http: ...`.
- **Trailing slashes and query strings are ignored**; paths are compared case-sensitively.

## How

Normalising a client URL, with the fixture's `` `/api/users/${id}` `` (`urls.py`):

1. A `dynamic` URL is an expression like `BASE + "/users/" + id`: split on `+`, quoted pieces keep
   their text, a bare name becomes a parameter, except a first bare name (a host prefix), dropped.
   A bare name may have attribute and subscript parts: `ids[0]`, `row["id"]`, `user.id`.
2. Turn each `${...}` or `{name}` into the parameter segment `{}`. Doing this first means a
   `?` inside `` ${q ? 'a' : 'b'} `` cannot cut the path, and a placeholder host is visible.
3. Strip `scheme://host:port` (or a protocol-relative `//host`); a non-local host ends the match
   (`external_host`).
4. Strip a leading `{}` that was a base placeholder (`${API}/users`).
5. Cut at `?` or `#`.
6. Split on `/`, dropping empty pieces (this removes repeated and trailing slashes).

Result: `("api", "users", "{}")`. The route `/api/users/{id}` becomes the same shape.

Matching (`http.py`): the segment lists must have equal length; a route `{}` matches any client
segment, a route literal needs an equal literal, and a client parameter never matches a route
literal. A route segment mixing a parameter and text (`{name}.json`) is compiled to a regular
expression (`[^/]+\.json`) that a literal client segment must match. The method must be equal,
the route's `ANY` matches all, and an unknown client method (`None`) matches any method; when
some hit has the call's exact method, `ANY` hits are dropped, so `GET /x` against routes
`GET /x` and `ANY /x` is one exact edge, not two split ones. The match is exact only when the call has no parameter and the path is
identical with a known, equal method; everything else is a pattern match. Of the matching routes,
only those with the most literal segments are kept.

Worked example: the fixture's `fetchUser` sends `GET /api/users/${id}`. Segments
`api, users, {}` match route `GET /api/users/{id}` only (`GET /api/users` has two segments). A
parameter is involved, so the edge is `ROUTE_PATTERN`, 0.7. `fetchUsers` sends the literal
`/api/users` and gets `ROUTE_EXACT`, 0.9. Routes are keyed `{handler file}::route:{METHOD} {path}`;
two handlers of one (method, path) share one node with two HANDLES edges.

Worked example, imported instance: `client.ts` has `import { http } from "./http"` and, in
`createUser`, `http.post("/users", { name })`. The adapter emits `RawHttpCall(client="axios:http",
url_text="/users", method="POST")`. The linker finds the import binding `http`, resolves `./http`
from `frontend/src/api/` to `frontend/src/api/http.ts` (trying `.ts`, `.tsx`, `.js`, ... and
`index` files), reads `{"http": {"base_url": "/api"}}` from that module node, and matches
`/api/users` exactly. A bare or aliased import (`@/api/http`) cannot be resolved without the
build config, so it is accepted only when exactly one module exports an instance with that
name. An imported name that is not an instance (`cache.get("/k")`) is counted as
`unknown_client`. A verb call on a line where the route extractor found an Express route
(`router.get("/x", handler)`) is never a candidate.

## Where

- Reads `ParseResult.routes` and `ParseResult.http_calls` from the Python and TypeScript adapters.
- Registered in `LINKERS` (`pipeline/plugins.py`); `build_graph` writes the ROUTE nodes and edges.
- Contract types: `RawRoute`, `RawHttpCall`, `Node` (ROUTE), `Edge` (HANDLES, CALLS_HTTP),
  `Resolution.ROUTE_EXACT`, `ROUTE_PATTERN`, `STRUCTURAL`.
- After `link`, `unmatched` (reason to count), `matched_calls` and `problems` describe what the
  linker could not do; `_run_linkers` in `pipeline/build.py` copies `problems` into
  `BuildResult.problems` with a `linker http:` prefix.
- The TypeScript adapter calls `linker/urls.py`'s `join_client_url` for local instances, so
  base URLs are joined the same way in both places; it writes `axios_instances` on module nodes
  (a new `attrs` key, not yet listed in the contract's common keys).

## What static linking cannot see

- **Cross-file Express mounts.** `app.use("/api/products", productRoutes)` is a raw call without
  arguments, so the prefix never reaches routes defined in `productRoutes.js`: they stay `/` and
  `/{id}`. A v1 limitation.
- **Imported handlers.** An Express route with an imported controller has a module-key handler,
  so it gets a ROUTE node and no HANDLES edge; each is counted in `problems`.
- **Clients the adapters do not record**: Flask's `app.test_client()`, hand-written wrappers
  around `fetch` (`api.get(path)` that builds the URL inside), and instances re-exported through
  a barrel file (`export { http } from "./http"`) or imported as a namespace (`api.http.post`).
- URLs built at run time, gateways and proxies that rewrite paths, and clients in other repositories.
