// API shapes (hand-written until the OpenAPI → TypeScript generation lands with more routes).
export type BriefItem = {
  ref: string;
  reason?: string;
  overdue?: boolean;
  id: number;
  kind: string;
  title: string;
  summary: string;
  outcome: string | null;
  link: string | null;
  last_activity_at: string;
  scopes: string[];
  participants: string[];
};

export type BriefSection = {
  title: string;
  text: string;
  refs: string[];
  items: BriefItem[];
  kind?: "ai" | "focus" | "data" | "note" | "group";
};

export type Brief = {
  id: number;
  routine: string;
  title: string;
  headline: string;
  window_start: string;
  window_end: string;
  mode: "ai" | "data";
  sections: BriefSection[];
  cost_usd?: number;
  created_at: string;
};
