import { apiFetch } from "./client";
import type {
  Campaign,
  Character,
  CharacterCompanion,
  Combat,
  Combatant,
  Scene,
  SceneGrid,
} from "./types";
import type { PlayerRoom } from "./playerRoom";

export type SimulationScenario = {
  title: string;
  objective: string;
  checkpoints: string[];
};

export type SimulationState = {
  scenario: SimulationScenario;
  campaign: Campaign;
  scene: Scene;
  grid: SceneGrid | null;
  combat: Combat;
  combatants: Combatant[];
  character: Character;
  companion: CharacterCompanion;
  player_room?: PlayerRoom;
  player_join_code?: string | null;
};

export const getSimulation = (signal?: AbortSignal) =>
  apiFetch<SimulationState>("/simulations/current", { signal });

export const prepareSimulation = () =>
  apiFetch<SimulationState>("/simulations/prepare", { method: "POST" });

export const resetSimulation = () =>
  apiFetch<SimulationState>("/simulations/reset", { method: "POST" });
