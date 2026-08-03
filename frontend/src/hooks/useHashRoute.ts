import { useCallback, useEffect, useState } from "react";

export type RoutePath =
  | "/"
  | "/assistant"
  | "/game-table"
  | "/rules"
  | "/compendium"
  | "/campaigns"
  | "/characters"
  | "/npcs"
  | "/locations"
  | "/inventory"
  | "/merchants"
  | "/scenes"
  | "/events"
  | "/quests"
  | "/simulation"
  | "/combat"
  | "/proposals"
  | "/settings"
  | "/player";

const ROUTES: readonly RoutePath[] = [
  "/",
  "/assistant",
  "/game-table",
  "/rules",
  "/compendium",
  "/campaigns",
  "/characters",
  "/npcs",
  "/locations",
  "/inventory",
  "/merchants",
  "/scenes",
  "/events",
  "/quests",
  "/simulation",
  "/combat",
  "/proposals",
  "/settings",
  "/player",
];

function parseHash(): RoutePath {
  const raw = window.location.hash.replace(/^#/, "");
  const rawPath = raw.split("?", 1)[0] ?? "";
  const path = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
  return (ROUTES as readonly string[]).includes(path) ? (path as RoutePath) : "/";
}

export function navigate(path: RoutePath): void {
  window.location.hash = path;
}

export function useHashRoute(): RoutePath {
  const [route, setRoute] = useState<RoutePath>(() => parseHash());

  useEffect(() => {
    const onChange = () => setRoute(parseHash());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return route;
}

export function useNavigate(): (path: RoutePath) => void {
  return useCallback((path: RoutePath) => navigate(path), []);
}
