export interface User {
  id: number;
  name: string;
}

export interface UserSource {
  listUsers(): Promise<User[]>;
  getUser(id: number): Promise<User>;
}
