import React from "react";
import { UserRepo as Repo, Other, Store, Wrapper } from "./repo";
import * as repos from "./repo";

class Comp extends React.Component {}

export class Service<M> {
  extra: Repo;
  built = new Other();
  maybe?: Repo | null;
  model: M;
  wrap: Wrapper;
  constructor(private repo: Repo, public ns: repos.UserRepo) {}

  viaProperty() { this.repo.save("a"); }
  viaBase() { this.extra.find("b"); }
  viaNew() { this.built.save(); }
  viaOptional() { this.maybe.get("c"); }
  viaNamespace() { this.ns.save("d"); }
  viaChain() { this.wrap.inner.save("e"); }
  viaParam(r: Repo, n: number = 3) { r.save("f"); }
  viaArrow = 1;

  onArray(list: Repo[]) { list.save("x"); }
  onAny(loose: any) { loose.save("x"); }
  onUnion(both: Repo | Other) { both.save("x"); }
  onInterface(s: Store) { s.save("x"); }
  onTypeParam<T>(t: T) { t.save("x"); }
  onClassTypeParam() { this.model.save("x"); }
  onShadow(r: Repo) {
    function inner(r) { r.save("x"); }
    inner(r);
  }
  onOutsideBase(c: Comp) { c.save("x"); }
}

export const typedArrow = async (r: Repo): Promise<void> => { r.get("g"); };
