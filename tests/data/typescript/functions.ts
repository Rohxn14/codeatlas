export const add = (a: number, b: number): number => a + b;

export const fetchAll = async () => {
  const rows = await load();
  return rows.map((row) => format(row));
};

const local = function (x: string) {
  return x.trim();
};

export function outer() {
  function inner() {
    return helper();
  }
  return inner();
}

export const api = {
  getUser(id: string) {
    return request(id);
  },
  remove: async (id: string) => request(id),
  version: 2,
};

const internal = {
  hidden() {},
};

export default () => local("x");
