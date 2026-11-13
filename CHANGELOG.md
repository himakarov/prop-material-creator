# Changelog

## 1.5.0
- Locations: slots and textures named differently now match. A new last matching level compares the words and the index number regardless of order (mtl_wall6 <-> 6_wall, mtl_props10 <-> 10_atlas_props, mtl_sand <-> sand). When both names carry a number the numbers must agree. Pairs found this way are listed in the build report under "Matched by similar name - please check".
- Fixed materials whose name starts with a digit collapsing into one USD material (1_atlas_props and 9_atlas_props became the same prim). Such materials now get a "mat_" prefix (mat_6_wall).
- New option "Generate normals from base color": a material with a color map but no normal/bump map gets a normal derived from the color's luminance (mtlxbump). With "Add intensity controls" on, the material gets a "Normal Strength" parameter (default 0.02, range 0-0.2).

## 1.4.0
- SpeedTree support. Base color maps exported without a channel suffix (Bark_Base.png, Knot_01.png) are now recognised: a two-pass scan assigns each unsuffixed file to base color, merging it with the material's suffixed maps (Bark_Base_Normal -> material 'Bark_Base'). An explicit _diffuse/_basecolor still wins if both exist. Toggle with "unsuffixed_is_base_color" in the channel map's "parsing" block (default on).
- Added subsurface channels: subsurface_color (_SubsurfaceColor) and subsurface (_SubsurfaceAmount), so SpeedTree foliage/moss SSS maps land on the right inputs instead of spawning junk materials.

## 1.3.1
- Bundled shelf icon

## 1.3.0
- Self-update. "Check for updates" pulls the latest GitHub release, and if it's
  newer, downloads and overwrites the local package files; "Changelog" shows
  what changed. Hand edits to config/channel_map.json are preserved across
  updates. Releases are cut automatically from version tags via GitHub Actions.

## 1.2.2
- Numbered channel suffixes are handled: Diffuse1 / Diffuse2 / Diffuse3 all map
  to base_color; with several of the same channel the first (lowest number)
  wins, the rest are ignored.
- Foreign/stray textures are filtered out. A file that doesn't belong to the
  prop's naming set (e.g. 'Map__13_Normal_Bump' among 'Rocket-Launcher_AK9_*')
  is dropped so it doesn't create a junk material or hijack node naming.
  Conservative: unrelated legit sets (body/chip/diod/wires) and real
  multi-material sets (barrel/grip) are untouched.

## 1.2.1
- Specular intensity control is now always added when intensity controls are
  on, even if the material has no specular map: with a map it's a "Specular
  Mult"; without one, a "Specular" parameter drives the surface value directly
  (default 0.1, so enabling it doesn't change the look until you turn it).

## 1.2.0
- Optional per-channel intensity controls (UI checkbox "Add intensity
  controls"). When on, each textured channel gets a multiply node whose factor
  is promoted to a spare parameter on the material subnet, so you can tune it
  from the material's own panel without diving inside:
    - base_color -> "Base Color Tint" (color multiply)
    - roughness / metalness / specular / etc. -> "<Channel> Mult" (0-2)
    - normal -> "Normal Strength" (mtlxnormalmap scale)
    - bump   -> "Bump Strength" (mtlxbump scale)
  Off by default, so quick builds keep a clean graph.

## 1.1.0
- Material presets for untextured slots. A geometry slot with no textures whose
  name matches a preset (glass, metall, white_plastic, ...) now gets a default
  material built from parameters in channel_map.json ("material_presets").
  Ships with: glass (transmission 1, ior 1.5, roughness 0), metall (metalness 1,
  red base color, roughness 0.25), white_plastic (light grey, roughness 0.5).
- Presets take priority over the single-material fast path: a lone textured
  material no longer paints over glass/metal slots - those get their preset.
- Presets are editable by hand; add a block with "match" aliases and "params"
  (mtlxstandard_surface inputs; a number = float, a 3-list = color).

## 1.0.5
- Channel priority flipped: diffuse (d) now wins over basecolor (b) when both
  are present for the same material.

## 1.0.4
- Channel conflict priority: when two maps feed the same channel for one
  material (e.g. a _b basecolor AND a _d diffuse), the higher-priority alias
  wins. basecolor/b > albedo > diffuse/d. Configurable in channel_map.json
  under "alias_priority".
- Single-material props now assign even when the texture-derived material name
  differs from the FBX slot name (e.g. material 'conditioner_mitsubishi' ->
  slot 'air_conditioner'): one material is bound to all of the prop's geometry.
  Multi-material props still match by name.
- Nodes are spliced INTO the stream below the anchor: whatever previously read
  from the anchor now reads from the new assign/matlib tail, so the graph stays
  a single chain instead of a dangling side branch.
- Prop name for node naming is now also derived from the anchor's stage when no
  prim is picked in the dialog tree, so nodes are named after the asset instead
  of the textures folder.

## 1.0.3
- Single-letter suffixes d/m/n/r/s; nodes named after the prop.

## 1.0.2
- assignmaterial uses the materiallibrary's real published paths.

## 1.0.1
- shop_materialpath_<mat> subsets recognised; prim tree reads composed stage.

## 1.0.0
- Initial release.
