// Small inline icon set (no dependency). 24×24, stroke = currentColor. Always decorative:
// every control that uses one also carries a text label or aria-label.
const PATHS: Record<string, string[]> = {
  mic: ["M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z", "M5 11a7 7 0 0 0 14 0", "M12 18v3"],
  send: ["M5 12h14", "M13 6l6 6-6 6"],
  pencil: ["M4 20h4L19 9a2.83 2.83 0 0 0-4-4L4 16v4z", "M13.5 6.5l4 4"],
  more: ["M5 12h.01", "M12 12h.01", "M19 12h.01"],
  lock: ["M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z", "M8 11V7a4 4 0 0 1 8 0v4"],
  speaker: ["M4 9v6h4l5 4V5L8 9H4z", "M16.5 8.5a5 5 0 0 1 0 7", "M19 6a8.5 8.5 0 0 1 0 12"],
  stop: ["M8 7h8a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z"],
  keyboard: ["M4 6h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z", "M7 10h.01", "M11 10h.01", "M15 10h.01", "M7 14h10"],
  sparkle: ["M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z", "M19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z"],
  history: ["M3 12a9 9 0 1 0 3-6.7L3 8", "M3 3v5h5", "M12 7v5l3 2"],
  chat: ["M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"],
  chart: ["M4 20V11", "M10 20V5", "M16 20v-6", "M21 20H3"],
  x: ["M6 6l12 12", "M18 6L6 18"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  refresh: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 4v7h-7"],
  reply: ["M9 10l-5 5 5 5", "M20 4v7a4 4 0 0 1-4 4H4"],
  shield: ["M12 3l8 3v6c0 5-3.4 8.1-8 9-4.6-.9-8-4-8-9V6z", "M9 12l2 2 4-4"],
  power: ["M12 3v8", "M6.3 6.3a8 8 0 1 0 11.4 0"],
  info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5", "M12 8h.01"],
  alert: ["M12 4l9 16H3z", "M12 10v4", "M12 17h.01"],
  memory: ["M12 5a3 3 0 0 0-5.8 1A3 3 0 0 0 4 11a3 3 0 0 0 2 5 3 3 0 0 0 6 1V5z", "M12 5a3 3 0 0 1 5.8 1A3 3 0 0 1 20 11a3 3 0 0 1-2 5 3 3 0 0 1-6 1"],
  chevron: ["M9 6l6 6-6 6"],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M4 21a8 8 0 0 1 16 0"],
};

export type IconName = keyof typeof PATHS;

export default function Icon({ name, size = 24, className = "", strokeWidth = 2 }: { name: IconName; size?: number; className?: string; strokeWidth?: number }) {
  return (
    <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 ${className}`}>
      {PATHS[name].map((d) => <path key={d} d={d} />)}
    </svg>
  );
}

/** Brand mark: a speech bubble with a second "voice" wave. */
export function Logo({ size = 44 }: { size?: number }) {
  return (
    <span aria-hidden className="grid shrink-0 place-items-center rounded-2xl bg-ink text-white shadow-card" style={{ width: size, height: size }}>
      <svg width={size * 0.58} height={size * 0.58} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round">
        <path d="M4 12h.01" />
        <path d="M8 8.5v7" />
        <path d="M12 5v14" />
        <path d="M16 8.5v7" stroke="#F2A27E" />
        <path d="M20 11v2" stroke="#F2A27E" />
      </svg>
    </span>
  );
}
