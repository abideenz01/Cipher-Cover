export type View = "queue" | "signoff" | "instructions" | "admin";

const ITEMS: { view: View; label: string; path: string }[] = [
  { view: "queue", label: "Queue", path: "M4 5h16M4 12h16M4 19h10" },
  { view: "signoff", label: "Sign-off", path: "M5 13l4 4L19 7" },
  {
    view: "instructions",
    label: "Instructions",
    path: "M7 4h10v16H7zM10 8h4M10 12h4M10 16h2",
  },
];

const ADMIN = {
  view: "admin" as const,
  label: "Admin",
  path: "M12 4a4 4 0 110 8 4 4 0 010-8zM4 20c0-4 4-6 8-6s8 2 8 6",
};

export function Rail({
  view,
  who,
  admin = false,
  onSignOut,
}: Readonly<{
  view: View;
  who: string;
  admin?: boolean;
  onSignOut: () => void;
}>) {
  const items = admin ? [...ITEMS, ADMIN] : ITEMS;
  return (
    <nav className="rail" aria-label="Main">
      {items.map((item) => (
        <a
          key={item.view}
          className="rail-item"
          href={`#/${item.view}`}
          aria-current={item.view === view ? "page" : undefined}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path d={item.path} />
          </svg>
          {item.label}
        </a>
      ))}
      <div className="rail-who">
        <span className="muted">{who}</span>
        <button type="button" className="button" onClick={onSignOut}>
          Sign out
        </button>
      </div>
    </nav>
  );
}
