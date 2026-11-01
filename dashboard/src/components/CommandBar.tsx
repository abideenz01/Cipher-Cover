import { useEffect, useRef, useState } from "react";
import type { QueueRun } from "../api";
import { RunStatusChip } from "./RunPanel";

interface Props {
  search: string;
  onSearch: (text: string) => void;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  live: QueueRun | undefined;
  onStart: (cap: number) => void;
  onStop: (runId: string) => void;
  children?: React.ReactNode;
}

export function RunControl({
  live,
  onStart,
  onStop,
}: Readonly<Pick<Props, "live" | "onStart" | "onStop">>) {
  const [cap, setCap] = useState(5);
  const [all, setAll] = useState(false);
  if (live) {
    return (
      <span className="run-control">
        <RunStatusChip run={live} />
        <button
          type="button"
          className="button"
          disabled={live.status === "stopping"}
          onClick={() => {
            onStop(live.run_id);
          }}
        >
          Stop
        </button>
      </span>
    );
  }
  return (
    <span className="run-control">
      <label className="cap">
        <span>Claims</span>
        <input
          className="mono"
          type="number"
          min={1}
          value={cap}
          disabled={all}
          onChange={(event) => {
            setCap(Math.max(1, Number(event.target.value)));
          }}
        />
      </label>
      <label className="cap">
        <input
          type="checkbox"
          checked={all}
          onChange={(event) => {
            setAll(event.target.checked);
          }}
        />
        <span>All</span>
      </label>
      <button
        type="button"
        className="button primary"
        onClick={() => {
          onStart(all ? 0 : cap);
        }}
      >
        Run
      </button>
    </span>
  );
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
      <RunControl
        live={props.live}
        onStart={props.onStart}
        onStop={props.onStop}
      />
      {props.children}
    </div>
  );
}
