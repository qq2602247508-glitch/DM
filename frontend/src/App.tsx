import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, type ReactElement } from "react";

import { AppShell } from "./components/AppShell";
import { useHashRoute } from "./hooks/useHashRoute";
import { AssistantPrefillProvider, CampaignProvider } from "./hooks/providers";
import { ToastProvider } from "./components/ToastProvider";
import { LoadingBlock } from "./ui/primitives";

const DashboardPage = lazy(() => import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const AssistantPage = lazy(() => import("./pages/AssistantPage").then((module) => ({ default: module.AssistantPage })));
const RulesPage = lazy(() => import("./pages/RulesPage").then((module) => ({ default: module.RulesPage })));
const ProposalsPage = lazy(() => import("./pages/ProposalsPage").then((module) => ({ default: module.ProposalsPage })));
const ManagementPage = lazy(() => import("./pages/ManagementPage").then((module) => ({ default: module.ManagementPage })));
const CombatPage = lazy(() => import("./pages/CombatPage").then((module) => ({ default: module.CombatPage })));
const StoryManagementPage = lazy(() => import("./pages/StoryManagementPage").then((module) => ({ default: module.StoryManagementPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const NpcPage = lazy(() => import("./pages/NpcPage").then((module) => ({ default: module.NpcPage })));
const LocationsPage = lazy(() => import("./pages/LocationsPage").then((module) => ({ default: module.LocationsPage })));
const InventoryPage = lazy(() => import("./pages/InventoryPage").then((module) => ({ default: module.InventoryPage })));
const ScenesPage = lazy(() => import("./pages/ScenesPage").then((module) => ({ default: module.ScenesPage })));
const GameTablePage = lazy(() => import("./pages/GameTablePage").then((module) => ({ default: module.GameTablePage })));
const PlayerPage = lazy(() => import("./pages/PlayerPage").then((module) => ({ default: module.PlayerPage })));
const CompendiumPage = lazy(() => import("./pages/CompendiumPage").then((module) => ({ default: module.CompendiumPage })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
    },
  },
});

function RoutedPage(): ReactElement {
  const route = useHashRoute();
  switch (route) {
    case "/assistant":
      return <AssistantPage />;
    case "/game-table":
      return <GameTablePage />;
    case "/rules":
      return <RulesPage />;
    case "/compendium":
      return <CompendiumPage />;
    case "/proposals":
      return <ProposalsPage />;
    case "/campaigns":
      return <ManagementPage kind="campaigns" />;
    case "/characters":
      return <ManagementPage kind="characters" />;
    case "/npcs":
      return <NpcPage />;
    case "/locations":
      return <LocationsPage />;
    case "/inventory":
      return <InventoryPage />;
    case "/scenes":
      return <ScenesPage />;
    case "/events":
      return <ManagementPage kind="events" />;
    case "/quests":
      return <StoryManagementPage />;
    case "/combat":
      return <CombatPage />;
    case "/settings":
      return <SettingsPage />;
    case "/player":
      return <PlayerPage />;
    default:
      return <DashboardPage />;
  }
}

export function App(): ReactElement {
  const route = useHashRoute();
  return (
    <QueryClientProvider client={queryClient}>
      <CampaignProvider>
        <ToastProvider>
          <AssistantPrefillProvider>
            <Suspense fallback={<LoadingBlock label="正在载入工作区…" />}>
              {route === "/player" ? <PlayerPage /> : <AppShell><RoutedPage /></AppShell>}
            </Suspense>
          </AssistantPrefillProvider>
        </ToastProvider>
      </CampaignProvider>
    </QueryClientProvider>
  );
}
