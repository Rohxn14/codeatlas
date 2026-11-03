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
  `0.0.0.0` and `testserver` count as local.
- **Trailing slashes and query strings are ignored**; paths are compared case-sensitively.

## How

Normalising a client URL, with the fixture's `` `/api/users/${id}` `` (`urls.py`):

1. A `dynamic` URL is an expression like `BASE + "/users/" + id`: split on `+`, quoted pieces keep
   their text, a bare name becomes a parameter, except a first bare name (a host prefix), dropped.
2. Strip `scheme://host:port`; a non-local host ends the match (`external_host`).
3. Strip a leading `${API}` or `{BASE}` placeholder.
4. Cut at `?` or `#`.
5. Turn each `${...}` or `{name}` into the parameter segment `{}`.
6. Split on `/`, dropping empty pieces (this removes repeated and trailing slashes).

Result: `("api", "users", "{}")`. The route `/api/users/{id}` becomes the same shape.

Matching (`http.py`): the segment lists must have equal length; a route `{}` matches any client
segment, a route literal needs an equal literal, and a client parameter never matches a route
literal. The method must be equal, the route's `ANY` matches all, and an unknown client method
(`None`) matches any method. The match is exact only when the call has no parameter and the path is
identical with a known, equal method; everything else is a pattern match. Of the matching routes,
only those with the most literal segments are kept.

Worked example: the fixture's `fetchUser` sends `GET /api/users/${id}`. Segments
`api, users, {}` match route `GET /api/users/{id}` only (`GET /api/users` has two segments). A
parameter is involved, so the edge is `ROUTE_PATTERN`, 0.7. `fetchUsers` sends the literal
`/api/users` and gets `ROUTE_EXACT`, 0.9. Routes are keyed `{handler file}::route:{METHOD} {path}`;
two handlers of one (method, path) share one node with two HANDLES edges.

## Where

- Reads `ParseResult.routes` and `ParseResult.http_calls` from the Python and TypeScript adapters.
- Registered in `LINKERS` (`pipeline/plugins.py`); `build_graph` writes the ROUTE nodes and edges.
- Contract types: `RawRoute`, `RawHttpCall`, `Node` (ROUTE), `Edge` (HANDLES, CALLS_HTTP),
  `Resolution.ROUTE_EXACT`, `ROUTE_PATTERN`, `STRUCTURAL`.
- After `link`, `unmatched` (reason to count), `matched_calls` and `problems` describe what the
  linker could not do.

## What static linking cannot see

- **Cross-file Express mounts.** `app.use("/api/products", productRoutes)` is a raw call without
  arguments, so the prefix never reaches routes defined in `productRoutes.js`: they stay `/` and
  `/{id}`. A v1 limitation.
- **Imported handlers.** An Express route with an imported controller has a module-key handler,
  so it gets a ROUTE node and no HANDLES edge; each is counted in `problems`.
- **Clients the adapters do not record**: the Python adapter does not treat `TestClient` as a
  client, and the TypeScript adapter does not follow an `axios.create` instance imported from
  another file. The linker cannot fix either: it sees only `RawHttpCall`.
- URLs built at run time, gateways and proxies that rewrite paths, and clients in other repositories.
