import type { User } from "../api";
import { UserCard } from "./UserCard";

export function UserList({ users }: { users: User[] }) {
  return (
    <ul>
      {users.map((user) => (
        <UserCard key={user.id} user={user} />
      ))}
    </ul>
  );
}
