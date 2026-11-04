import { Repo } from "./m";

export function sync(repo: Repo, rows: any[]) { rows.forEach((repo) => repo.save()); }
export function loose(repo: Repo, rows: any[]) { rows.forEach((repo: any) => repo.load()); }
export function block(repo: Repo) { { const repo = make(); repo.save(); } }
export function kept(repo: Repo, rows: any[]) { rows.forEach((row) => repo.load()); }
