import { describe, expect, it } from "vitest";
import { UserCard } from "../src/components/UserCard";
import { UserList } from "../src/components/UserList";

describe("UserList", () => {
  it("renders one UserCard per user", () => {
    const users = [
      { id: 1, name: "ada" },
      { id: 2, name: "grace" },
    ];
    const element = UserList({ users });
    const cards = element.props.children;
    expect(cards).toHaveLength(2);
    expect(cards[0].type).toBe(UserCard);
  });
});
