export interface Shape {
  area(): number;
}

interface Named extends Shape {
  name: string;
}

type Point = { x: number; y: number };

/**
 * A square that knows its own area.
 */
@Serializable()
export class Square extends Base<Shape> implements Shape, Named {
  name = "square";

  constructor(private side: number) {
    super();
  }

  /** The area, in square units. */
  @Memo()
  area(): number {
    return this.side * this.side;
  }

  async save(store: Store): Promise<void> {
    await store.put(this.name, this);
  }

  get label() {
    return this.name;
  }

  set label(value: string) {
    this.name = value;
  }
}

class Hidden {}
