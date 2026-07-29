import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

const dmApiBase =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export type RealtimeState = "connecting" | "live" | "degraded";

function campaignQuery(queryKey: readonly unknown[], campaignId: string): boolean {
  return queryKey.some((part) => part === campaignId);
}

export function useCampaignRealtime(campaignId: string | null): RealtimeState {
  const client = useQueryClient();
  const [state, setState] = useState<RealtimeState>("connecting");
  useEffect(() => {
    if (!campaignId || typeof EventSource === "undefined") return;
    const source = new EventSource(
      `${dmApiBase}/campaigns/${encodeURIComponent(campaignId)}/events/stream`,
    );
    const ready = () => setState("live");
    const changed = () => {
      setState("live");
      void client.invalidateQueries({
        predicate: (query) => campaignQuery(query.queryKey, campaignId),
      });
    };
    source.addEventListener("ready", ready);
    source.addEventListener("change", changed);
    source.onerror = () => setState("degraded");
    return () => source.close();
  }, [campaignId, client]);
  return state;
}

export function usePlayerRealtime(enabled: boolean): RealtimeState {
  const client = useQueryClient();
  const [state, setState] = useState<RealtimeState>("connecting");
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const source = new EventSource("/api/v1/player-room/me/events", {
      withCredentials: true,
    });
    const ready = () => setState("live");
    const changed = () => {
      setState("live");
      void client.invalidateQueries({ queryKey: ["my-player-room"] });
    };
    source.addEventListener("ready", ready);
    source.addEventListener("change", changed);
    source.onerror = () => setState("degraded");
    return () => source.close();
  }, [client, enabled]);
  return state;
}
