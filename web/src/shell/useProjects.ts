import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export type Project = { name: string; label: string; archived: boolean };
const DEFAULT = ["personal", "digisoft", "quokka", "rdim"];

// Personal and the owner's projects (projects can be added on the Connectors page).
export function useProjects(): string[] {
  const q = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<{ projects: Project[] }>("/api/projects"),
    staleTime: 60_000,
  });
  return q.data?.projects.map((p) => p.name) ?? DEFAULT;
}
