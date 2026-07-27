# LAN Player Room Design

## Outcome

The DM keeps the complete dashboard and AI services on loopback. Players on the same trusted LAN
join a temporary campaign room through a separate gateway, create or claim one character, and use
a deliberately limited player dashboard. Player and DM state is synchronized through the shared
SQLite campaign database without exposing any DM route to the network.

```text
DM browser -> 127.0.0.1:5173 -> 127.0.0.1:8000 (complete private API)
Player browser -> LAN-IP:8787 -> player gateway (public room API + built player SPA only)
                                      |
                                      +-> shared SQLite state
```

The gateway never initializes the local model runtime and does not mount campaign administration,
AI, backup, diagnostics, raw entity, or generic combat mutation routes.

## Room lifecycle

1. The DM selects a campaign and opens or rotates its player room.
2. The server creates a six-character code from an unambiguous alphabet. Only a salted slow hash
   and the final two-character hint are stored.
3. The DM shares the displayed LAN URL and code. A room has an expiry and can be closed at once.
4. A player enters the code and a display name. A rate-limited join creates a revocable high-entropy
   session held in an HttpOnly, SameSite=Strict cookie.
5. The player creates a level-one D&D 5e 2024 character or claims an unclaimed character in the
   same campaign. One active player may claim a character at a time.
6. Closing or rotating a room and kicking a member revoke affected sessions immediately.

Room, scene, combat, character, and session IDs are always revalidated against the room campaign.
Possessing a valid ID from another campaign never grants access.

## Player experience

The responsive player page has four working modes:

- **Join and character creation:** all core 2024 species, backgrounds, and twelve classes are
  visible. The standard array is assigned once per ability. The server derives starting HP, speed,
  features, proficiencies, skills, equipment, actions, class resources, and spell slots.
- **My character:** only the claimed sheet is visible, including abilities, HP/AC/speed, actions,
  features, resources, spells, inventory, equipment, and carrying information already present on
  the character. No other complete character or NPC record is returned.
- **Public table:** the authoritative current scene, public map objects/tokens, published handouts,
  and player/public events are visible. Players can submit narrative intents, but those intents are
  requests for the DM rather than direct campaign mutations.
- **Combat:** the player sees initiative, the public combat log, their exact state, ally public
  state, and enemy condition bands. Only on their own turn can they move, choose one of their own
  actions, target a legal enemy, submit roll totals, or end the turn.

The local rule search on the player page is deterministic text matching over the pinned rules
corpus. It never calls a generation or embedding model and returns only a short safe projection,
not local paths or internal metadata.

## Synchronization and authority

The room stores the authoritative current scene and combat selected by the DM. Changing scene on
the game table and starting a scene combat update that pointer. The player page polls the public
snapshot every few seconds and every second during an active combat; the DM combat and room panels
poll at the same cadence. Commands are normal HTTP transactions with idempotency keys and optimistic
versions, so retries cannot repeat damage or spend an action twice.

The backend is authoritative for:

- room/session validity and character ownership;
- current turn, action/bonus-action/reaction economy, movement remaining, occupancy, map bounds and
  blocking terrain;
- legal targets and range;
- attack totals versus hidden AC, damage resistance/immunity, HP, pending saving throws, and turn
  advancement.

A player's reported die total is treated as input, never permission to choose another actor,
target, character, campaign, damage type, or action outside their sheet. DM and player receive the
same resulting combat action/log entry after the transaction commits.

## Visibility policy

Player responses are allowlists. They exclude DM notes, NPC secrets, encounter plans, hidden scene
objects/tokens, proposal internals, model prompts, source filesystem paths, backups, diagnostics,
and private events. Enemy exact AC, exact HP, resistances, action inventory, and hidden positions are
not included unless a future DM-controlled reveal explicitly publishes them.

## Operational boundary

The existing desktop launcher starts the loopback backend, loopback Vite dashboard, and the safe
LAN player gateway. With no active room, joining is impossible. The gateway is intended only for a
trusted home/table LAN: no router port forwarding, public tunnel, or reload server is enabled.

## Acceptance path

The feature is complete only when an automated and browser acceptance can perform this sequence:

1. Create campaigns A and B and prove all room/session/character data remains isolated.
2. Open A's room, reject a bad code, join two players with cookies, and kick/revoke one.
3. Create a rules-derived character, bind it, and prove another session cannot claim it or read it.
4. Select a scene and verify only its public projection appears.
5. Start its combat and verify non-current players cannot act.
6. Move within remaining speed, reject blocked/out-of-range movement, attack once, and reject a
   second action after the action is spent.
7. Resolve a monster-generated player roll prompt from the owning player and apply its result once.
8. End the player's turn and observe the same turn/log/state on both DM and player snapshots.
9. Close the room and prove every former player endpoint returns unauthorized.
10. Call representative DM, AI, backup, and knowledge routes on port 8787 and receive 404.
