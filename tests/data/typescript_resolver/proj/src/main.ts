import axios from "axios";
import React, { useState } from "react";
import fs from "node:fs";
import norm, { slug } from "@lib/util";
import { thing } from "src/lib/thing";
import { thing as exact } from "@exact";
import * as ns from "./ns";
import "./side";
import { Button } from "@acme/ui";
import { deep } from "./chain";
import { sw } from "./swap.js";
import { inB } from "./cyc/a";
import { Child, NoCtor } from "./classes";
const cjs = require("./cjs");
const { fromCjs } = require("./cjs");

export function run() {
  slug();
  norm();
  thing();
  exact();
  ns.f();
  ns.Widget.make();
  Button();
  deep();
  sw();
  inB();
  axios.get("/x");
  React.useState(0);
  useState(1);
  fs.readFileSync("x");
  console.log("hi");
  setTimeout(() => {}, 1);
  const kid = new Child();
  kid.go();
  new NoCtor();
  cjs.fromCjs();
  fromCjs();
  inner();
  function inner() {}
}
