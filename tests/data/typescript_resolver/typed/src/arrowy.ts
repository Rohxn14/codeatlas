import { Repo } from "./m";

interface IRepo { save(): number; }

export class Arrowy implements IRepo {
  save = () => 3;
}

export function useArrowy(x: Arrowy, r: Repo) { x.save(); }
