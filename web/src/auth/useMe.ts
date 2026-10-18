import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export type Me = { signed_in: boolean; has_passkeys: boolean; needs_passkey: boolean };

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/api/auth/me") });
}
