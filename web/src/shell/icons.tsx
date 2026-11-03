// Line icons for the navigation (24 px grid, stroke follows the text colour).
import type { ReactNode } from "react";

function Svg({ children }: { children: ReactNode }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

export const ICONS: Record<string, ReactNode> = {
  assistant: (
    <Svg>
      <path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" />
      <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" />
    </Svg>
  ),
  mic: (
    <Svg>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </Svg>
  ),
  send: (
    <Svg>
      <path d="M5 12h13M13 6l6 6-6 6" />
    </Svg>
  ),
  menu: (
    <Svg>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Svg>
  ),
  inbox: (
    <Svg>
      <path d="M3 13l3-8h12l3 8v6H3z" />
      <path d="M3 13h5l1 2h6l1-2h5" />
    </Svg>
  ),
  loops: (
    <Svg>
      <path d="M17 2l3 3-3 3" />
      <path d="M4 11V9a4 4 0 0 1 4-4h12M7 22l-3-3 3-3" />
      <path d="M20 13v2a4 4 0 0 1-4 4H4" />
    </Svg>
  ),
  library: (
    <Svg>
      <path d="M5 4h4v16H5zM10 4h4v16h-4z" />
      <path d="M15.5 5.2l3.8-1 3 15.5-3.8 1z" />
    </Svg>
  ),
  people: (
    <Svg>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6" />
    </Svg>
  ),
  briefs: (
    <Svg>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </Svg>
  ),
  week: (
    <Svg>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M3 10h18M8 3v4M16 3v4M7 14h2M11 14h2M15 14h2M7 17h2" />
    </Svg>
  ),
  clickup: (
    <Svg>
      <rect x="3" y="3" width="18" height="18" rx="4" />
      <path d="M8 12l3 3 5-6" />
    </Svg>
  ),
  connectors: (
    <Svg>
      <path d="M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5" />
    </Svg>
  ),
  status: (
    <Svg>
      <path d="M3 12h4l2-5 4 10 2-5h6" />
    </Svg>
  ),
  bell: (
    <Svg>
      <path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8" />
      <path d="M10.3 20a2 2 0 0 0 3.4 0" />
    </Svg>
  ),
  today: (
    <Svg>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Svg>
  ),
  moderate: (
    <Svg>
      <rect x="4" y="3" width="16" height="18" rx="3" />
      <path d="M8 9l2 2 4-4M8 16h8" />
    </Svg>
  ),
  meetings: (
    <Svg>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M3 10h18M8 3v4M16 3v4" />
    </Svg>
  ),
  search: (
    <Svg>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </Svg>
  ),
  settings: (
    <Svg>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </Svg>
  ),
};
