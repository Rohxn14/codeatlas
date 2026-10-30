import React from "react";
import { useState as useLocalState, useEffect } from "react";
import * as api from "./api";
import "./styles.css";
import Default, { named } from "./mixed";
import type { User } from "./types";
import legacy = require("./legacy");
export { save, load as fetchOne } from "./store";
export * from "./models";
export * as helpers from "./helpers";

export async function lazy() {
  const mod = await import("./heavy");
  return mod;
}
