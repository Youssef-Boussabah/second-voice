import { useEffect } from "react";
import { USE_MOCKS } from "./config";
import { useStore, type Screen } from "./store";
import TalkScreen from "./screens/TalkScreen";
import MemoryScreen from "./screens/MemoryScreen";
import ScoreboardScreen from "./screens/ScoreboardScreen";
import Toasts from "./components/Toasts";
import BoundaryModal from "./components/BoundaryModal";

const TABS: { id: Screen; label: string; icon: string }[] = [
  { id: "talk", label: "Talk", icon: "💬" },
  { id: "memory", label: "Memory & privacy", icon: "🔒" },
  { id: "scoreboard", label: "Scoreboard", icon: "📊" },
];

export default function App() {
  const screen = useStore((s) => s.screen);
  const setScreen = useStore((s) => s.setScreen);
  const init = useStore((s) => s.init);
  const wsStatus = useStore((s) => s.wsStatus);

  useEffect(() => {
    void init();
  }, [init]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b-2 border-line bg-white/70 px-4 py-2 backdrop-blur">
        <div className="mr-2 flex items-center gap-2">
          <span aria-hidden className="grid h-10 w-10 place-items-center rounded-full bg-clay text-xl text-white">◐</span>
          <span className="text-2xl font-bold tracking-tight">Second Voice</span>
        </div>
        <nav aria-label="Main" className="flex flex-1 flex-wrap gap-2">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setScreen(t.id)}
              aria-current={screen === t.id ? "page" : undefined}
              className={`min-h-16 rounded-2xl px-5 text-lg font-bold transition-colors ${
                screen === t.id ? "bg-ink text-paper" : "text-ink hover:bg-clay-soft"
              }`}
            >
              <span aria-hidden className="mr-2">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="flex items-center gap-2 text-base">
          {USE_MOCKS && (
            <span className="rounded-full bg-lock-soft px-3 py-1 font-bold text-lock" title="VITE_USE_MOCKS=true">Mock data</span>
          )}
          <span className="flex items-center gap-2 rounded-full bg-white px-3 py-1 text-muted" role="status" aria-live="polite">
            <span
              aria-hidden
              className={`h-3 w-3 rounded-full ${
                wsStatus === "open" ? "bg-sage" : wsStatus === "idle" ? "bg-line" : wsStatus === "connecting" ? "bg-amber-500" : "bg-red-600"
              }`}
            />
            {wsStatus === "open" ? "Live" : wsStatus === "idle" ? "Ready" : wsStatus === "connecting" ? "Connecting…" : "Reconnecting…"}
          </span>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">
        {screen === "talk" && <TalkScreen />}
        {screen === "memory" && <MemoryScreen />}
        {screen === "scoreboard" && <ScoreboardScreen />}
      </main>

      <Toasts />
      <BoundaryModal />
    </div>
  );
}
