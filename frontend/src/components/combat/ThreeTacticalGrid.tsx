import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import * as THREE from "three";
import type { Combatant } from "../../api/types";
import { gridDistanceFt, isAimPointInRange, type GridPoint } from "../../ui/gridTargeting";
import type { CombatTargeting } from "./TurnCommandConsole";
import type { VfxEvent } from "../../pages/QuickCombatPage";
import { soundboard } from "../../ui/soundboard";

export type ThreeTacticalGridProps = {
  campaignId: string;
  combatId: string;
  fighters: Combatant[];
  activeFighterId: string | null;
  selectedTargetId: string;
  onTargetSelect: (id: string) => void;
  positions: Record<string, [number, number]>;
  targeting: CombatTargeting | null;
  interactionMode: "move" | "target";
  onInteractionModeChange: (mode: "move" | "target") => void;
  aimPoint: GridPoint | null;
  onAimPointChange: (point: GridPoint | null) => void;
  areaKeys: Set<string>;
  vfxEvents: VfxEvent[];
  onSpawnVfx: (event: Omit<VfxEvent, "id">) => void;
  onMoveToken: (fighter: Combatant, newRow: number, newCol: number, spentFt: number) => void;
  showEnemyThreat: boolean;
  onToggleEnemyThreat: () => void;
};

type CellTerrain = {
  elevationFt: number;
  isWall?: boolean;
  isStairs?: boolean;
  isPillar?: boolean;
};

function getCellTerrain(r: number, c: number): CellTerrain {
  if (r === 4 && (c === 4 || c === 5)) return { elevationFt: 5, isStairs: true };
  if (r === 7 && (c === 4 || c === 5)) return { elevationFt: 5, isStairs: true };

  if (c <= 3 && r >= 2 && r <= 9) return { elevationFt: 10 };
  if (c <= 4 && r >= 3 && r <= 8) return { elevationFt: 10 };

  if (c >= 10 && r >= 2 && r <= 4) return { elevationFt: 15 };

  if ((r === 1 || r === 10) && (c === 1 || c === 12)) return { elevationFt: 8, isPillar: true };
  if (r === 5 && c === 8) return { elevationFt: 6, isPillar: true };
  if (r === 6 && c === 8) return { elevationFt: 6, isPillar: true };

  return { elevationFt: 0 };
}

function combatantElevationFt(fighter: Combatant): number {
  const snap = fighter.snapshot_json as Record<string, unknown> | undefined;
  if (!snap) return 0;
  const pos = snap.grid_position as { elevation_ft?: number } | undefined;
  if (pos && typeof pos.elevation_ft === "number") return pos.elevation_ft;
  if (typeof snap.elevation_ft === "number") return snap.elevation_ft;
  if (typeof snap.elevation === "number") return snap.elevation;
  return 0;
}

// Cached High-Resolution Token HUD Badge Texture
const badgeTextureCache = new Map<string, THREE.CanvasTexture>();

function getOrCreateTokenBadgeTexture(fighter: Combatant, isMeleeThreatened: boolean): THREE.CanvasTexture {
  const isMonster = fighter.entity_type === "monster";
  const hp = Math.max(0, fighter.hp ?? 0);
  const maxHp = Math.max(1, fighter.max_hp ?? 10);
  const ac = fighter.armor_class ?? 10;
  const name = fighter.display_name?.slice(0, 9) ?? "单位";
  const cacheKey = `${fighter.id}_${hp}_${maxHp}_${ac}_${name}_${isMonster}_${isMeleeThreatened}`;

  const cached = badgeTextureCache.get(cacheKey);
  if (cached) return cached;

  const canvas = document.createElement("canvas");
  canvas.width = 300;
  canvas.height = 140;
  let ctx: CanvasRenderingContext2D | null = null;
  try {
    ctx = canvas.getContext("2d");
  } catch {
    ctx = null;
  }
  if (!ctx) {
    const fallbackTex = new THREE.CanvasTexture(canvas);
    badgeTextureCache.set(cacheKey, fallbackTex);
    return fallbackTex;
  }

  try {
    ctx.clearRect(0, 0, 300, 140);
    const hpPct = Math.max(0, Math.min(1, hp / maxHp));

    // Background Pill
    ctx.fillStyle = "rgba(10, 15, 26, 0.92)";
    ctx.strokeStyle = isMonster ? "#f43f5e" : "#38bdf8";
    ctx.lineWidth = 3;
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(10, 10, 280, 120, 18);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(10, 10, 280, 120);
      ctx.strokeRect(10, 10, 280, 120);
    }

    // Name text
    ctx.fillStyle = isMonster ? "#fecdd3" : "#f1f5f9";
    ctx.font = "bold 24px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(name, 150, 44);

    // HP Bar Track
    ctx.fillStyle = "#1e293b";
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(24, 58, 252, 22, 11);
      ctx.fill();
      ctx.fillStyle = hpPct > 0.5 ? "#10b981" : hpPct > 0.2 ? "#f59e0b" : "#ef4444";
      ctx.beginPath();
      ctx.roundRect(24, 58, Math.max(10, 252 * hpPct), 22, 11);
      ctx.fill();
    } else {
      ctx.fillRect(24, 58, 252, 22);
      ctx.fillStyle = hpPct > 0.5 ? "#10b981" : hpPct > 0.2 ? "#f59e0b" : "#ef4444";
      ctx.fillRect(24, 58, Math.max(10, 252 * hpPct), 22);
    }

    // HP Number
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 15px monospace";
    ctx.fillText(`${hp} / ${maxHp} HP`, 150, 75);

    // Status / AC Badge
    if (isMeleeThreatened && !isMonster) {
      ctx.fillStyle = "#f43f5e";
      ctx.font = "bold 17px sans-serif";
      ctx.fillText("⚠️ 处于近战威胁", 150, 112);
    } else {
      ctx.fillStyle = "#94a3b8";
      ctx.font = "bold 16px monospace";
      ctx.fillText(`🛡️ AC ${ac}`, 150, 112);
    }
  } catch {
    // Canvas fallback
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  badgeTextureCache.set(cacheKey, texture);
  return texture;
}

export function ThreeTacticalGrid({
  fighters,
  activeFighterId,
  selectedTargetId,
  onTargetSelect,
  positions,
  targeting,
  interactionMode,
  onInteractionModeChange,
  aimPoint,
  onAimPointChange,
  areaKeys,
  vfxEvents,
  onSpawnVfx,
  onMoveToken,
  showEnemyThreat,
  onToggleEnemyThreat,
}: ThreeTacticalGridProps): ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredCellText, setHoveredCellText] = useState<{ row: number; col: number } | null>(null);
  const [cameraPreset, setCameraPreset] = useState<"iso" | "top" | "close">("iso");

  const width = 12;
  const height = 10;
  const cellSize = 1.6;
  const cellSizeFt = 5;

  // Active combatant whose turn it is
  const activeFighter = fighters.find((f) => f.id === activeFighterId) ?? fighters[0] ?? null;
  const activePos = activeFighter ? (positions[activeFighter.id] ?? [3, 3]) : [3, 3];
  const activePosition: GridPoint = { row: activePos[0], col: activePos[1] };

  // Always bind the mover to the Player Character (or selected PC)
  const targetedCombatant = fighters.find((f) => f.id === selectedTargetId);
  const moverFighter = (targetedCombatant && (targetedCombatant.entity_type === "character" || targetedCombatant.entity_type === "npc"))
    ? targetedCombatant
    : (activeFighter && (activeFighter.entity_type === "character" || activeFighter.entity_type === "npc"))
      ? activeFighter
      : (fighters.find((f) => f.entity_type === "character" || f.entity_type === "npc") ?? activeFighter);

  const moverPos = moverFighter ? (positions[moverFighter.id] ?? [3, 3]) : [3, 3];
  
  // Safe remaining movement fallback
  const moverRemaining = (moverFighter?.movement_remaining_ft !== undefined && moverFighter?.movement_remaining_ft !== null && moverFighter.movement_remaining_ft > 0)
    ? moverFighter.movement_remaining_ft
    : (moverFighter?.speed_ft ?? 30);

  // Compute enemy threat maps
  const enemyThreatCells = useMemo(() => {
    if (!showEnemyThreat) {
      return {
        meleeMap: new Map<string, string[]>(),
        rangedMap: new Map<string, string[]>(),
      };
    }
    const meleeMap = new Map<string, string[]>();
    const rangedMap = new Map<string, string[]>();

    const enemies = fighters.filter((f) => f.entity_type === "monster" && (f.hp ?? 0) > 0);
    enemies.forEach((enemy) => {
      const pos = positions[enemy.id];
      if (!pos) return;

      for (let r = 1; r <= height; r++) {
        for (let c = 1; c <= width; c++) {
          const key = `${r}:${c}`;
          const dist = gridDistanceFt({ row: pos[0], col: pos[1] }, { row: r, col: c }, cellSizeFt);
          if (dist <= 5) {
            const list = meleeMap.get(key) ?? [];
            list.push(enemy.display_name);
            meleeMap.set(key, list);
          } else if (dist <= 30) {
            const list = rangedMap.get(key) ?? [];
            list.push(enemy.display_name);
            rangedMap.set(key, list);
          }
        }
      }
    });

    return { meleeMap, rangedMap };
  }, [fighters, positions, showEnemyThreat, height, width, cellSizeFt]);

  // Three.js Scene Refs
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const tileMeshesRef = useRef<Map<string, { capMesh: THREE.Mesh; capEdgeLine: THREE.LineSegments; blockMesh: THREE.Mesh }>>(new Map());
  const tokenGroupsRef = useRef<Map<string, THREE.Group>>(new Map());
  const particleGroupRef = useRef<THREE.Group>(new THREE.Group());
  const trajectoryGroupRef = useRef<THREE.Group>(new THREE.Group());
  const hoverPathGroupRef = useRef<THREE.Group>(new THREE.Group());

  // Orbit controls & drag detection state
  const isDraggingRef = useRef<boolean>(false);
  const pointerDownPosRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const previousMousePositionRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const hoveredCellRef = useRef<{ row: number; col: number } | null>(null);

  const sphericalRef = useRef<{ radius: number; theta: number; phi: number }>({
    radius: 24,
    theta: Math.PI / 4,
    phi: Math.PI / 3.4,
  });
  const targetLookAtRef = useRef<THREE.Vector3>(new THREE.Vector3(0, 0, 0));

  const updateCameraFromSpherical = useCallback(() => {
    if (!cameraRef.current) return;
    const { radius, theta, phi } = sphericalRef.current;
    const x = radius * Math.sin(phi) * Math.sin(theta);
    const y = radius * Math.cos(phi);
    const z = radius * Math.sin(phi) * Math.cos(theta);

    cameraRef.current.position.set(
      targetLookAtRef.current.x + x,
      targetLookAtRef.current.y + y,
      targetLookAtRef.current.z + z,
    );
    cameraRef.current.lookAt(targetLookAtRef.current);
  }, []);

  const applyCameraPreset = useCallback((preset: "iso" | "top" | "close") => {
    setCameraPreset(preset);
    if (preset === "iso") {
      sphericalRef.current = { radius: 24, theta: Math.PI / 4, phi: Math.PI / 3.4 };
    } else if (preset === "top") {
      sphericalRef.current = { radius: 22, theta: 0.001, phi: 0.05 };
    } else if (preset === "close") {
      sphericalRef.current = { radius: 14, theta: Math.PI / 3.8, phi: Math.PI / 2.6 };
    }
    updateCameraFromSpherical();
  }, [updateCameraFromSpherical]);

  const gridToWorld = useCallback((row: number, col: number, manualElevationFt?: number): THREE.Vector3 => {
    const terrain = getCellTerrain(row, col);
    const elevFt = manualElevationFt !== undefined ? manualElevationFt : terrain.elevationFt;
    const x = (col - (width + 1) / 2) * cellSize;
    const z = (row - (height + 1) / 2) * cellSize;
    const y = (elevFt / 5) * 0.45;
    return new THREE.Vector3(x, y, z);
  }, [width, height, cellSize]);

  // Mathematical Raycast to determine exact Grid Cell (0 dead-zones)
  const getCellFromPointer = useCallback((e: React.PointerEvent<HTMLDivElement>): { row: number; col: number } | null => {
    if (!rendererRef.current || !cameraRef.current) return null;
    const rect = rendererRef.current.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, cameraRef.current);

    // 1. Raycast across all tile meshes (precise elevated terrain)
    const allInteractables: THREE.Object3D[] = [];
    tileMeshesRef.current.forEach((t) => allInteractables.push(t.capMesh, t.blockMesh));
    const tileHits = raycaster.intersectObjects(allInteractables);

    if (tileHits.length > 0) {
      const uData = tileHits[0].object.userData as { row?: number; col?: number };
      if (uData?.row && uData?.col) {
        return { row: uData.row, col: uData.col };
      }
    }

    // 2. Mathematical ground plane raycast fallback (guarantees 100% cell hit)
    const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const planeHit = new THREE.Vector3();
    if (raycaster.ray.intersectPlane(groundPlane, planeHit)) {
      const c = Math.round(planeHit.x / cellSize + (width + 1) / 2);
      const r = Math.round(planeHit.z / cellSize + (height + 1) / 2);
      if (r >= 1 && r <= height && c >= 1 && c <= width) {
        return { row: r, col: c };
      }
    }

    return null;
  }, [width, height, cellSize]);

  // Fast direct WebGL hover path update (0ms latency, zero React re-render lag)
  const updateHoverVisuals = useCallback((cell: { row: number; col: number } | null) => {
    const group = hoverPathGroupRef.current;
    group.clear();

    if (!cell || interactionMode !== "move" || !moverPos) return;

    const distFt = gridDistanceFt({ row: moverPos[0], col: moverPos[1] }, cell, cellSizeFt);
    const isReachable = distFt <= moverRemaining && moverRemaining > 0;
    const isOccupied = fighters.some((f) => positions[f.id]?.[0] === cell.row && positions[f.id]?.[1] === cell.col);

    if (isOccupied && (cell.row !== moverPos[0] || cell.col !== moverPos[1])) return;

    const originWPos = gridToWorld(moverPos[0], moverPos[1]);
    originWPos.y += 0.15;

    const destWPos = gridToWorld(cell.row, cell.col);
    destWPos.y += 0.15;

    // 1. Sleek Navigation Ground Line
    if (originWPos.distanceTo(destWPos) > 0.2) {
      const lineGeo = new THREE.BufferGeometry().setFromPoints([originWPos, destWPos]);
      lineGeo.computeBoundingSphere();
      const lineMat = new THREE.LineBasicMaterial({
        color: isReachable ? 0x10b981 : 0xf43f5e,
        linewidth: 3,
      });
      group.add(new THREE.Line(lineGeo, lineMat));
    }

    // 2. Landing Concentric Target Disc Marker
    const ringGeo = new THREE.RingGeometry(0.35, 0.55, 24);
    const ringMat = new THREE.MeshBasicMaterial({
      color: isReachable ? 0x34d399 : 0xf43f5e,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.9,
    });
    const ringMesh = new THREE.Mesh(ringGeo, ringMat);
    ringMesh.rotation.x = -Math.PI / 2;
    ringMesh.position.set(destWPos.x, destWPos.y + 0.02, destWPos.z);
    ringMesh.name = "hoverAimReticle";
    group.add(ringMesh);
  }, [interactionMode, moverPos, moverRemaining, fighters, positions, gridToWorld, cellSizeFt]);

  // Initialize Three.js Scene with Premium Architectural Blueprint Materials
  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    scene.background = new THREE.Color(0x0a101d);

    const camera = new THREE.PerspectiveCamera(40, container.clientWidth / container.clientHeight, 0.1, 1000);
    cameraRef.current = camera;
    updateCameraFromSpherical();

    let renderer: THREE.WebGLRenderer | null = null;
    let animationFrameId: number | null = null;

    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
      renderer.setSize(container.clientWidth || 600, container.clientHeight || 400);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = false;
      rendererRef.current = renderer;

      container.innerHTML = "";
      container.appendChild(renderer.domElement);
    } catch {
      return;
    }

    // Clean Architectural Lighting
    const ambientLight = new THREE.AmbientLight(0xe2e8f0, 1.3);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xffffff, 0.8);
    keyLight.position.set(20, 35, 25);
    scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0x60a5fa, 0.5);
    fillLight.position.set(-20, 20, -20);
    scene.add(fillLight);

    // Deep Slate Ground Base Board
    const basePlateGeo = new THREE.BoxGeometry(width * cellSize + 2.4, 0.25, height * cellSize + 2.4);
    const basePlateMat = new THREE.MeshLambertMaterial({ color: 0x0f172a });
    const basePlateMesh = new THREE.Mesh(basePlateGeo, basePlateMat);
    basePlateMesh.position.y = -0.14;
    scene.add(basePlateMesh);

    const baseEdgesGeo = new THREE.EdgesGeometry(basePlateGeo);
    const baseEdgesMat = new THREE.LineBasicMaterial({ color: 0x334155, linewidth: 2 });
    basePlateMesh.add(new THREE.LineSegments(baseEdgesGeo, baseEdgesMat));

    // Multi-Level Voxel Tiles
    const tilesMap = new Map<string, { capMesh: THREE.Mesh; capEdgeLine: THREE.LineSegments; blockMesh: THREE.Mesh }>();

    for (let r = 1; r <= height; r++) {
      for (let c = 1; c <= width; c++) {
        const key = `${r}:${c}`;
        const terrain = getCellTerrain(r, c);
        const wPos = gridToWorld(r, c, terrain.elevationFt);
        const blockHeight = Math.max(0.15, (terrain.elevationFt / 5) * 0.45 + 0.15);

        // Lower Solid Voxel Extrusion
        const blockGeo = new THREE.BoxGeometry(cellSize * 0.95, blockHeight, cellSize * 0.95);
        const isElevated = terrain.elevationFt > 0;
        const blockMat = new THREE.MeshLambertMaterial({
          color: isElevated ? 0x1e293b : 0x131d2e,
        });
        const blockMesh = new THREE.Mesh(blockGeo, blockMat);
        blockMesh.position.set(wPos.x, blockHeight / 2 - 0.15, wPos.z);
        blockMesh.userData = { row: r, col: c, key, elevationFt: terrain.elevationFt };
        scene.add(blockMesh);

        const blockEdgesGeo = new THREE.EdgesGeometry(blockGeo);
        const blockEdgesMat = new THREE.LineBasicMaterial({
          color: isElevated ? 0x475569 : 0x1e293b,
        });
        blockMesh.add(new THREE.LineSegments(blockEdgesGeo, blockEdgesMat));

        // Interactive Top Cap Step
        const capGeo = new THREE.BoxGeometry(cellSize * 0.92, 0.08, cellSize * 0.92);
        const capMat = new THREE.MeshLambertMaterial({
          color: isElevated ? 0x24324a : (r + c) % 2 === 0 ? 0x182234 : 0x111a28,
        });
        const capMesh = new THREE.Mesh(capGeo, capMat);
        capMesh.position.set(wPos.x, wPos.y + 0.04, wPos.z);
        capMesh.userData = { row: r, col: c, key, elevationFt: terrain.elevationFt };
        scene.add(capMesh);

        // Cap Crisp Outline Wireframe
        const capEdgeGeo = new THREE.EdgesGeometry(capGeo);
        const capEdgeMat = new THREE.LineBasicMaterial({ color: 0x334155, linewidth: 2 });
        const capEdgeLine = new THREE.LineSegments(capEdgeGeo, capEdgeMat);
        capMesh.add(capEdgeLine);

        // Dungeon Stone Pillars
        if (terrain.isPillar) {
          const pillarGeo = new THREE.CylinderGeometry(0.22, 0.28, 1.4, 8);
          const pillarMat = new THREE.MeshLambertMaterial({ color: 0x334155 });
          const pillarMesh = new THREE.Mesh(pillarGeo, pillarMat);
          pillarMesh.position.set(wPos.x, wPos.y + 0.7, wPos.z);
          scene.add(pillarMesh);

          const pillarEdges = new THREE.LineSegments(new THREE.EdgesGeometry(pillarGeo), new THREE.LineBasicMaterial({ color: 0x64748b }));
          pillarMesh.add(pillarEdges);
        }

        tilesMap.set(key, { capMesh, capEdgeLine, blockMesh });
      }
    }
    tileMeshesRef.current = tilesMap;

    // Groups for Particles, Spell Trajectory, and Fast Hover Path
    scene.add(particleGroupRef.current);
    scene.add(trajectoryGroupRef.current);
    scene.add(hoverPathGroupRef.current);

    // 60FPS High-Performance Animation Loop
    const clock = new THREE.Clock();
    const animate = () => {
      if (!renderer || !camera) return;
      animationFrameId = requestAnimationFrame(animate);
      const delta = clock.getDelta();

      // Animate active token gold ring rotation & camera-facing badges
      tokenGroupsRef.current.forEach((group) => {
        const activeRing = group.getObjectByName("activeRing");
        if (activeRing) activeRing.rotation.z += delta * 2;

        const targetRing = group.getObjectByName("targetRing");
        if (targetRing) targetRing.rotation.z -= delta * 1.5;

        const badge = group.getObjectByName("badgeSprite");
        if (badge && cameraRef.current) {
          badge.quaternion.copy(cameraRef.current.quaternion);
        }
      });

      // Animate 3D Trajectory / Hover Reticles
      const reticleMesh = trajectoryGroupRef.current.getObjectByName("aimReticle");
      if (reticleMesh) reticleMesh.rotation.z += delta * 3;

      const hoverReticle = hoverPathGroupRef.current.getObjectByName("hoverAimReticle");
      if (hoverReticle) hoverReticle.rotation.z += delta * 3;

      // Animate floating particles
      particleGroupRef.current.children.forEach((p) => {
        p.position.y += delta * 0.8;
        if (p instanceof THREE.Mesh && p.material instanceof THREE.Material) {
          p.material.opacity -= delta * 1.2;
        }
      });

      renderer.render(scene, camera);
    };
    animate();

    const handleResize = () => {
      if (!container || !camera || !renderer) return;
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      if (animationFrameId !== null) cancelAnimationFrame(animationFrameId);
      if (renderer) renderer.dispose();
    };
  }, [width, height, cellSize, gridToWorld, updateCameraFromSpherical]);

  // Update Dynamic Tile Highlights (Move Range, Spell AoE, Threat Auras)
  useEffect(() => {
    const tilesMap = tileMeshesRef.current;
    if (!tilesMap.size) return;

    for (let r = 1; r <= height; r++) {
      for (let c = 1; c <= width; c++) {
        const key = `${r}:${c}`;
        const item = tilesMap.get(key);
        if (!item) continue;

        const terrain = getCellTerrain(r, c);
        const fighter = fighters.find((f) => positions[f.id]?.[0] === r && positions[f.id]?.[1] === c);

        // Movement Range (Calculated from Mover Fighter)
        const distFromMover = gridDistanceFt({ row: moverPos[0], col: moverPos[1] }, { row: r, col: c }, cellSizeFt);
        const canMoveHere = interactionMode === "move" && moverFighter && !fighter && distFromMover <= moverRemaining && moverRemaining > 0;

        // Spell Range & AoE Coverage
        const inCastRange = targeting
          ? isAimPointInRange(activePosition, { row: r, col: c }, targeting.rangeFt, cellSizeFt)
          : false;
        const isAreaAffected = areaKeys.has(key);

        // Monster Threat Ranges
        const isMeleeThreat = showEnemyThreat && enemyThreatCells.meleeMap.has(key);
        const isRangedThreat = showEnemyThreat && !isMeleeThreat && enemyThreatCells.rangedMap.has(key);

        const capMat = item.capMesh.material as THREE.MeshLambertMaterial;
        const edgeMat = item.capEdgeLine.material as THREE.LineBasicMaterial;

        if (canMoveHere) {
          // 🟢 Brilliant Glowing Emerald Movement Range (100% full coverage)
          capMat.color.setHex(0x047857);
          capMat.emissive.setHex(0x10b981);
          capMat.emissiveIntensity = 0.65;
          edgeMat.color.setHex(0x34d399);
        } else if (isAreaAffected && interactionMode === "target") {
          // 🟣 Hot Magenta Spell AoE
          capMat.color.setHex(0xc026d3);
          capMat.emissive.setHex(0xf0abfc);
          capMat.emissiveIntensity = 0.9;
          edgeMat.color.setHex(0xf472b6);
        } else if (inCastRange && interactionMode === "target") {
          // 🔵 Arcane Cyan Spell Range
          capMat.color.setHex(0x0284c7);
          capMat.emissive.setHex(0x38bdf8);
          capMat.emissiveIntensity = 0.65;
          edgeMat.color.setHex(0x38bdf8);
        } else if (isMeleeThreat) {
          // 🔴 Subtle Crimson Melee Threat Warning
          capMat.color.setHex(0x4c0519);
          capMat.emissive.setHex(0xe11d48);
          capMat.emissiveIntensity = 0.35;
          edgeMat.color.setHex(0xf43f5e);
        } else if (isRangedThreat) {
          // 🟡 Subtle Amber Ranged Threat Warning
          capMat.color.setHex(0x451a03);
          capMat.emissive.setHex(0xd97706);
          capMat.emissiveIntensity = 0.25;
          edgeMat.color.setHex(0xf59e0b);
        } else {
          // Default Slate Dungeon Floor
          capMat.color.setHex(terrain.elevationFt > 0 ? 0x24324a : (r + c) % 2 === 0 ? 0x182234 : 0x111a28);
          capMat.emissive.setHex(0x000000);
          capMat.emissiveIntensity = 0;
          edgeMat.color.setHex(0x334155);
        }
      }
    }
  }, [
    fighters,
    positions,
    moverPos,
    moverFighter,
    moverRemaining,
    interactionMode,
    targeting,
    activePosition,
    areaKeys,
    enemyThreatCells,
    showEnemyThreat,
    height,
    width,
    cellSizeFt,
  ]);

  // Update Dynamic 3D Trajectory in Target Mode
  useEffect(() => {
    const trajGroup = trajectoryGroupRef.current;
    trajGroup.clear();

    if (interactionMode !== "target") return;

    const casterWPos = gridToWorld(activePosition.row, activePosition.col);
    casterWPos.y += 0.8;

    let destPoint: GridPoint | null = aimPoint;
    if (!destPoint && selectedTargetId) {
      const tgt = fighters.find((f) => f.id === selectedTargetId);
      const tgtPos = tgt ? positions[tgt.id] : null;
      if (tgtPos) destPoint = { row: tgtPos[0], col: tgtPos[1] };
    }

    if (!destPoint) return;

    const destWPos = gridToWorld(destPoint.row, destPoint.col);
    destWPos.y += 0.3;

    const distFt = gridDistanceFt(activePosition, destPoint, cellSizeFt);
    const maxRange = targeting?.rangeFt ?? 60;
    const inRange = distFt <= maxRange;

    // 1. Parabolic 3D Curve Beam
    if (casterWPos.distanceTo(destWPos) > 0.3) {
      const midPoint = new THREE.Vector3()
        .addVectors(casterWPos, destWPos)
        .multiplyScalar(0.5);
      midPoint.y += Math.max(0.6, distFt * 0.08);

      const curve = new THREE.QuadraticBezierCurve3(casterWPos, midPoint, destWPos);
      const points = curve.getPoints(24);
      const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
      lineGeo.computeBoundingSphere();
      const lineMat = new THREE.LineBasicMaterial({
        color: inRange ? 0x38bdf8 : 0xf43f5e,
        linewidth: 3,
      });
      const trajectoryLine = new THREE.Line(lineGeo, lineMat);
      trajGroup.add(trajectoryLine);
    }

    // 2. Animated Concentric 3D Reticle
    const reticleGeo = new THREE.RingGeometry(0.5, 0.65, 24);
    const reticleMat = new THREE.MeshBasicMaterial({
      color: inRange ? 0x38bdf8 : 0xf43f5e,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.9,
    });
    const reticleMesh = new THREE.Mesh(reticleGeo, reticleMat);
    reticleMesh.rotation.x = -Math.PI / 2;
    reticleMesh.position.set(destWPos.x, destWPos.y + 0.02, destWPos.z);
    reticleMesh.name = "aimReticle";
    trajGroup.add(reticleMesh);

    // 3. Crosshair Lines
    const crossGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-0.7, 0, 0),
      new THREE.Vector3(0.7, 0, 0),
      new THREE.Vector3(0, 0, -0.7),
      new THREE.Vector3(0, 0, 0.7),
    ]);
    crossGeo.computeBoundingSphere();
    const crossMat = new THREE.LineBasicMaterial({ color: inRange ? 0x7dd3fc : 0xfb7185 });
    const crossMesh = new THREE.LineSegments(crossGeo, crossMat);
    crossMesh.position.set(destWPos.x, destWPos.y + 0.03, destWPos.z);
    trajGroup.add(crossMesh);
  }, [interactionMode, targeting, activePosition, aimPoint, selectedTargetId, fighters, positions, gridToWorld, cellSizeFt]);

  // Update 3D Tabletop Miniature Chess Tokens (Fast texture caching)
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    const currentGroups = tokenGroupsRef.current;
    const existingIds = new Set(fighters.map((f) => f.id));

    // Remove defunct tokens
    currentGroups.forEach((group, id) => {
      if (!existingIds.has(id)) {
        scene.remove(group);
        currentGroups.delete(id);
      }
    });

    // Create or update sleek chess figurine tokens
    fighters.forEach((f, idx) => {
      const defaultPos: [number, number] = f.entity_type === "monster"
        ? [Math.min(9, 3 + idx * 2), 9]
        : [Math.min(9, 3 + idx * 2), 3];
      const pos = positions[f.id] ?? defaultPos;

      const terrain = getCellTerrain(pos[0], pos[1]);
      const manualElev = combatantElevationFt(f);
      const totalElevFt = terrain.elevationFt + manualElev;
      const targetWPos = gridToWorld(pos[0], pos[1], totalElevFt);

      const isPc = f.entity_type === "character";
      const isMonster = f.entity_type === "monster";
      const isActive = f.id === activeFighterId;
      const isSelected = f.id === selectedTargetId;

      let group = currentGroups.get(f.id);

      if (!group) {
        group = new THREE.Group();
        group.userData = { fighterId: f.id };

        // 1. Polished Tabletop Resin Pedestal (底盘)
        const baseGeo = new THREE.CylinderGeometry(0.44, 0.5, 0.18, 24);
        const baseMat = new THREE.MeshLambertMaterial({
          color: isPc ? 0x0369a1 : isMonster ? 0x9f1239 : 0x6d28d9,
        });
        const baseMesh = new THREE.Mesh(baseGeo, baseMat);
        baseMesh.position.y = 0.09;
        group.add(baseMesh);

        const baseEdges = new THREE.LineSegments(
          new THREE.EdgesGeometry(baseGeo),
          new THREE.LineBasicMaterial({ color: isPc ? 0x38bdf8 : isMonster ? 0xf43f5e : 0xc084fc, linewidth: 2 }),
        );
        baseMesh.add(baseEdges);

        // 2. Sculpted Chess Miniature Stem (立柱)
        const stemGeo = new THREE.CylinderGeometry(0.2, 0.32, 0.55, 20);
        const stemMat = new THREE.MeshLambertMaterial({
          color: isPc ? 0x0284c7 : isMonster ? 0xbe123c : 0x7c3aed,
        });
        const stemMesh = new THREE.Mesh(stemGeo, stemMat);
        stemMesh.position.y = 0.45;
        group.add(stemMesh);

        const stemEdges = new THREE.LineSegments(
          new THREE.EdgesGeometry(stemGeo),
          new THREE.LineBasicMaterial({ color: isPc ? 0x7dd3fc : isMonster ? 0xfb7185 : 0xd8b4fe }),
        );
        stemMesh.add(stemEdges);

        // 3. Distinct Class Crest / Head
        const crownGeo = isPc
          ? new THREE.OctahedronGeometry(0.24)
          : isMonster
            ? new THREE.DodecahedronGeometry(0.24)
            : new THREE.SphereGeometry(0.24, 12, 12);
        const crownMat = new THREE.MeshLambertMaterial({
          color: isPc ? 0x38bdf8 : isMonster ? 0xf43f5e : 0xa855f7,
          emissive: isPc ? 0x0284c7 : isMonster ? 0x881337 : 0x6b21a8,
          emissiveIntensity: 0.4,
        });
        const crownMesh = new THREE.Mesh(crownGeo, crownMat);
        crownMesh.position.y = 0.85;
        group.add(crownMesh);

        // 4. Rotating Gold Action Turn Ring
        const activeRingGeo = new THREE.RingGeometry(0.55, 0.65, 24);
        const activeRingMat = new THREE.MeshBasicMaterial({
          color: 0xfbbf24,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.95,
        });
        const activeRing = new THREE.Mesh(activeRingGeo, activeRingMat);
        activeRing.rotation.x = -Math.PI / 2;
        activeRing.position.y = 0.02;
        activeRing.name = "activeRing";
        group.add(activeRing);

        // 5. Emerald Target Selection Ring
        const targetRingGeo = new THREE.RingGeometry(0.55, 0.65, 24);
        const targetRingMat = new THREE.MeshBasicMaterial({
          color: 0x10b981,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.95,
        });
        const targetRing = new THREE.Mesh(targetRingGeo, targetRingMat);
        targetRing.rotation.x = -Math.PI / 2;
        targetRing.position.y = 0.02;
        targetRing.name = "targetRing";
        group.add(targetRing);

        // 6. Compact High-Res Overhead HUD Badge (Cached Texture)
        const isThreatened = enemyThreatCells.meleeMap.has(`${pos[0]}:${pos[1]}`);
        const badgeTexture = getOrCreateTokenBadgeTexture(f, isThreatened);
        const badgeMat = new THREE.SpriteMaterial({ map: badgeTexture, transparent: true });
        const badgeSprite = new THREE.Sprite(badgeMat);
        badgeSprite.scale.set(1.4, 0.68, 1);
        badgeSprite.position.y = 1.35;
        badgeSprite.name = "badgeSprite";
        group.add(badgeSprite);

        group.position.copy(targetWPos);
        scene.add(group);
        currentGroups.set(f.id, group);
      }

      group.position.lerp(targetWPos, 0.3);

      const activeRing = group.getObjectByName("activeRing");
      if (activeRing) activeRing.visible = isActive;

      const targetRing = group.getObjectByName("targetRing");
      if (targetRing) targetRing.visible = isSelected && !isActive;

      const isThreatened = enemyThreatCells.meleeMap.has(`${pos[0]}:${pos[1]}`);
      const badge = group.getObjectByName("badgeSprite") as THREE.Sprite | undefined;
      if (badge && badge.material instanceof THREE.SpriteMaterial) {
        const freshTex = getOrCreateTokenBadgeTexture(f, isThreatened);
        if (badge.material.map !== freshTex) {
          badge.material.map = freshTex;
          badge.material.needsUpdate = true;
        }
      }
    });
  }, [fighters, positions, activeFighterId, selectedTargetId, gridToWorld, enemyThreatCells]);

  // Spawn 3D VFX
  useEffect(() => {
    if (!vfxEvents.length || !sceneRef.current) return;
    const latest = vfxEvents[vfxEvents.length - 1];
    const terrain = getCellTerrain(latest.row, latest.col);
    const wPos = gridToWorld(latest.row, latest.col, terrain.elevationFt);

    if (latest.type === "slash") {
      const geo = new THREE.TorusGeometry(0.6, 0.08, 8, 20, Math.PI * 1.2);
      const mat = new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.95 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(wPos.x, wPos.y + 0.6, wPos.z);
      mesh.rotation.x = Math.PI / 3;
      sceneRef.current.add(mesh);
      setTimeout(() => {
        sceneRef.current?.remove(mesh);
      }, 500);
    } else if (latest.type === "arcane" || latest.type === "fire") {
      const geo = new THREE.SphereGeometry(0.5, 12, 12);
      const mat = new THREE.MeshBasicMaterial({
        color: latest.type === "fire" ? 0xf97316 : 0xd946ef,
        transparent: true,
        opacity: 0.9,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(wPos.x, wPos.y + 0.8, wPos.z);
      sceneRef.current.add(mesh);
      setTimeout(() => {
        sceneRef.current?.remove(mesh);
      }, 600);
    } else if (latest.type === "dust") {
      for (let i = 0; i < 6; i++) {
        const geo = new THREE.SphereGeometry(0.12, 6, 6);
        const mat = new THREE.MeshBasicMaterial({ color: 0x34d399, transparent: true, opacity: 0.85 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(
          wPos.x + (Math.random() - 0.5) * 0.6,
          wPos.y + 0.1 + Math.random() * 0.3,
          wPos.z + (Math.random() - 0.5) * 0.6,
        );
        particleGroupRef.current.add(mesh);
        setTimeout(() => {
          particleGroupRef.current.remove(mesh);
        }, 700);
      }
    }
  }, [vfxEvents, gridToWorld]);

  // Pointer interaction: Left click = Point & Click Move; Right click = Orbit Camera
  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    pointerDownPosRef.current = { x: e.clientX, y: e.clientY };
    previousMousePositionRef.current = { x: e.clientX, y: e.clientY };
    isDraggingRef.current = false;
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const dx = e.clientX - previousMousePositionRef.current.x;
    const dy = e.clientY - previousMousePositionRef.current.y;
    const totalDist = Math.hypot(e.clientX - pointerDownPosRef.current.x, e.clientY - pointerDownPosRef.current.y);

    if (e.buttons === 2 || (e.buttons === 1 && totalDist > 18)) {
      // 3D Camera Orbit
      isDraggingRef.current = true;
      sphericalRef.current.theta -= dx * 0.006;
      sphericalRef.current.phi = Math.max(0.1, Math.min(Math.PI / 2.05, sphericalRef.current.phi - dy * 0.006));
      updateCameraFromSpherical();
      previousMousePositionRef.current = { x: e.clientX, y: e.clientY };
    } else if (e.buttons === 0) {
      // Fast cell detection and instant WebGL path update
      const cell = getCellFromPointer(e);
      if (cell) {
        if (!hoveredCellRef.current || hoveredCellRef.current.row !== cell.row || hoveredCellRef.current.col !== cell.col) {
          hoveredCellRef.current = cell;
          updateHoverVisuals(cell);
          setHoveredCellText(cell);
        }
      } else if (hoveredCellRef.current !== null) {
        hoveredCellRef.current = null;
        updateHoverVisuals(null);
        setHoveredCellText(null);
      }
    }
  };

  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    sphericalRef.current.radius = Math.max(8, Math.min(45, sphericalRef.current.radius + e.deltaY * 0.03));
    updateCameraFromSpherical();
  };

  // Pure 100% Reliable Point-and-Click Movement on Mouse Up
  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const totalDist = Math.hypot(e.clientX - pointerDownPosRef.current.x, e.clientY - pointerDownPosRef.current.y);

    if (e.button === 2 || totalDist > 18 || isDraggingRef.current) {
      isDraggingRef.current = false;
      return;
    }
    isDraggingRef.current = false;

    // Detect clicked cell via hybrid mathematical + mesh raycast (100% coverage)
    const cell = getCellFromPointer(e);
    if (!cell) return;

    const occupant = fighters.find((f) => positions[f.id]?.[0] === cell.row && positions[f.id]?.[1] === cell.col);

    if (occupant) {
      // Clicked on a token / occupant
      onTargetSelect(occupant.id);
      soundboard.playDiceRoll();
      if (interactionMode === "target") {
        onAimPointChange({ row: cell.row, col: cell.col });
      }
    } else if (interactionMode === "move" && moverFighter) {
      // Clicked on a reachable movement tile: INSTANT MOVE!
      const dist = gridDistanceFt({ row: moverPos[0], col: moverPos[1] }, cell, cellSizeFt);
      if (dist <= moverRemaining && moverRemaining > 0) {
        onMoveToken(moverFighter, cell.row, cell.col, dist);
      } else if (dist > moverRemaining) {
        soundboard.playMiss();
      }
    } else if (interactionMode === "target") {
      // In target mode, floor click sets the spell aim point
      onAimPointChange({ row: cell.row, col: cell.col });
    }
  };

  return (
    <div className="relative flex flex-col justify-between rounded-2xl border border-sky-500/30 bg-[#090d16] p-3 shadow-2xl">
      {/* 3D Viewport Top Controls */}
      <div className="z-20 mb-2 flex flex-wrap items-center justify-between gap-2 text-2xs">
        <div className="flex items-center gap-2">
          {/* Interaction Mode Switch */}
          <div className="flex rounded-xl border border-ink-700 bg-ink-900/90 p-0.5 shadow-lg">
            <button
              className={`rounded-lg px-3 py-1 font-bold transition ${
                interactionMode === "move"
                  ? "bg-emerald-600 text-emerald-950 shadow ring-1 ring-emerald-400"
                  : "text-stone-300 hover:text-white"
              }`}
              onClick={() => onInteractionModeChange("move")}
              type="button"
            >
              🏃 移动走位: {moverFighter?.display_name ?? "主角"} ({moverRemaining}尺)
            </button>
            <button
              className={`rounded-lg px-3 py-1 font-bold transition ${
                interactionMode === "target"
                  ? "bg-fuchsia-600 text-fuchsia-950 shadow ring-1 ring-fuchsia-400"
                  : "text-stone-300 hover:text-white"
              }`}
              onClick={() => onInteractionModeChange("target")}
              type="button"
            >
              🔮 施法瞄准 {targeting ? `(${targeting.rangeFt}尺)` : ""}
            </button>
          </div>

          {/* Camera Angles Presets */}
          <div className="flex rounded-xl border border-ink-700 bg-ink-900/90 p-0.5 shadow-lg">
            <button
              className={`rounded-lg px-2.5 py-1 transition ${
                cameraPreset === "iso" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"
              }`}
              onClick={() => applyCameraPreset("iso")}
              type="button"
            >
              📐 45° 战术
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${
                cameraPreset === "top" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"
              }`}
              onClick={() => applyCameraPreset("top")}
              type="button"
            >
              🦅 顶视
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${
                cameraPreset === "close" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"
              }`}
              onClick={() => applyCameraPreset("close")}
              type="button"
            >
              ⚔️ 特写
            </button>
          </div>
        </div>

        {/* Threat Range Switcher */}
        <div className="flex items-center gap-1.5">
          <button
            className={`rounded-xl border px-2.5 py-1 text-2xs font-bold transition flex items-center gap-1.5 shadow-lg ${
              showEnemyThreat
                ? "border-rose-500 bg-rose-950/80 text-rose-200 shadow-[0_0_10px_rgba(244,63,94,0.4)]"
                : "border-ink-700 bg-ink-900 text-stone-400 hover:text-stone-200"
            }`}
            onClick={onToggleEnemyThreat}
            title="切换显示怪物近战 5尺 威胁区与远程 30尺 射程"
            type="button"
          >
            <span>👹 怪物威胁范围: {showEnemyThreat ? "开" : "关"}</span>
            {showEnemyThreat ? (
              <span className="flex items-center gap-1 text-[9px] text-stone-300">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500 inline-block" /> 近战5尺
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 inline-block ml-0.5" /> 远程30尺
              </span>
            ) : null}
          </button>
        </div>
      </div>

      {/* Three.js 3D WebGL Canvas Viewport (Mouse Left Click: Point & Click Move; Right Click: Orbit Camera) */}
      <div
        className="relative h-[380px] w-full cursor-crosshair overflow-hidden rounded-xl border border-slate-800 bg-[#0a101d]"
        onContextMenu={(e) => e.preventDefault()}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
        ref={containerRef}
      />

      {/* Bottom Floating Legend Bar */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px] text-stone-400">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded bg-emerald-500 inline-block" /> 绿色: 可移动范围 ({moverRemaining}尺 · 鼠标点击地格直接走位)
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded bg-sky-500 inline-block" /> 蓝色: 施法射程
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded bg-fuchsia-500 inline-block" /> 紫色: 3D法术范围
          </span>
        </div>

        {hoveredCellText ? (
          <div className="rounded-lg bg-ink-950 px-2 py-0.5 border border-ink-800 font-mono text-amber-300">
            坐标: ({hoveredCellText.row}, {hoveredCellText.col}) · 高度: {getCellTerrain(hoveredCellText.row, hoveredCellText.col).elevationFt} 尺
            {moverPos
              ? ` · 距离 ${gridDistanceFt({ row: moverPos[0], col: moverPos[1] }, hoveredCellText, cellSizeFt)} 尺`
              : ""}
          </div>
        ) : null}
      </div>
    </div>
  );
}
