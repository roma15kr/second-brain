import { Link } from "react-router";

// A scope tag that opens the scope page (web-dashboard spec: scope pages open from any tag).
export function ScopeTag({ scope }: { scope: string }) {
  return (
    <Link to={`/scopes/${scope}`} className={`tag ${scope}`}>
      {scope}
    </Link>
  );
}
