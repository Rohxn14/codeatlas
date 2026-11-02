import * as helpers from "./helpers";

export function useThem(x: any) {
  x.target();
  x.pair();
  return helpers;
}
