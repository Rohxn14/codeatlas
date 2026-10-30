import type { User } from "../api";
import { formatName } from "./format";

export function UserCard({ user }: { user: User }) {
  return <li className="user-card">{formatName(user)}</li>;
}
