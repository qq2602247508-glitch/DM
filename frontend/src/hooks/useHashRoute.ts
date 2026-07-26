import { useCallback, useEffect, useState } from "react";

export type RoutePath =
  | "/"
  | "/assistant"
  | "/game-table"
  | "/rules"
  | "/campaigns"
  | "/characters"
  | "/npcs"
  | "/locations"
  | "/inventory"
  | "/scenes"
  | "/events"
  | "/quests"
  | "/combat"
  | "/proposals"
  | "/settings"
  | "/player";

const ROUTES: readonly RoutePath[] = [
  "/",
  "/assistant",
  "/game-table",
  "/rules",
  "/campaigns",
  "/characters",
  "/npcs",
  "/locations",
  "/inventory",
  "/scenes",
  "/events",
  "/quests",
  "/combat",
  "/proposals",
  "/settings",
  "/player",
];

function parseHash(): RoutePath {
  const raw = window.location.hash.replace(/^#/, "");
  const path = raw.startsWith("/") ? raw : `/${raw}`;
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
