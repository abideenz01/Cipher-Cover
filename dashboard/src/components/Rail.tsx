export type View = "queue" | "signoff" | "instructions";

const ITEMS: { view: View; label: string; path: string }[] = [
  { view: "queue", label: "Queue", path: "M4 5h16M4 12h16M4 19h10" },
  { view: "signoff", label: "Sign-off", path: "M5 13l4 4L19 7" },
  {
    view: "instructions",
    label: "Instructions",
    path: "M7 4h10v16H7zM10 8h4M10 12h4M10 16h2",
  },
];

export function Rail({ view }: Readonly<{ view: View }>) {
  return (
    <nav className="rail" aria-label="Main">
      {ITEMS.map((item) => (
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
    </nav>
  );
}
