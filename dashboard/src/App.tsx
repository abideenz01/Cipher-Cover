import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type ClaimSummary,
  type Me,
  type QueueRun,
  type UiAction,
  type VoiceConfig,
} from "./api";
import { Board } from "./components/Board";
import { CommandBar } from "./components/CommandBar";
import { Drawer } from "./components/Drawer";
import { MetricStrip } from "./components/MetricStrip";
import { Rail, type View } from "./components/Rail";
import { RunPanel } from "./components/RunPanel";
import { isLive, matches } from "./format";
import { Admin } from "./views/Admin";
import { Instructions } from "./views/Instructions";
import { SignOff, type Highlight } from "./views/SignOff";
import { CaptionsPanel, ConsentNotice } from "./voice/CaptionsPanel";
import { MicButton } from "./voice/MicButton";
import { browserProvider } from "./voice/providers/browser";
import { stubProvider } from "./voice/providers/stub";
import { useVoice } from "./voice/useVoice";

type Theme = "dark" | "light";

function viewFromHash(): View {
  const view = window.location.hash.replace("#/", "");
  return ["signoff", "instructions", "admin"].includes(view)
    ? (view as View)
    : "queue";
}

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() =>
    localStorage.getItem("theme") === "light" ? "light" : "dark",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);
  return [
    theme,
    () => {
      setTheme((current) => (current === "dark" ? "light" : "dark"));
    },
  ];
}

export function App({
  me,
  onSignOut,
}: Readonly<{ me: Me; onSignOut: () => void }>) {
  const [view, setView] = useState<View>(viewFromHash);
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState("");
  const [now, setNow] = useState(() => new Date());
  const [theme, toggleTheme] = useTheme();
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const [queueRuns, setQueueRuns] = useState<QueueRun[]>([]);
  const [shownRun, setShownRun] = useState("");

  useEffect(() => {
    api.getVoiceConfig().then(setVoiceConfig, () => {
      setVoiceConfig(null);
    });
  }, []);

  const provider = useMemo(() => {
    if (!voiceConfig?.enabled) return null;
    return voiceConfig.provider === "stub" ? stubProvider : browserProvider();
  }, [voiceConfig]);

  const onAction = useCallback(
    (action: UiAction) => {
      if (action.type === "open_claim") setOpenId(action.claim_id);
      if (action.type === "focus_signoff") {
        setHighlight({ claimId: action.claim_id, handlerId: me.handler_id });
        window.location.hash = "#/signoff";
      }
    },
    [me.handler_id],
  );

  const isAdmin = me.roles.includes("tenant_admin");
  // Only a claims handler talks to the voice assistant.
  const speaking = me.handler_id ? provider : null;
  const voice = useVoice({ provider: speaking, onAction });

  const refresh = useCallback(() => {
    Promise.all([api.listClaims(), api.listQueueRuns()]).then(
      ([next, nextRuns]) => {
        setClaims(next);
        setQueueRuns(nextRuns);
        setNow(new Date());
        setError("");
      },
      () => {
        setError("The backend is not responding. Start it with npm run dev.");
      },
    );
  }, []);

  function failed(e: unknown) {
    setError(e instanceof Error ? e.message : "The run did not start.");
  }

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => {
      clearInterval(timer);
    };
  }, [refresh]);

  useEffect(() => {
    function onHash() {
      setView(viewFromHash());
    }
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  const close = useCallback(() => {
    setOpenId("");
  }, []);

  const open = claims.find((c) => c.claim_id === openId);
  const signoffVersion = claims
    .filter((c) => c.state === "waiting_for_signoff")
    .map((c) => c.claim_id + c.state_since)
    .join();
  const shown = search ? claims.filter((c) => matches(c, search)) : claims;
  const live = queueRuns.find((r) => isLive(r.status));
  const panelRun =
    queueRuns.find((r) => r.run_id === shownRun) ?? live ?? queueRuns[0];

  return (
    <div className="app">
      <Rail view={view} who={me.name} admin={isAdmin} onSignOut={onSignOut} />
      <main className="main">
        <CommandBar
          search={search}
          onSearch={setSearch}
          theme={theme}
          onToggleTheme={toggleTheme}
          live={live}
          onStart={(cap) => {
            setShownRun("");
            api.startQueueRun(cap).then(refresh, failed);
          }}
          onStop={(runId) => {
            api.stopQueueRun(runId).then(refresh, failed);
          }}
        >
          {speaking?.available && (
            <MicButton
              status={voice.status}
              onPress={voice.start}
              onRelease={voice.stop}
            />
          )}
        </CommandBar>
        {error && <p className="error">{error}</p>}
        <MetricStrip claims={claims} now={now} />
        {view === "queue" && (
          <>
            <RunPanel
              run={panelRun}
              history={queueRuns}
              onSelect={setShownRun}
            />
            <Board claims={shown} now={now} onOpen={setOpenId} />
          </>
        )}
        {view === "signoff" && (
          <SignOff
            me={me}
            version={signoffVersion}
            now={now}
            highlight={highlight}
            onOpen={setOpenId}
            onChanged={refresh}
          />
        )}
        {view === "instructions" && <Instructions />}
        {view === "admin" && <Admin me={me} />}
      </main>
      {speaking && (
        <CaptionsPanel
          captions={voice.captions}
          speaker={`${me.handler_id} ${me.name}`}
          onSend={(text) => void voice.send(text)}
          onOpen={setOpenId}
        />
      )}
      {voice.asking && <ConsentNotice onContinue={voice.consent} />}
      {open && (
        <Drawer
          claimId={open.claim_id}
          version={open.state + open.state_since}
          onClose={close}
          onChanged={refresh}
        />
      )}
    </div>
  );
}
