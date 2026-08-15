import { useEffect, useState, type ReactElement } from "react";
import { soundboard, type AmbienceType } from "../ui/soundboard";

const AMBIENCE_OPTIONS: Array<{ key: AmbienceType; label: string; icon: string }> = [
  { key: "none", label: "静音", icon: "🔇" },
  { key: "tavern", label: "酒馆喧闹", icon: "🍺" },
  { key: "dungeon", label: "幽暗地牢", icon: "🏰" },
  { key: "campfire", label: "荒野营火", icon: "🔥" },
  { key: "combat", label: "史诗战鼓", icon: "⚔️" },
];

export function SoundboardBar(): ReactElement {
  const [ambience, setAmbience] = useState<AmbienceType>(soundboard.getAmbience());
  const [isMuted, setIsMuted] = useState<boolean>(soundboard.getMuted());
  const [volume, setVolume] = useState<number>(soundboard.getVolume());
  const [isOpen, setIsOpen] = useState<boolean>(false);

  useEffect(() => {
    return soundboard.subscribe(() => {
      setAmbience(soundboard.getAmbience());
      setIsMuted(soundboard.getMuted());
      setVolume(soundboard.getVolume());
    });
  }, []);

  return (
    <div className="relative inline-flex items-center">
      {/* Mini quick-toggle button in top bar */}
      <button
        aria-label="氛围音效控制台"
        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
          ambience !== "none" && !isMuted
            ? "border-amber-500/60 bg-amber-500/15 text-amber-300 shadow-sm shadow-amber-500/20"
            : "border-ink-700 bg-ink-900/80 text-stone-300 hover:border-ink-600 hover:text-stone-100"
        }`}
        onClick={() => setIsOpen(!isOpen)}
        title="跑团氛围音效控制台"
        type="button"
      >
        <span className={ambience !== "none" && !isMuted ? "animate-pulse" : ""}>
          {isMuted ? "🔇" : ambience === "none" ? "🎵" : AMBIENCE_OPTIONS.find((o) => o.key === ambience)?.icon}
        </span>
        <span className="hidden sm:inline">
          {isMuted ? "已静音" : ambience === "none" ? "氛围音效" : AMBIENCE_OPTIONS.find((o) => o.key === ambience)?.label}
        </span>
      </button>

      {/* Floating Popup Control Panel */}
      {isOpen ? (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 top-full z-50 mt-2 w-72 rounded-xl border border-ink-700 bg-ink-950/95 p-3.5 shadow-2xl backdrop-blur-md">
            <div className="flex items-center justify-between border-b border-ink-800 pb-2">
              <div className="flex items-center gap-2">
                <span className="text-base">🎵</span>
                <span className="font-display text-sm font-semibold text-parchment-100">跑团音效与氛围台</span>
              </div>
              <button
                className="text-stone-400 hover:text-stone-200"
                onClick={() => setIsOpen(false)}
                type="button"
              >
                ✕
              </button>
            </div>

            {/* Ambience Track Selection */}
            <div className="mt-3">
              <label className="text-2xs font-semibold uppercase tracking-wider text-stone-400">
                环境背景音 (离线合成)
              </label>
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                {AMBIENCE_OPTIONS.map((opt) => (
                  <button
                    className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-xs transition-all ${
                      ambience === opt.key
                        ? "border-amber-500 bg-amber-500/20 font-medium text-amber-200"
                        : "border-ink-800 bg-ink-900/60 text-stone-300 hover:border-ink-700 hover:bg-ink-900"
                    }`}
                    key={opt.key}
                    onClick={() => soundboard.setAmbience(opt.key)}
                    type="button"
                  >
                    <span>{opt.icon}</span>
                    <span>{opt.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Volume and Mute */}
            <div className="mt-3.5 flex items-center gap-3 border-t border-ink-800/80 pt-3">
              <button
                aria-label={isMuted ? "取消静音" : "静音"}
                className={`rounded border p-1.5 text-xs transition-colors ${
                  isMuted
                    ? "border-rose-700/60 bg-rose-950/40 text-rose-300"
                    : "border-ink-700 bg-ink-900 text-stone-300 hover:text-stone-100"
                }`}
                onClick={() => soundboard.toggleMute()}
                type="button"
              >
                {isMuted ? "🔇" : "🔊"}
              </button>
              <input
                aria-label="音量调节"
                className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-ink-700 accent-amber-500"
                max="1"
                min="0"
                onChange={(e) => soundboard.setVolume(parseFloat(e.target.value))}
                step="0.05"
                type="range"
                value={volume}
              />
              <span className="min-w-[2.5rem] text-right font-mono text-2xs text-stone-400">
                {Math.round(volume * 100)}%
              </span>
            </div>

            {/* Action SFX Triggers */}
            <div className="mt-3.5 border-t border-ink-800/80 pt-3">
              <label className="text-2xs font-semibold uppercase tracking-wider text-stone-400">
                即时音效测试
              </label>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                <button
                  className="rounded border border-ink-800 bg-ink-900/60 px-2 py-1 text-2xs text-stone-300 hover:border-amber-500/40 hover:text-amber-200"
                  onClick={() => soundboard.playDiceRoll()}
                  type="button"
                >
                  🎲 掷骰
                </button>
                <button
                  className="rounded border border-amber-800/60 bg-amber-950/30 px-2 py-1 text-2xs text-amber-300 hover:bg-amber-900/40"
                  onClick={() => soundboard.playNat20()}
                  type="button"
                >
                  ✨ Nat 20
                </button>
                <button
                  className="rounded border border-rose-800/60 bg-rose-950/30 px-2 py-1 text-2xs text-rose-300 hover:bg-rose-900/40"
                  onClick={() => soundboard.playNat1()}
                  type="button"
                >
                  💀 Nat 1
                </button>
                <button
                  className="rounded border border-ink-800 bg-ink-900/60 px-2 py-1 text-2xs text-stone-300 hover:border-ink-700"
                  onClick={() => soundboard.playAttackHit()}
                  type="button"
                >
                  ⚔️ 攻击命中
                </button>
                <button
                  className="rounded border border-ink-800 bg-ink-900/60 px-2 py-1 text-2xs text-stone-300 hover:border-ink-700"
                  onClick={() => soundboard.playSpellCast()}
                  type="button"
                >
                  🔮 施法
                </button>
                <button
                  className="rounded border border-ink-800 bg-ink-900/60 px-2 py-1 text-2xs text-stone-300 hover:border-ink-700"
                  onClick={() => soundboard.playPing()}
                  type="button"
                >
                  📍 信号Ping
                </button>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
