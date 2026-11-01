import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type ClaimSummary,
  type Handler,
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
  return view === "signoff" || view === "instructions" ? view : "queue";
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

export function App() {
  const [view, setView] = useState<View>(viewFromHash);
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState("");
  const [now, setNow] = useState(() => new Date());
  const [theme, toggleTheme] = useTheme();
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [handlers, setHandlers] = useState<Handler[]>([]);
  const [voiceHandler, setVoiceHandler] = useState("HND-01");
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

  useEffect(() => {
    if (provider) void api.listHandlers().then(setHandlers);
  }, [provider]);

  const onAction = useCallback(
    (action: UiAction) => {
      if (action.type === "open_claim") setOpenId(action.claim_id);
      if (action.type === "focus_signoff") {
        setHighlight({ claimId: action.claim_id, handlerId: voiceHandler });
        window.location.hash = "#/signoff";
      }
    },
    [voiceHandler],
  );

  const voice = useVoice({ provider, handlerId: voiceHandler, onAction });

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
      <Rail view={view} />
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
          {provider?.available && (
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
            version={signoffVersion}
            now={now}
            highlight={highlight}
            onOpen={setOpenId}
            onChanged={refresh}
          />
        )}
        {view === "instructions" && <Instructions />}
      </main>
      {provider && (
        <CaptionsPanel
          captions={voice.captions}
          handlers={handlers}
          handlerId={voiceHandler}
          onHandler={setVoiceHandler}
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
