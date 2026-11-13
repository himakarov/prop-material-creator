# Prop Material Creator

[Русский](README.md) | [English](README.en.md)

Karma MaterialX material builder for **single FBX props** in Houdini Solaris,
with one-click assignment onto the geometry. Companion to the Character Material
Tool, on the same **CGA Tools** shelf.

## What it does

Given one prop's flat `textures` folder — where each file is named
`<material>_<channel>` (`body_dif.png`, `button_bump.png`, `chip_dif.png`) —
the tool:

1. Groups textures by material prefix.
2. Builds one `mtlxstandard_surface` subnet per material inside a
   `materiallibrary` LOP.
3. Assigns each material to the matching `GeomSubset` (or mesh) of the prop.

Scope by design: **one prop = one FBX + its own textures folder.** Everything
in the folder belongs to that prop.

## Install

1. Download the latest build from the [latest release](https://github.com/himakarov/prop-material-creator/releases/latest).
2. Find your Houdini user prefs folder and the `packages` folder inside it
   (create `packages` if it isn't there yet):

   - Windows: `C:/Users/<name>/Documents/houdini22.0/packages/`
   - macOS: `~/Library/Preferences/houdini/22.0/packages/`
   - Linux: `~/houdini22.0/packages/` (use your version)

3. Unzip straight into `packages`, so you end up with:

   ```
   houdini22.0/
   └── packages/
       ├── prop_material_creator.json
       └── PropMaterialCreator/
           ├── VERSION
           ├── python/
           ├── config/
           └── scripts/
   ```

   Nothing to rename — the archive is already laid out correctly.

4. Restart Houdini. A **Prop Mat** button appears on the **CGA Tools** shelf.

## Use

1. Import the prop into `/stage` (SOP Import / SOP Create).
2. Select that node in the `/stage` network.
3. Click **Prop Mat** on the CGA Tools shelf.
4. Pick the prop geometry in the tree, point at the textures folder, **Build**.

## Channel map

All naming lives in `config/channel_map.json`. Edit it by hand to add suffix
aliases or change colorspaces — no code changes needed.

Each channel entry has:

| key          | meaning                                                        |
|--------------|----------------------------------------------------------------|
| `aliases`    | filename suffixes that map to this channel (case-insensitive)   |
| `colorspace` | `srgb` or `raw`                                                 |
| `mtlx_input` | input on `mtlxstandard_surface` to feed                        |
| `signature`  | mtlximage signature (`color3` / `float` / `vector3`)           |
| `via`        | optional helper node: `mtlxnormalmap` or `mtlxbump`           |

Defaults cover `dif/diffuse/albedo`, `refl/rough`, `metal`, `spec`, `normal`,
`bump/height`, `opacity`, `emission`, `ao`.

## Material presets

A geometry slot with no textures whose name matches a preset (`glass`,
`metall`, `white_plastic`, ...) gets a default material from the
`material_presets` block in `channel_map.json`. Textures always win over presets.

## Matching

Material → geometry matching runs in order: exact name (case-insensitive) →
normalised fuzzy (separators stripped) → prefix containment → shared words
and index number in any order (`mtl_wall6` ↔ `6_wall`, for locations). Pairs
found by the last level are listed separately in the report so you can check
them. Unmatched geometry and unused materials are reported after each build.

## Normals from color

The **Generate normals from base color** checkbox: a material that has a color
map but no normal/bump map of its own gets a normal derived from the color's
luminance (`mtlxbump`). Together with **Add intensity controls** the material
gets a **Normal Strength** parameter (default 0.02).

## Opacity from color alpha

The **Use base color alpha as opacity** checkbox: for decals, foliage and
water whose transparency lives in the alpha channel of the color map. The
alpha is wired to opacity only where the material has no opacity map of its
own and the alpha is not fully opaque.

## Updating

The **Check for updates** button pulls the latest version from GitHub. If a
newer one exists it downloads and overwrites the local files (your edited
`channel_map.json` is preserved). Restart Houdini after updating. The
**Changelog** button shows what changed.
