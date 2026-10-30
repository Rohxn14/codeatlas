import { http } from "./http";
import type { User, UserSource } from "./types";

export async function fetchUsers(): Promise<User[]> {
  const response = await fetch("/api/users");
  return response.json();
}

export async function fetchUser(id: number): Promise<User> {
  const response = await fetch(`/api/users/${id}`);
  return response.json();
}

export async function createUser(name: string): Promise<User> {
  const response = await http.post("/users", { name });
  return response.data;
}

export class UserApi implements UserSource {
  private readonly cache = new Map<number, User>();

  async listUsers(): Promise<User[]> {
    return fetchUsers();
  }

  async getUser(id: number): Promise<User> {
    const cached = this.cache.get(id);
    if (cached) {
      return cached;
    }
    const user = await fetchUser(id);
    this.remember(user);
    return user;
  }

  private remember(user: User): void {
    this.cache.set(user.id, user);
  }
}
