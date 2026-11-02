import React from "react";
import { Child as C } from "./classes";

export class Grand extends C {
  more() {
    this.run();
    this.go();
    this.missing();
  }
}

export class View extends React.Component {}
