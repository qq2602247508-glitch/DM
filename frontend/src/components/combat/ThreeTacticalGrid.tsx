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

function combatantElevationFt(fighter: Combatant): number {
  const snap = fighter.snapshot_json as Record<string, unknown> | undefined;
  if (!snap) return 0;
  const pos = snap.grid_position as { elevation_ft?: number } | undefined;
  if (pos && typeof pos.elevation_ft === "number") return pos.elevation_ft;
  if (typeof snap.elevation_ft === "number") return snap.elevation_ft;
  if (typeof snap.elevation === "number") return snap.elevation;
  return 0;
}

// Helper to create circular canvas texture for token nameplate & HP bar sprite
function createTokenBadgeTexture(fighter: Combatant, isMeleeThreatened: boolean): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 128;
  let ctx: CanvasRenderingContext2D | null = null;
  try {
    ctx = canvas.getContext("2d");
  } catch {
    ctx = null;
  }
  if (!ctx) return new THREE.CanvasTexture(canvas);

  try {
    ctx.clearRect(0, 0, 256, 128);

    // Background rounded card
    ctx.fillStyle = "rgba(10, 14, 23, 0.88)";
    ctx.strokeStyle = fighter.entity_type === "monster" ? "rgba(244, 63, 94, 0.9)" : "rgba(245, 158, 11, 0.9)";
    ctx.lineWidth = 4;
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(10, 10, 236, 108, 16);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(10, 10, 236, 108);
      ctx.strokeRect(10, 10, 236, 108);
    }

    // Name
    ctx.fillStyle = "#fef3c7";
    ctx.font = "bold 24px sans-serif";
    ctx.textAlign = "center";
    const name = fighter.display_name?.slice(0, 8) ?? "单位";
    ctx.fillText(name, 128, 44);

    // HP Bar background
    const hp = Math.max(0, fighter.hp ?? 0);
    const maxHp = Math.max(1, fighter.max_hp ?? 10);
    const hpPct = Math.max(0, Math.min(1, hp / maxHp));

    ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(28, 56, 200, 20, 10);
      ctx.fill();
      ctx.fillStyle = hpPct > 0.5 ? "#10b981" : hpPct > 0.2 ? "#f59e0b" : "#ef4444";
      ctx.beginPath();
      ctx.roundRect(28, 56, Math.max(8, 200 * hpPct), 20, 10);
      ctx.fill();
    } else {
      ctx.fillRect(28, 56, 200, 20);
      ctx.fillStyle = hpPct > 0.5 ? "#10b981" : hpPct > 0.2 ? "#f59e0b" : "#ef4444";
      ctx.fillRect(28, 56, Math.max(8, 200 * hpPct), 20);
    }

    // HP Text
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 16px monospace";
    ctx.fillText(`${hp}/${maxHp}`, 128, 72);

    // Opportunity Attack Warning
    if (isMeleeThreatened && fighter.entity_type === "character") {
      ctx.fillStyle = "#ef4444";
      ctx.font = "bold 18px sans-serif";
      ctx.fillText("⚠️ 借机危险区", 128, 104);
    } else {
      ctx.fillStyle = "#94a3b8";
      ctx.font = "16px monospace";
      ctx.fillText(`AC ${fighter.armor_class ?? 10}`, 128, 104);
    }
  } catch {
    // Fallback if canvas methods fail in unit tests
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
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
  const [hoveredCell, setHoveredCell] = useState<{ row: number; col: number } | null>(null);
  const [cameraPreset, setCameraPreset] = useState<"iso" | "top" | "close">("iso");

  const width = 12;
  const height = 10;
  const cellSize = 1.6; // 3D units per 5ft cell
  const cellSizeFt = 5;

  const activeFighter = fighters.find((f) => f.id === activeFighterId) ?? fighters[0] ?? null;
  const activePos = activeFighter ? positions[activeFighter.id] : null;
  const activePosition: GridPoint | null = activePos ? { row: activePos[0], col: activePos[1] } : null;

  const selectedFighter = fighters.find((f) => f.id === selectedTargetId) ?? activeFighter;
  const selectedPos = selectedFighter ? positions[selectedFighter.id] : activePos;
  const selectedRemaining = (selectedFighter?.movement_remaining_ft !== undefined && selectedFighter?.movement_remaining_ft !== null)
    ? selectedFighter.movement_remaining_ft
    : (selectedFighter?.speed_ft ?? 30);

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
  const tileMeshesRef = useRef<Map<string, THREE.Mesh>>(new Map());
  const tokenGroupsRef = useRef<Map<string, THREE.Group>>(new Map());
  const particleGroupRef = useRef<THREE.Group>(new THREE.Group());
  const vfxMeshesRef = useRef<THREE.Object3D[]>([]);

  // Orbit controls state
  const isDraggingRef = useRef<boolean>(false);
  const previousMousePositionRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const sphericalRef = useRef<{ radius: number; theta: number; phi: number }>({
    radius: 22,
    theta: Math.PI / 4,
    phi: Math.PI / 3.2,
  });
  const targetLookAtRef = useRef<THREE.Vector3>(new THREE.Vector3(0, 0, 0));

  // Update camera position from spherical coordinates
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

  // Set camera presets
  const applyCameraPreset = useCallback((preset: "iso" | "top" | "close") => {
    setCameraPreset(preset);
    if (preset === "iso") {
      sphericalRef.current = { radius: 22, theta: Math.PI / 4, phi: Math.PI / 3.2 };
    } else if (preset === "top") {
      sphericalRef.current = { radius: 20, theta: 0.001, phi: 0.05 };
    } else if (preset === "close") {
      sphericalRef.current = { radius: 12, theta: Math.PI / 3.5, phi: Math.PI / 2.6 };
    }
    updateCameraFromSpherical();
  }, [updateCameraFromSpherical]);

  // Convert (row, col) to 3D world space (x, y, z)
  const gridToWorld = useCallback((row: number, col: number, elevationFt = 0): THREE.Vector3 => {
    const x = (col - (width + 1) / 2) * cellSize;
    const z = (row - (height + 1) / 2) * cellSize;
    const y = (elevationFt / 5) * 0.6;
    return new THREE.Vector3(x, y, z);
  }, [width, height, cellSize]);

  // Convert 3D world space (x, z) to (row, col)
  const worldToGrid = useCallback((pos: THREE.Vector3): { row: number; col: number } | null => {
    const col = Math.round(pos.x / cellSize + (width + 1) / 2);
    const row = Math.round(pos.z / cellSize + (height + 1) / 2);
    if (row >= 1 && row <= height && col >= 1 && col <= width) {
      return { row, col };
    }
    return null;
  }, [width, height, cellSize]);

  // Initialize Three.js scene
  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    scene.background = new THREE.Color(0x060911);
    scene.fog = new THREE.FogExp2(0x060911, 0.015);

    const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
    cameraRef.current = camera;
    updateCameraFromSpherical();

    let renderer: THREE.WebGLRenderer | null = null;
    let animationFrameId: number | null = null;

    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(container.clientWidth || 600, container.clientHeight || 400);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.15;
      rendererRef.current = renderer;

      container.innerHTML = "";
      container.appendChild(renderer.domElement);
    } catch {
      // Headless testing environment without hardware WebGL support
      return;
    }

    // 1. Lighting Setup (Atmospheric Tabletop Warmth & Cool Rim Light)
    const ambientLight = new THREE.AmbientLight(0x2a2838, 1.4);
    scene.add(ambientLight);

    const sunLight = new THREE.DirectionalLight(0xfff5e6, 2.2);
    sunLight.position.set(12, 22, 16);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.width = 1024;
    sunLight.shadow.mapSize.height = 1024;
    sunLight.shadow.camera.near = 0.5;
    sunLight.shadow.camera.far = 60;
    sunLight.shadow.camera.left = -15;
    sunLight.shadow.camera.right = 15;
    sunLight.shadow.camera.top = 15;
    sunLight.shadow.camera.bottom = -15;
    sunLight.shadow.bias = -0.0005;
    scene.add(sunLight);

    const rimLight = new THREE.DirectionalLight(0x6366f1, 1.0);
    rimLight.position.set(-15, 12, -15);
    scene.add(rimLight);

    const torchLight = new THREE.PointLight(0xf59e0b, 1.2, 18);
    torchLight.position.set(0, 4, 0);
    scene.add(torchLight);

    // 2. Table Platform Base & Floor Grid Tiles
    const tableGeo = new THREE.BoxGeometry(width * cellSize + 2.5, 0.4, height * cellSize + 2.5);
    const tableMat = new THREE.MeshStandardMaterial({
      color: 0x090c14,
      roughness: 0.85,
      metalness: 0.2,
    });
    const tableMesh = new THREE.Mesh(tableGeo, tableMat);
    tableMesh.position.y = -0.25;
    tableMesh.receiveShadow = true;
    scene.add(tableMesh);

    // Grid Floor Border Rim
    const borderGeo = new THREE.BoxGeometry(width * cellSize + 0.4, 0.15, height * cellSize + 0.4);
    const borderMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.7 });
    const borderMesh = new THREE.Mesh(borderGeo, borderMat);
    borderMesh.position.y = -0.05;
    scene.add(borderMesh);

    // Build Individual Interactive Grid Tiles
    const tileGeo = new THREE.BoxGeometry(cellSize * 0.94, 0.08, cellSize * 0.94);
    const tilesMap = new Map<string, THREE.Mesh>();

    for (let r = 1; r <= height; r++) {
      for (let c = 1; c <= width; c++) {
        const key = `${r}:${c}`;
        const isChecker = (r + c) % 2 === 0;
        const tileMat = new THREE.MeshStandardMaterial({
          color: isChecker ? 0x151b28 : 0x111622,
          roughness: 0.8,
          metalness: 0.15,
        });

        const mesh = new THREE.Mesh(tileGeo, tileMat);
        const wPos = gridToWorld(r, c);
        mesh.position.set(wPos.x, 0, wPos.z);
        mesh.receiveShadow = true;
        mesh.userData = { row: r, col: c, key };

        scene.add(mesh);
        tilesMap.set(key, mesh);
      }
    }
    tileMeshesRef.current = tilesMap;

    // Particle Group
    scene.add(particleGroupRef.current);

    // Animation Loop
    const clock = new THREE.Clock();

    const animate = () => {
      if (!renderer || !camera) return;
      animationFrameId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      // Subtle torch flicker
      torchLight.intensity = 1.1 + Math.sin(elapsed * 4) * 0.15;

      // Animate active token gold ring rotation & pulse
      tokenGroupsRef.current.forEach((group) => {
        const activeRing = group.getObjectByName("activeRing");
        if (activeRing) {
          activeRing.rotation.z += delta * 1.5;
          const s = 1 + Math.sin(elapsed * 4) * 0.05;
          activeRing.scale.set(s, s, s);
        }
        const badge = group.getObjectByName("badgeSprite");
        if (badge && cameraRef.current) {
          badge.quaternion.copy(cameraRef.current.quaternion);
        }
      });

      // Animate particles
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

  // Update Tile Colors based on state (Movement, Spell AoE, Threat Ranges, Hover)
  useEffect(() => {
    const tilesMap = tileMeshesRef.current;
    if (!tilesMap.size) return;

    for (let r = 1; r <= height; r++) {
      for (let c = 1; c <= width; c++) {
        const key = `${r}:${c}`;
        const mesh = tilesMap.get(key);
        if (!mesh) continue;

        const isChecker = (r + c) % 2 === 0;
        const fighter = fighters.find((f) => positions[f.id]?.[0] === r && positions[f.id]?.[1] === c);

        const distFromSelected = selectedPos
          ? gridDistanceFt({ row: selectedPos[0], col: selectedPos[1] }, { row: r, col: c }, cellSizeFt)
          : null;
        const canMoveHere = interactionMode === "move" && selectedFighter && !fighter && distFromSelected !== null && distFromSelected <= selectedRemaining && selectedRemaining > 0;

        const inCastRange = targeting && activePosition
          ? isAimPointInRange(activePosition, { row: r, col: c }, targeting.rangeFt, cellSizeFt)
          : false;
        const isAreaAffected = areaKeys.has(key);
        const isHovered = hoveredCell?.row === r && hoveredCell?.col === c;

        const isMeleeThreat = enemyThreatCells.meleeMap.has(key);
        const isRangedThreat = enemyThreatCells.rangedMap.has(key);

        const mat = mesh.material as THREE.MeshStandardMaterial;

        if (canMoveHere) {
          mat.color.setHex(isHovered ? 0x34d399 : 0x065f46);
          mat.emissive.setHex(isHovered ? 0x10b981 : 0x047857);
          mat.emissiveIntensity = 0.5;
        } else if (isAreaAffected && interactionMode === "target") {
          mat.color.setHex(0xa21caf);
          mat.emissive.setHex(0xd946ef);
          mat.emissiveIntensity = 0.6;
        } else if (inCastRange && interactionMode === "target") {
          mat.color.setHex(0x0369a1);
          mat.emissive.setHex(0x38bdf8);
          mat.emissiveIntensity = 0.35;
        } else if (isMeleeThreat) {
          mat.color.setHex(isHovered ? 0x991b1b : 0x450a0a);
          mat.emissive.setHex(0xe11d48);
          mat.emissiveIntensity = 0.35;
        } else if (isRangedThreat) {
          mat.color.setHex(isHovered ? 0x92400e : 0x451a03);
          mat.emissive.setHex(0xf59e0b);
          mat.emissiveIntensity = 0.2;
        } else if (isHovered) {
          mat.color.setHex(0x334155);
          mat.emissive.setHex(0x64748b);
          mat.emissiveIntensity = 0.2;
        } else {
          mat.color.setHex(isChecker ? 0x151b28 : 0x111622);
          mat.emissive.setHex(0x000000);
          mat.emissiveIntensity = 0;
        }
      }
    }
  }, [
    fighters,
    positions,
    selectedPos,
    selectedFighter,
    selectedRemaining,
    interactionMode,
    targeting,
    activePosition,
    areaKeys,
    hoveredCell,
    enemyThreatCells,
    height,
    width,
    cellSizeFt,
  ]);

  // Update 3D Miniature Tokens (Figurines / 棋子)
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

    // Create or update miniatures
    fighters.forEach((f) => {
      const pos = positions[f.id] ?? [3, 3];
      const elevFt = combatantElevationFt(f);
      const targetWPos = gridToWorld(pos[0], pos[1], elevFt);
      const isPc = f.entity_type === "character";
      const isMonster = f.entity_type === "monster";
      const isActive = f.id === activeFighterId;
      const isSelected = f.id === selectedTargetId;

      let group = currentGroups.get(f.id);

      if (!group) {
        group = new THREE.Group();
        group.userData = { fighterId: f.id };

        // 1. Pedestal Base (棋子圆盘底座)
        const baseGeo = new THREE.CylinderGeometry(0.5, 0.58, 0.16, 32);
        const baseMat = new THREE.MeshStandardMaterial({
          color: isPc ? 0x92400e : isMonster ? 0x881337 : 0x4c1d95,
          metalness: 0.7,
          roughness: 0.3,
        });
        const baseMesh = new THREE.Mesh(baseGeo, baseMat);
        baseMesh.position.y = 0.08;
        baseMesh.castShadow = true;
        baseMesh.receiveShadow = true;
        group.add(baseMesh);

        // Gold / Silver Metallic Rim
        const rimGeo = new THREE.TorusGeometry(0.52, 0.04, 16, 32);
        const rimMat = new THREE.MeshStandardMaterial({
          color: isPc ? 0xf59e0b : isMonster ? 0xf43f5e : 0xa855f7,
          metalness: 0.9,
          roughness: 0.2,
        });
        const rimMesh = new THREE.Mesh(rimGeo, rimMat);
        rimMesh.rotation.x = Math.PI / 2;
        rimMesh.position.y = 0.14;
        group.add(rimMesh);

        // 2. Miniature Figurine Body (棋子立体身段)
        const bodyGeo = new THREE.CylinderGeometry(0.25, 0.38, 0.5, 24);
        const bodyMat = new THREE.MeshStandardMaterial({
          color: isPc ? 0x0284c7 : isMonster ? 0x9f1239 : 0x7c3aed,
          metalness: 0.4,
          roughness: 0.4,
        });
        const bodyMesh = new THREE.Mesh(bodyGeo, bodyMat);
        bodyMesh.position.y = 0.4;
        bodyMesh.castShadow = true;
        group.add(bodyMesh);

        // 3. Miniature Head / Crest (棋子徽标/晶石)
        const headGeo = isPc
          ? new THREE.OctahedronGeometry(0.24)
          : isMonster
            ? new THREE.DodecahedronGeometry(0.24)
            : new THREE.SphereGeometry(0.24, 16, 16);
        const headMat = new THREE.MeshStandardMaterial({
          color: isPc ? 0x38bdf8 : isMonster ? 0xf43f5e : 0xc084fc,
          emissive: isPc ? 0x0284c7 : isMonster ? 0x881337 : 0x6b21a8,
          emissiveIntensity: 0.4,
          metalness: 0.6,
          roughness: 0.25,
        });
        const headMesh = new THREE.Mesh(headGeo, headMat);
        headMesh.position.y = 0.78;
        headMesh.castShadow = true;
        group.add(headMesh);

        // 4. Active Aura Gold Pulsing Ring
        const activeRingGeo = new THREE.RingGeometry(0.65, 0.78, 32);
        const activeRingMat = new THREE.MeshBasicMaterial({
          color: 0xfbbf24,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.85,
        });
        const activeRing = new THREE.Mesh(activeRingGeo, activeRingMat);
        activeRing.rotation.x = -Math.PI / 2;
        activeRing.position.y = 0.02;
        activeRing.name = "activeRing";
        group.add(activeRing);

        // 5. Selected Target Emerald Ring
        const targetRingGeo = new THREE.RingGeometry(0.65, 0.75, 32);
        const targetRingMat = new THREE.MeshBasicMaterial({
          color: 0x10b981,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.85,
        });
        const targetRing = new THREE.Mesh(targetRingGeo, targetRingMat);
        targetRing.rotation.x = -Math.PI / 2;
        targetRing.position.y = 0.02;
        targetRing.name = "targetRing";
        group.add(targetRing);

        // 6. Overhead 3D HUD Badge Sprite
        const badgeTexture = createTokenBadgeTexture(f, false);
        const badgeMat = new THREE.SpriteMaterial({ map: badgeTexture, transparent: true });
        const badgeSprite = new THREE.Sprite(badgeMat);
        badgeSprite.scale.set(2.2, 1.1, 1);
        badgeSprite.position.y = 1.6;
        badgeSprite.name = "badgeSprite";
        group.add(badgeSprite);

        group.position.copy(targetWPos);
        scene.add(group);
        currentGroups.set(f.id, group);
      }

      // Smooth Position Interpolation
      group.position.lerp(targetWPos, 0.2);

      // Ring Visibilities
      const activeRing = group.getObjectByName("activeRing");
      if (activeRing) activeRing.visible = isActive;

      const targetRing = group.getObjectByName("targetRing");
      if (targetRing) targetRing.visible = isSelected && !isActive;

      // Update Sprite Texture
      const isThreatened = enemyThreatCells.meleeMap.has(`${pos[0]}:${pos[1]}`);
      const badge = group.getObjectByName("badgeSprite") as THREE.Sprite | undefined;
      if (badge && badge.material instanceof THREE.SpriteMaterial) {
        badge.material.map?.dispose();
        badge.material.map = createTokenBadgeTexture(f, isThreatened);
        badge.material.needsUpdate = true;
      }
    });
  }, [fighters, positions, activeFighterId, selectedTargetId, gridToWorld, enemyThreatCells]);

  // Spawn 3D VFX when new vfxEvents arrive
  useEffect(() => {
    if (!vfxEvents.length || !sceneRef.current) return;
    const latest = vfxEvents[vfxEvents.length - 1];
    const wPos = gridToWorld(latest.row, latest.col);

    if (latest.type === "slash") {
      const geo = new THREE.TorusGeometry(0.6, 0.08, 8, 24, Math.PI * 1.2);
      const mat = new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.9 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(wPos.x, 0.6, wPos.z);
      mesh.rotation.x = Math.PI / 3;
      sceneRef.current.add(mesh);
      setTimeout(() => {
        sceneRef.current?.remove(mesh);
      }, 500);
    } else if (latest.type === "arcane" || latest.type === "fire") {
      const geo = new THREE.SphereGeometry(0.5, 16, 16);
      const mat = new THREE.MeshBasicMaterial({
        color: latest.type === "fire" ? 0xf97316 : 0xd946ef,
        transparent: true,
        opacity: 0.85,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(wPos.x, 0.8, wPos.z);
      sceneRef.current.add(mesh);
      setTimeout(() => {
        sceneRef.current?.remove(mesh);
      }, 600);
    } else if (latest.type === "dust") {
      for (let i = 0; i < 6; i++) {
        const geo = new THREE.SphereGeometry(0.12, 8, 8);
        const mat = new THREE.MeshBasicMaterial({ color: 0x34d399, transparent: true, opacity: 0.8 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(
          wPos.x + (Math.random() - 0.5) * 0.6,
          0.1 + Math.random() * 0.3,
          wPos.z + (Math.random() - 0.5) * 0.6,
        );
        particleGroupRef.current.add(mesh);
        setTimeout(() => {
          particleGroupRef.current.remove(mesh);
        }, 700);
      }
    }
  }, [vfxEvents, gridToWorld]);

  // Pointer interaction & Raycasting
  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    isDraggingRef.current = false;
    previousMousePositionRef.current = { x: e.clientX, y: e.clientY };
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const dx = e.clientX - previousMousePositionRef.current.x;
    const dy = e.clientY - previousMousePositionRef.current.y;

    if (e.buttons === 1 || e.buttons === 2) {
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        isDraggingRef.current = true;
        sphericalRef.current.theta -= dx * 0.006;
        sphericalRef.current.phi = Math.max(0.1, Math.min(Math.PI / 2.05, sphericalRef.current.phi - dy * 0.006));
        updateCameraFromSpherical();
        previousMousePositionRef.current = { x: e.clientX, y: e.clientY };
      }
    } else {
      // Raycasting for Hover Highlights
      if (!rendererRef.current || !cameraRef.current || !sceneRef.current) return;
      const rect = rendererRef.current.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1,
      );
      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(mouse, cameraRef.current);

      const meshes = Array.from(tileMeshesRef.current.values());
      const intersects = raycaster.intersectObjects(meshes);

      if (intersects.length > 0) {
        const hit = intersects[0].object.userData as { row: number; col: number };
        if (hit.row !== hoveredCell?.row || hit.col !== hoveredCell?.col) {
          setHoveredCell({ row: hit.row, col: hit.col });
        }
      } else if (hoveredCell !== null) {
        setHoveredCell(null);
      }
    }
  };

  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    sphericalRef.current.radius = Math.max(6, Math.min(40, sphericalRef.current.radius + e.deltaY * 0.03));
    updateCameraFromSpherical();
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isDraggingRef.current) return;
    if (!rendererRef.current || !cameraRef.current) return;

    const rect = rendererRef.current.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, cameraRef.current);

    // 1. Check for token hits
    const tokenMeshes: THREE.Object3D[] = [];
    tokenGroupsRef.current.forEach((grp) => tokenMeshes.push(...grp.children));
    const tokenHits = raycaster.intersectObjects(tokenMeshes);

    if (tokenHits.length > 0) {
      let cur: THREE.Object3D | null = tokenHits[0].object;
      while (cur && !cur.userData?.fighterId) {
        cur = cur.parent;
      }
      if (cur?.userData?.fighterId) {
        onTargetSelect(cur.userData.fighterId);
        soundboard.playDiceRoll();
        return;
      }
    }

    // 2. Check for tile hits
    const tileMeshes = Array.from(tileMeshesRef.current.values());
    const tileHits = raycaster.intersectObjects(tileMeshes);

    if (tileHits.length > 0) {
      const hit = tileHits[0].object.userData as { row: number; col: number };
      const point = { row: hit.row, col: hit.col };
      const occupant = fighters.find((f) => positions[f.id]?.[0] === hit.row && positions[f.id]?.[1] === hit.col);

      if (occupant) {
        onTargetSelect(occupant.id);
        soundboard.playDiceRoll();
      } else if (interactionMode === "move" && selectedFighter && selectedPos) {
        const dist = gridDistanceFt({ row: selectedPos[0], col: selectedPos[1] }, point, cellSizeFt);
        if (dist <= selectedRemaining && selectedRemaining > 0) {
          onMoveToken(selectedFighter, hit.row, hit.col, dist);
        }
      } else if (interactionMode === "target") {
        onAimPointChange(point);
      }
    }
  };

  return (
    <div className="relative flex flex-col justify-between rounded-2xl border border-amber-500/30 bg-[#06080d] p-3 shadow-2xl">
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
              🏃 移动走位
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
              🔮 施法瞄准
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
            <span>👹 怪物攻击范围: {showEnemyThreat ? "开" : "关"}</span>
            {showEnemyThreat ? (
              <span className="flex items-center gap-1 text-[9px] text-stone-300">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500 inline-block" /> 近战5尺
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 inline-block ml-0.5" /> 远程30尺
              </span>
            ) : null}
          </button>
        </div>
      </div>

      {/* Three.js 3D WebGL Canvas Viewport */}
      <div
        className="relative h-[380px] w-full cursor-grab active:cursor-grabbing overflow-hidden rounded-xl border border-ink-800 bg-[#04060a]"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
        ref={containerRef}
      />

      {/* Bottom Floating Legend Bar */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px] text-stone-400">
        <div className="flex items-center gap-2">
          <span>🎮 操作提示: <strong className="text-stone-300">按住鼠标拖拽旋转 3D 棋盘</strong> · 滚轮缩放 · 点击网格或棋子交互</span>
        </div>
        {hoveredCell ? (
          <div className="rounded-lg bg-ink-950 px-2 py-0.5 border border-ink-800 font-mono text-amber-300">
            坐标: ({hoveredCell.row}, {hoveredCell.col})
            {selectedPos
              ? ` · 距离 ${gridDistanceFt({ row: selectedPos[0], col: selectedPos[1] }, hoveredCell, cellSizeFt)} 尺`
              : ""}
          </div>
        ) : null}
      </div>
    </div>
  );
}
