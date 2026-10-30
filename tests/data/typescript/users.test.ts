import { getUser } from "./users";

describe("UserApi", () => {
  beforeEach(() => reset());

  it("fetches a user", async () => {
    const user = await getUser(1);
    expect(user.id).toBe(1);
  });

  describe("errors", () => {
    test("rejects a missing user", async () => {
      await expect(getUser(0)).rejects.toThrow();
    });

    it.skip("retries", () => {
      retry();
    });
  });
});

test("top level", () => {});
