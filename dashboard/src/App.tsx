import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type ClaimSummary,
  type Handler,
  type UiAction,
  type VoiceConfig,
} from "./api";
import { Board } from "./components/Board";
import { CommandBar } from "./components/CommandBar";
import { Drawer } from "./components/Drawer";
import { MetricStrip } from "./components/MetricStrip";
import { Rail, type View } from "./components/Rail";
import { matches } from "./format";
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
    api.listClaims().then(
      (next) => {
        setClaims(next);
        setNow(new Date());
        setError("");
      },
      () => {
        setError("The backend is not responding. Start it with npm run dev.");
      },
    );
  }, []);

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

  return (
    <div className="app">
      <Rail view={view} />
      <main className="main">
        <CommandBar
          search={search}
          onSearch={setSearch}
          theme={theme}
          onToggleTheme={toggleTheme}
          onRunAll={() => {
            void api.startQueueRun().then(refresh);
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
          <Board claims={shown} now={now} onOpen={setOpenId} />
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
