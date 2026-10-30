import { UserCard } from "./UserCard";
import { Avatar } from "./Avatar";

export function UserPage({ id }: { id: string }) {
  const user = useUser(id);
  return (
    <section>
      <UserCard user={user} />
      <Avatar.Small src={user.photo}>
        <span>{user.name}</span>
      </Avatar.Small>
    </section>
  );
}
