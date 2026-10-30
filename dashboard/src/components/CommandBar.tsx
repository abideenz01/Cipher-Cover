import { useEffect, useRef } from "react";

interface Props {
  search: string;
  onSearch: (text: string) => void;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onRunAll: () => void;
  children?: React.ReactNode;
}

export function CommandBar(props: Readonly<Props>) {
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (event.key === "/" && !typing) {
        event.preventDefault();
        input.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <div className="command-bar">
      <input
        ref={input}
        className="search"
        type="search"
        aria-label="Find claims by id, customer or policy"
        placeholder="Find claims by id, customer or policy  /"
        value={props.search}
        onChange={(event) => {
          props.onSearch(event.target.value);
        }}
      />
      <button type="button" className="button" onClick={props.onToggleTheme}>
        {props.theme === "dark" ? "Light mode" : "Dark mode"}
      </button>
      <button type="button" className="button primary" onClick={props.onRunAll}>
        Run all waiting
      </button>
      {props.children}
    </div>
  );
}
