export interface Iface {}

export class Base {
  run() {}
}

export class Child extends Base implements Iface {
  constructor() {
    super();
  }

  go() {
    this.run();
    super.run();
  }
}

export class NoCtor {}
