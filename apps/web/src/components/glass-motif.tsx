import { cn } from "@/lib/cn";

export function GlassMotif({
  className,
  tone = "light",
}: {
  className?: string;
  tone?: "light" | "dark";
}) {
  const stroke = tone === "dark" ? "rgba(191, 219, 254, 0.45)" : "rgba(37, 99, 235, 0.28)";
  const fill = tone === "dark" ? "rgba(191, 219, 254, 0.2)" : "rgba(37, 99, 235, 0.12)";
  const accent = tone === "dark" ? "#5eead4" : "#0f766e";

  return (
    <svg
      viewBox="0 0 480 280"
      aria-hidden="true"
      className={cn("pointer-events-none select-none", className)}
    >
      <ellipse cx="240" cy="140" rx="168" ry="78" fill="none" stroke={stroke} strokeWidth="1.2" />
      <ellipse cx="240" cy="140" rx="112" ry="48" fill="none" stroke={stroke} strokeWidth="1" />
      <path d="M72 168 C 150 40, 330 40, 408 168" fill="none" stroke={stroke} strokeWidth="1.4" />
      <path d="M88 188 C 170 248, 310 248, 392 188" fill="none" stroke={stroke} strokeWidth="1" />
      {(
        [
          [96, 156],
          [168, 92],
          [240, 74],
          [318, 98],
          [384, 158],
          [240, 196],
        ] as const
      ).map(([cx, cy], index) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={index === 2 ? 7 : 5} fill={index === 2 ? accent : fill} stroke={stroke} />
      ))}
    </svg>
  );
}

export function StageChips() {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {["Acquire", "Close", "Expand"].map((label) => (
        <span
          key={label}
          className="rounded-full border border-white/70 bg-white/50 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-azure-700 backdrop-blur-md"
        >
          {label}
        </span>
      ))}
    </div>
  );
}
