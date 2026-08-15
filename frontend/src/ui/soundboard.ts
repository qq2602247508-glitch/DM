/**
 * Offline Procedural Soundboard & Ambience Synthesizer for D&D DM Assistant.
 * Uses Web Audio API with zero external assets/network requests.
 */

export type AmbienceType = "none" | "tavern" | "dungeon" | "campfire" | "combat";

class SoundboardEngine {
  private ctx: AudioContext | null = null;
  private currentAmbience: AmbienceType = "none";
  private masterGain: GainNode | null = null;
  private ambienceGain: GainNode | null = null;
  private sfxGain: GainNode | null = null;
  private ambienceTimer: number | null = null;
  private isMuted: boolean = false;
  private volume: number = 0.6;
  private listeners: Set<() => void> = new Set();

  constructor() {
    // Load persisted settings if available
    try {
      const savedMuted = localStorage.getItem("dnd_sfx_muted");
      if (savedMuted !== null) this.isMuted = savedMuted === "true";
      const savedVol = localStorage.getItem("dnd_sfx_volume");
      if (savedVol !== null) this.volume = Math.max(0, Math.min(1, parseFloat(savedVol)));
    } catch {
      // Ignore storage errors in sandbox
    }
  }

  private initContext(): AudioContext | null {
    if (typeof window === "undefined") return null;
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!AudioCtx) return null;
      this.ctx = new AudioCtx();

      this.masterGain = this.ctx.createGain();
      this.masterGain.gain.setValueAtTime(this.isMuted ? 0 : this.volume, this.ctx.currentTime);

      this.ambienceGain = this.ctx.createGain();
      this.ambienceGain.gain.setValueAtTime(0.4, this.ctx.currentTime);
      this.ambienceGain.connect(this.masterGain);

      this.sfxGain = this.ctx.createGain();
      this.sfxGain.gain.setValueAtTime(0.7, this.ctx.currentTime);
      this.sfxGain.connect(this.masterGain);

      this.masterGain.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") {
      void this.ctx.resume();
    }
    return this.ctx;
  }

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify() {
    this.listeners.forEach((fn) => fn());
  }

  public getAmbience(): AmbienceType {
    return this.currentAmbience;
  }

  public getVolume(): number {
    return this.volume;
  }

  public getMuted(): boolean {
    return this.isMuted;
  }

  public setVolume(vol: number) {
    this.volume = Math.max(0, Math.min(1, vol));
    try {
      localStorage.setItem("dnd_sfx_volume", String(this.volume));
    } catch {
      // ignore
    }
    if (this.ctx && this.masterGain && !this.isMuted) {
      this.masterGain.gain.setValueAtTime(this.volume, this.ctx.currentTime);
    }
    this.notify();
  }

  public setMuted(muted: boolean) {
    this.isMuted = muted;
    try {
      localStorage.setItem("dnd_sfx_muted", String(this.isMuted));
    } catch {
      // ignore
    }
    if (this.ctx && this.masterGain) {
      this.masterGain.gain.setValueAtTime(this.isMuted ? 0 : this.volume, this.ctx.currentTime);
    }
    this.notify();
  }

  public toggleMute() {
    this.setMuted(!this.isMuted);
  }

  public setAmbience(type: AmbienceType) {
    if (this.currentAmbience === type) return;
    this.stopAmbience();
    this.currentAmbience = type;
    if (type !== "none") {
      this.startAmbience(type);
    }
    this.notify();
  }

  private stopAmbience() {
    if (this.ambienceTimer) {
      window.clearInterval(this.ambienceTimer);
      this.ambienceTimer = null;
    }
    this.currentAmbience = "none";
  }

  private startAmbience(type: AmbienceType) {
    const ctx = this.initContext();
    if (!ctx || !this.ambienceGain) return;

    if (type === "dungeon") {
      // Deep drone
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(55, ctx.currentTime);
      gain.gain.setValueAtTime(0.08, ctx.currentTime);
      osc.connect(gain);
      gain.connect(this.ambienceGain);
      osc.start();

      // Periodic water drops
      this.ambienceTimer = window.setInterval(() => {
        if (!this.ctx || this.currentAmbience !== "dungeon") return;
        const dropOsc = this.ctx.createOscillator();
        const dropGain = this.ctx.createGain();
        const freq = 1200 + Math.random() * 800;
        dropOsc.type = "sine";
        dropOsc.frequency.setValueAtTime(freq, this.ctx.currentTime);
        dropOsc.frequency.exponentialRampToValueAtTime(freq + 400, this.ctx.currentTime + 0.08);

        dropGain.gain.setValueAtTime(0.06, this.ctx.currentTime);
        dropGain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.15);

        dropOsc.connect(dropGain);
        dropGain.connect(this.ambienceGain!);
        dropOsc.start();
        dropOsc.stop(this.ctx.currentTime + 0.16);
      }, 3500);
    } else if (type === "tavern") {
      // Warm lute chord pulse
      const chords = [
        [220, 277.18, 329.63], // A major
        [196, 246.94, 293.66], // G major
        [174.61, 220, 261.63], // F major
        [164.81, 207.65, 246.94], // E major
      ];
      let chordIdx = 0;
      this.ambienceTimer = window.setInterval(() => {
        if (!this.ctx || this.currentAmbience !== "tavern") return;
        const notes = chords[chordIdx % chords.length];
        chordIdx++;
        if (notes && notes.length > 0) {
          notes.forEach((freq, i) => {
            const osc = this.ctx!.createOscillator();
            const gain = this.ctx!.createGain();
            osc.type = "triangle";
            osc.frequency.setValueAtTime(freq, this.ctx!.currentTime + i * 0.08);
            gain.gain.setValueAtTime(0.04, this.ctx!.currentTime + i * 0.08);
            gain.gain.exponentialRampToValueAtTime(0.001, this.ctx!.currentTime + i * 0.08 + 1.2);

            osc.connect(gain);
            gain.connect(this.ambienceGain!);
            osc.start(this.ctx!.currentTime + i * 0.08);
            osc.stop(this.ctx!.currentTime + i * 0.08 + 1.3);
          });
        }
      }, 2000);
    } else if (type === "campfire") {
      // Crackle pops
      this.ambienceTimer = window.setInterval(() => {
        if (!this.ctx || this.currentAmbience !== "campfire") return;
        for (let i = 0; i < 3; i++) {
          const delay = Math.random() * 0.4;
          const osc = this.ctx.createOscillator();
          const gain = this.ctx.createGain();
          osc.type = "sawtooth";
          osc.frequency.setValueAtTime(150 + Math.random() * 300, this.ctx.currentTime + delay);
          gain.gain.setValueAtTime(0.03, this.ctx.currentTime + delay);
          gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + delay + 0.04);
          osc.connect(gain);
          gain.connect(this.ambienceGain!);
          osc.start(this.ctx.currentTime + delay);
          osc.stop(this.ctx.currentTime + delay + 0.05);
        }
      }, 600);
    } else if (type === "combat") {
      // War drum pulse
      this.ambienceTimer = window.setInterval(() => {
        if (!this.ctx || this.currentAmbience !== "combat") return;
        const drumOsc = this.ctx.createOscillator();
        const drumGain = this.ctx.createGain();
        drumOsc.type = "sine";
        drumOsc.frequency.setValueAtTime(110, this.ctx.currentTime);
        drumOsc.frequency.exponentialRampToValueAtTime(45, this.ctx.currentTime + 0.18);

        drumGain.gain.setValueAtTime(0.12, this.ctx.currentTime);
        drumGain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.35);

        drumOsc.connect(drumGain);
        drumGain.connect(this.ambienceGain!);
        drumOsc.start();
        drumOsc.stop(this.ctx.currentTime + 0.36);
      }, 1000);
    }
  }

  // --- Action SFX ---

  public playDiceRoll() {
    const ctx = this.initContext();
    if (!ctx || !this.sfxGain) return;
    for (let i = 0; i < 4; i++) {
      const t = ctx.currentTime + i * 0.06;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.setValueAtTime(400 + Math.random() * 300, t);
      gain.gain.setValueAtTime(0.06, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.04);
      osc.connect(gain);
      gain.connect(this.sfxGain);
      osc.start(t);
      osc.stop(t + 0.05);
    }
  }

  public playNat20() {
    const ctx = this.initContext();
    if (!ctx || !this.sfxGain) return;
    // Triumphant fanfare arpeggio (C5 -> E5 -> G5 -> C6)
    const notes = [523.25, 659.25, 783.99, 1046.50];
    notes.forEach((freq, idx) => {
      const t = ctx.currentTime + idx * 0.1;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(freq, t);
      gain.gain.setValueAtTime(0.15, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.6);
      osc.connect(gain);
      gain.connect(this.sfxGain!);
      osc.start(t);
      osc.stop(t + 0.65);
    });
  }

  public playNat1() {
    const ctx = this.initContext();
    if (!ctx || !this.sfxGain) return;
    // Dissonant low buzz
    [130.81, 138.59].forEach((freq) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(freq, ctx.currentTime);
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
      osc.connect(gain);
      gain.connect(this.sfxGain!);
      osc.start();
      osc.stop(ctx.currentTime + 0.55);
    });
  }

  public playAttackHit() {
    const ctx = this.initContext();
    if (!ctx || !this.sfxGain) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(300, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(80, ctx.currentTime + 0.12);
    gain.gain.setValueAtTime(0.18, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
    osc.connect(gain);
    gain.connect(this.sfxGain);
    osc.start();
    osc.stop(ctx.currentTime + 0.16);
  }

  public playSpellCast() {
    const ctx = this.initContext();
    if (!ctx || !this.sfxGain) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(350, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(900, ctx.currentTime + 0.25);
    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
    osc.connect(gain);
    gain.connect(this.sfxGain);
    osc.start();
    osc.stop(ctx.currentTime + 0.36);
  }

  public playPing() {
    const ctx = this.initContext();
    if (!ctx || !this.sfxGain) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    gain.gain.setValueAtTime(0.2, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    osc.connect(gain);
    gain.connect(this.sfxGain);
    osc.start();
    osc.stop(ctx.currentTime + 0.42);
  }

  public playHandout() {
    const ctx = this.initContext();
    if (!ctx || !this.sfxGain) return;
    // Chime harp chord
    [440, 554.37, 659.25].forEach((freq, idx) => {
      const t = ctx.currentTime + idx * 0.08;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, t);
      gain.gain.setValueAtTime(0.12, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
      osc.connect(gain);
      gain.connect(this.sfxGain!);
      osc.start(t);
      osc.stop(t + 0.52);
    });
  }
}

export const soundboard = new SoundboardEngine();
