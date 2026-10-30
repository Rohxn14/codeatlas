import { afterEach, describe, expect, it, vi } from "vitest";
import { UserApi, fetchUsers } from "../src/api";
import { formatName } from "../src/components/format";

function stubFetch(body: unknown) {
  const fake = vi.fn(async () => ({ json: async () => body }));
  vi.stubGlobal("fetch", fake);
  return fake;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UserApi", () => {
  describe("getUser", () => {
    it("fetches a user once and caches it", async () => {
      const fake = stubFetch({ id: 7, name: "ada" });
      const api = new UserApi();
      await api.getUser(7);
      const user = await api.getUser(7);
      expect(user.name).toBe("ada");
      expect(fake).toHaveBeenCalledTimes(1);
      expect(fake).toHaveBeenCalledWith("/api/users/7");
    });
  });

  it("lists users", async () => {
    stubFetch([{ id: 1, name: "grace" }]);
    const users = await new UserApi().listUsers();
    expect(users).toHaveLength(1);
  });
});

describe("fetchUsers", () => {
  it("calls the list endpoint", async () => {
    const fake = stubFetch([]);
    await fetchUsers();
    expect(fake).toHaveBeenCalledWith("/api/users");
  });
});

describe("formatName", () => {
  it("shows the name and id", () => {
    expect(formatName({ id: 3, name: "linus" })).toBe("linus (#3)");
  });
});
