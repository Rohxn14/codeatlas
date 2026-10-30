import axios from "axios";

const api = axios.create({ baseURL: "/api" });

export async function loadUser(id: string) {
  const res = await fetch(`/api/users/${id}`);
  return res.json();
}

export function saveUser(user: User) {
  return fetch("/api/users", { method: "post", body: JSON.stringify(user) });
}

export function search(url: string) {
  return fetch(url, options);
}

export const listOrders = () => axios.get("/api/orders");

export function createOrder(order: Order) {
  return axios({ url: "/api/orders", method: "POST", data: order });
}

export function getProfile(id: string) {
  return api.get(`/profiles/${id}`);
}

export function deleteProfile(id: string) {
  return api.delete("/profiles/" + id);
}
