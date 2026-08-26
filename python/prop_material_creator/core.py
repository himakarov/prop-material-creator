"""
core.py - Karma material build logic for single props.

Companion to the Character Material Tool, but inverted where props differ:

  Character pipeline: one subfolder PER material; channel comes from a suffix.
  Prop pipeline:      one FLAT 'textures' folder; both the material name AND
                      the channel live in the filename as `<material>_<channel>`
                      (body_dif.png, button_bump.png, chip_dif.png ...).

Scope (by design): ONE prop = ONE FBX + its own textures folder. Everything in
the given folder belongs to this prop. The user picks the prop's LOP mesh in
the UI and points at the folder; we scan, group textures by material prefix,
build one Karma mtlxstandard_surface subnet per material, and bind each to the
matching GeomSubset (falling back to texture-prefix assignment when the mesh
has no usable subsets).

UI-independent; called from ui.py.
"""

import os
import hou

from . import config as _config


MATERIALS_PREFIX = "/materials/"


# ---------------------------------------------------------------------------
# Texture scanning & filename parsing
# ---------------------------------------------------------------------------
def _strip_trailing_digits(token):
    """Drop a trailing run of digits from a suffix token so 'diffuse1',
    'diffuse2' all match the 'diffuse' alias. Returns (base, had_digits)."""
    import re as _re
    m = _re.match(r"^(.*?)(\d+)$", token)
    if m and m.group(1):
        return m.group(1), True
    return token, False


def _split_stem(stem, cfg):
    """Split a filename stem into (material, channel_name, alias) using the
    channel map. Strategy:
      1. Peel the longest known alias off the tail of the stem, respecting a
         separator boundary. body_basecolor -> ('body', 'base_color', 'basecolor').
         A trailing number on the suffix is tolerated: _Diffuse1 -> diffuse.
      2. Fall back to a plain last-separator split, then match that token.
    Returns (material, channel_name, alias) or (None, None, None).
    The alias is returned so callers can resolve same-channel conflicts by
    priority (basecolor beats diffuse)."""
    low = stem if cfg.case_sensitive else stem.lower()

    # 1. longest-alias tail peel. Try the raw tail first; if the stem ends in
    #    digits (Diffuse1), also try peeling the alias with the digits after it.
    for alias in cfg.all_alias_keys():
        for sep in cfg.separators:
            tail = sep + alias
            if low.endswith(tail) and len(stem) > len(tail):
                material = stem[: len(stem) - len(tail)]
                return (material.strip("".join(cfg.separators)),
                        cfg.match_suffix(alias), alias)
            # tolerate a trailing number: <sep><alias><digits>
            import re as _re
            m = _re.search(_re.escape(sep) + _re.escape(alias) + r"\d+$", low)
            if m and m.start() > 0:
                material = stem[: m.start()]
                return (material.strip("".join(cfg.separators)),
                        cfg.match_suffix(alias), alias)

    # 2. plain split on the last separator that appears
    last_pos = -1
    last_sep = None
    for sep in cfg.separators:
        pos = stem.rfind(sep)
        if pos > last_pos:
            last_pos, last_sep = pos, sep
    if last_pos > 0:
        material = stem[:last_pos]
        token = stem[last_pos + len(last_sep):]
        ch = cfg.match_suffix(token)
        if ch:
            return material.strip("".join(cfg.separators)), ch, token
        # retry after stripping a trailing number (Diffuse3 -> diffuse)
        base, had = _strip_trailing_digits(token)
        if had:
            ch = cfg.match_suffix(base)
            if ch:
                return material.strip("".join(cfg.separators)), ch, base

    # No channel suffix recognised. Do NOT guess here - scan_textures handles
    # the SpeedTree unsuffixed-base-color case in a second pass, where it can
    # see which stems line up with materials that DO have suffixed maps.
    return None, None, None


def scan_textures(folder, cfg):
    """Scan a flat folder and group textures by material.
    Returns:
        materials: dict[material_name] -> dict[channel_name] -> filepath
        unrecognised: list of filenames whose channel could not be parsed

    When two files feed the SAME channel for one material (e.g. a _basecolor
    and a _diffuse both -> base_color), the one whose alias has the higher
    priority wins (basecolor over diffuse)."""
    materials = {}
    # track which alias won each (material, channel) so we can compare priority
    chosen_alias = {}
    unrecognised = []
    try:
        entries = sorted(os.listdir(folder))
    except Exception as exc:
        return {}, ["<cannot list folder: %s>" % exc]

    tex_files = [f for f in entries
                 if os.path.splitext(f)[1].lower() in cfg.texture_exts]

    # -- pass 1: files with a recognised channel suffix --------------------
    leftover = []
    for fname in tex_files:
        stem, _ext = os.path.splitext(fname)
        material, channel, alias = _split_stem(stem, cfg)
        if not material or not channel:
            leftover.append(fname)   # decide in pass 2
            continue
        full = os.path.join(folder, fname).replace("\\", "/")
        materials.setdefault(material, {})
        key = (material, channel)
        if channel in materials[material]:
            if cfg.alias_priority(alias) > cfg.alias_priority(chosen_alias.get(key)):
                materials[material][channel] = full
                chosen_alias[key] = alias
        else:
            materials[material][channel] = full
            chosen_alias[key] = alias

    # -- pass 2: unsuffixed files -> base color ----------------------------
    # SpeedTree leaves the base color map with no channel tag (Bark_Base.png,
    # Knot_01.png) while every other channel IS tagged. A leftover whose stem
    # matches a material we already found from its suffixed maps is that
    # material's base color; a leftover that matches nothing is a standalone
    # single-texture material (a prop with only a color map). Either way it's
    # base color - never a junk channel. An explicit _diffuse/_basecolor from
    # pass 1 already sits in base_color and wins (this only fills, never
    # overwrites).
    if cfg.unsuffixed_is_base_color:
        norm_known = {_norm(m): m for m in materials.keys()}
        for fname in leftover:
            stem, _ext = os.path.splitext(fname)
            mat = stem.strip("".join(cfg.separators))
            if not mat:
                unrecognised.append(fname)
                continue
            target = norm_known.get(_norm(mat), mat)
            full = os.path.join(folder, fname).replace("\\", "/")
            materials.setdefault(target, {})
            if "base_color" not in materials[target]:
                materials[target]["base_color"] = full
                chosen_alias[(target, "base_color")] = "__unsuffixed__"
    else:
        unrecognised.extend(leftover)

    return _filter_foreign(materials), unrecognised


def _filter_foreign(materials):
    """Drop foreign textures that don't belong to this prop.

    Two cases:
      - Many materials (>=3): if a majority share a name prefix, materials not
        sharing it are strays and get dropped. A set of short unrelated names
        (body/chip/diod/wires) has no common prefix, so nothing is dropped.
      - Exactly 2 materials: drop one only if it is a clear outsider - it has
        far fewer maps than the other AND its name is dissimilar (no shared
        prefix). Covers 'Rocket-Launcher_AK9' (5 maps) vs a stray
        'Map__13_Normal_Bump' (1 map)."""
    if len(materials) <= 1:
        return materials

    def _norm_name(s):
        return "".join(c for c in s.lower() if c.isalnum())

    names = list(materials.keys())
    norms = {m: _norm_name(m) for m in names}

    # --- exactly two materials ---
    if len(materials) == 2:
        a, b = names
        ca, cb = len(materials[a]), len(materials[b])
        big, small = (a, b) if ca >= cb else (b, a)
        big_c, small_c = max(ca, cb), min(ca, cb)
        # outsider must be a single-map material dwarfed by a multi-map one
        if small_c == 1 and big_c >= 3:
            common = os.path.commonprefix([norms[a], norms[b]])
            if len(common) < 3:  # dissimilar names -> the small one is foreign
                return {big: materials[big]}
        return materials

    # --- three or more materials: dominant-prefix rule ---
    from collections import Counter
    best_prefix = ""
    for cand_len in range(8, 3, -1):
        counts = Counter(n[:cand_len] for n in norms.values()
                         if len(n) >= cand_len)
        if not counts:
            continue
        pref, cnt = counts.most_common(1)[0]
        if cnt / float(len(names)) >= 0.6 and cnt >= 2:
            best_prefix = pref
            break

    if not best_prefix:
        return materials  # unrelated set -> keep all

    kept = {m: materials[m] for m in names if norms[m].startswith(best_prefix)}
    return kept if kept else materials


# ---------------------------------------------------------------------------
# Material construction (mtlxstandard_surface subnet, same shape as Character)
# ---------------------------------------------------------------------------
def _set_parm(node, names, value):
    for n in names:
        p = node.parm(n)
        if p is not None:
            try:
                p.set(value)
                return True
            except Exception:
                pass
    return False


def _promote_float(sub, parm_name, label, default=1.0, minv=0.0, maxv=2.0):
    """Add a float spare parameter to the subnet and return its name."""
    try:
        grp = sub.parmTemplateGroup()
        pt = hou.FloatParmTemplate(parm_name, label, 1,
                                   default_value=(default,),
                                   min=minv, max=maxv,
                                   min_is_strict=False, max_is_strict=False)
        grp.append(pt)
        sub.setParmTemplateGroup(grp)
        return parm_name
    except Exception:
        return None


def _promote_color(sub, parm_name, label, default=(1.0, 1.0, 1.0)):
    """Add a color (3-float) spare parameter to the subnet."""
    try:
        grp = sub.parmTemplateGroup()
        pt = hou.FloatParmTemplate(parm_name, label, 3,
                                   default_value=default,
                                   min=0.0, max=1.0,
                                   look=hou.parmLook.ColorSquare)
        grp.append(pt)
        sub.setParmTemplateGroup(grp)
        return parm_name
    except Exception:
        return None


def _build_material(matlib, mat_name, channels, cfg, add_controls=False):
    """Build one mtlxstandard_surface subnet named mat_name.
    channels: dict[channel_name] -> filepath.
    add_controls: if True, insert per-channel multiply nodes and promote their
    factors to spare parameters on the subnet, so intensity can be tuned from
    the material's own parameter panel without diving inside."""
    sub = matlib.createNode("subnet", mat_name)
    out = sub.createNode("subnetconnector", "surface_output")
    out.parm("connectorkind").set("output")
    out.parm("parmname").set("surface")
    out.parm("parmlabel").set("Surface")
    _set_parm(out, ["parmtype"], "surface")

    surface = sub.createNode("mtlxstandard_surface", "mtlxstandard_surface")
    out.setInput(0, surface)

    # Deterministic order so graphs look the same every build.
    for channel in sorted(channels.keys()):
        filepath = channels[channel]
        spec = cfg.channel(channel)
        if not spec:
            continue
        mtlx_input = spec.get("mtlx_input")
        colorspace = spec.get("colorspace", "raw")
        signature = spec.get("signature", "float")
        via = spec.get("via")

        # AO has no direct standard_surface input; skip binding but keep the
        # image node so the artist can wire it manually if wanted.
        internal_only = mtlx_input.startswith("_") if mtlx_input else False

        img = sub.createNode("mtlximage", "img_" + channel)
        img.parm("file").set(filepath)
        _set_parm(img, ["signature"], signature)
        _set_parm(img, ["filecolorspace", "colorspace"],
                  "Raw" if colorspace == "raw" else "srgb_texture")

        if internal_only:
            continue

        if via == "mtlxnormalmap":
            nmap = sub.createNode("mtlxnormalmap", "normalmap_" + channel)
            nmap.setInput(0, img)
            surface.setNamedInput(mtlx_input, nmap, 0)
            if add_controls:
                # normalmap has a 'scale' input = normal strength
                pn = _promote_float(sub, channel + "_strength",
                                    channel.capitalize() + " Strength",
                                    default=1.0, minv=0.0, maxv=2.0)
                if pn:
                    p = nmap.parm("scale")
                    if p is not None:
                        try:
                            p.setExpression('ch("../%s")' % pn)
                        except Exception:
                            pass
        elif via == "mtlxbump":
            bump = sub.createNode("mtlxbump", "bump_" + channel)
            bump.setInput(0, img)
            surface.setNamedInput(mtlx_input, bump, 0)
            if add_controls:
                pn = _promote_float(sub, channel + "_strength",
                                    channel.capitalize() + " Strength",
                                    default=1.0, minv=0.0, maxv=2.0)
                if pn:
                    p = bump.parm("scale")
                    if p is not None:
                        try:
                            p.setExpression('ch("../%s")' % pn)
                        except Exception:
                            pass
        else:
            node_to_input = img
            if add_controls:
                is_color = (signature == "color3")
                mult = sub.createNode("mtlxmultiply", "mult_" + channel)
                mult.setInput(0, img)
                if is_color:
                    pn = _promote_color(sub, channel + "_tint",
                                        channel.replace("_", " ").title() + " Tint")
                    # mtlxmultiply color: in2 has components in2r/in2g/in2b.
                    # A 3-float spare parm exposes components as name1/2/3.
                    if pn:
                        for comp, idx in (("r", 1), ("g", 2), ("b", 3)):
                            p = mult.parm("in2" + comp)
                            if p is not None:
                                try:
                                    p.setExpression('ch("../%s%d")' % (pn, idx))
                                except Exception:
                                    pass
                else:
                    pn = _promote_float(sub, channel + "_mult",
                                        channel.replace("_", " ").title() + " Mult",
                                        default=1.0, minv=0.0, maxv=2.0)
                    if pn:
                        p = mult.parm("in2")
                        if p is not None:
                            try:
                                p.setExpression('ch("../%s")' % pn)
                            except Exception:
                                pass
                node_to_input = mult
            surface.setNamedInput(mtlx_input, node_to_input, 0)

    # Always-on Specular control: if there was no specular texture, promote a
    # parameter that drives the surface's specular value directly (there's no
    # map to multiply). If a specular map WAS present, it already got a
    # "Specular Mult" above, so we skip to avoid a duplicate.
    if add_controls:
        specular_had_map = False
        for ch_name in channels:
            spec = cfg.channel(ch_name)
            if spec.get("mtlx_input") == "specular":
                specular_had_map = True
                break
        if not specular_had_map:
            pn = _promote_float(sub, "specular_value", "Specular",
                                default=0.1, minv=0.0, maxv=1.0)
            if pn:
                p = surface.parm("specular")
                if p is not None:
                    try:
                        p.setExpression('ch("../%s")' % pn)
                    except Exception:
                        pass

    try:
        sub.setMaterialFlag(True)
    except Exception:
        pass
    sub.layoutChildren()
    return sub


def _build_preset_material(matlib, mat_name, params):
    """Build an mtlxstandard_surface subnet from preset PARAMETERS (no
    textures). params: dict of mtlxstandard_surface input -> number or 3-list.
    A number sets a float parm; a 3-list sets a color parm."""
    sub = matlib.createNode("subnet", mat_name)
    out = sub.createNode("subnetconnector", "surface_output")
    out.parm("connectorkind").set("output")
    out.parm("parmname").set("surface")
    out.parm("parmlabel").set("Surface")
    _set_parm(out, ["parmtype"], "surface")

    surface = sub.createNode("mtlxstandard_surface", "mtlxstandard_surface")
    out.setInput(0, surface)

    for input_name in sorted(params.keys()):
        value = params[input_name]
        try:
            if isinstance(value, (list, tuple)):
                # color/vector input -> set component parms input_namer/g/b
                comps = list(value) + [0.0] * (3 - len(value))
                set_any = False
                for suffix, comp in zip(("r", "g", "b"), comps):
                    if _set_parm(surface, [input_name + suffix], float(comp)):
                        set_any = True
                if not set_any:
                    # some builds expose a single tuple parm
                    p = surface.parm(input_name)
                    if p is not None:
                        try:
                            p.set(float(comps[0]))
                        except Exception:
                            pass
            else:
                _set_parm(surface, [input_name], float(value))
        except Exception:
            pass

    try:
        sub.setMaterialFlag(True)
    except Exception:
        pass
    sub.layoutChildren()
    return sub
def _norm(name):
    """Normalise a name for fuzzy comparison: lowercase, strip separators."""
    return "".join(c for c in name.lower() if c.isalnum())


# GeomSubset name prefixes Houdini emits when partitioning by an attribute.
# SOP Create / SOP Import partitioning GeomSubsets by `shop_materialpath`
# produces subsets named `shop_materialpath_<MatName>` (or the legacy
# `shop_materialpath__materials_<MatName>`). We recover <MatName> from these so
# a subset like `shop_materialpath_body` matches material `body`.
_SUBSET_ATTR_PREFIXES = (
    "shop_materialpath__materials_",
    "shop_materialpath_",
    "fbx_material_name_",
    "mat_",
)


def _material_name_from_subset(name):
    """Return the material name embedded in an attribute-partitioned subset
    name, or the name unchanged if no known prefix applies.
    shop_materialpath_body -> body ; body -> body."""
    if not name:
        return name
    for pref in _SUBSET_ATTR_PREFIXES:
        if name.startswith(pref) and len(name) > len(pref):
            return name[len(pref):]
    return name


def _is_garbage_name(name):
    """True only for names that carry NO recoverable material info.
    Note: `shop_materialpath_<mat>` is NOT garbage - the material name is
    recoverable via _material_name_from_subset - so it is allowed through."""
    if not name:
        return True
    low = name.lower()
    # bare attribute name with nothing after it -> no material info
    if low in ("shop_materialpath", "fbx_material_name"):
        return True
    if "principledshader" in low:
        return True
    import re as _re
    if _re.match(r"^(mesh|geo|object|prim)_?\d+$", low):
        return True
    return False


def collect_geo(stage, scope_path):
    """Collect GeomSubsets (preferred) and Meshes under scope_path.
    scope_path='' or '/' means the whole stage.
    Returns list of (prim_path, gtype, name)."""
    items = []
    scope = scope_path.rstrip("/") if scope_path not in ("", "/") else ""

    def in_scope(path):
        if not scope:
            return True
        return path == scope or path.startswith(scope + "/")

    try:
        with_subsets = set()
        for p in stage.Traverse():
            if p.GetTypeName() != "GeomSubset":
                continue
            path = str(p.GetPath())
            if not in_scope(path):
                continue
            items.append((path, "subset", p.GetName()))
            with_subsets.add(path.rsplit("/", 1)[0])
        for p in stage.Traverse():
            if p.GetTypeName() != "Mesh":
                continue
            path = str(p.GetPath())
            if not in_scope(path):
                continue
            if path in with_subsets:
                continue
            items.append((path, "mesh", p.GetName()))
    except Exception:
        pass
    return items


def match_pairs(geo_items, material_names, cfg=None):
    """Match geometry to built materials.
    Levels:
      - Single material: assign it to every geometry item, ignoring names,
        EXCEPT slots that match a preset (glass, metall, ...) - those are left
        unmatched so the preset pass can claim them.
      - Several materials: match by name - exact (case-insensitive) ->
        normalised fuzzy -> prefix containment.
    Returns (pairs, unmatched_geo, unused_materials)."""

    def _has_preset(name):
        if cfg is None:
            return False
        slot = _material_name_from_subset(name)
        pname, _ = cfg.match_preset(slot)
        return bool(pname)

    # --- single-material fast path ---------------------------------------
    if len(material_names) == 1:
        only = material_names[0]
        pairs, unmatched = [], []
        for path, gtype, name in geo_items:
            candidate = _material_name_from_subset(name)
            # leave preset-matching slots for the preset pass
            if _has_preset(name):
                unmatched.append(name)
                continue
            # skip clearly non-geometry garbage, but otherwise bind everything
            if _is_garbage_name(candidate) and gtype != "subset":
                unmatched.append(name)
                continue
            pairs.append((path, only))
        unused = [] if pairs else [only]
        return pairs, unmatched, unused

    # --- multi-material name matching ------------------------------------
    norm_to_mat = {}
    for m in material_names:
        norm_to_mat.setdefault(_norm(m), m)

    def find_mat(name):
        n = _norm(name)
        if not n:
            return None
        if n in norm_to_mat:                      # exact / case-insensitive
            return norm_to_mat[n]
        best, best_len = None, 0                  # containment either way
        for mnorm, mname in norm_to_mat.items():
            if not mnorm:
                continue
            if mnorm.startswith(n) or n.startswith(mnorm):
                ov = min(len(mnorm), len(n))
                if ov > best_len:
                    best_len, best = ov, mname
        return best

    pairs = []
    unmatched = []
    used = set()
    for path, gtype, name in geo_items:
        # Recover the real material name from attribute-partitioned subsets
        # (shop_materialpath_body -> body) before any matching.
        candidate = _material_name_from_subset(name)
        mat = None
        if not _is_garbage_name(candidate):
            mat = find_mat(candidate)
        if mat:
            pairs.append((path, mat))
            used.add(mat)
        else:
            unmatched.append(name)

    unused = [m for m in material_names if m not in used]
    return pairs, unmatched, unused


def _resolve_material_paths(matlib, material_names):
    """Return {material_name: real_usd_path} by reading the materiallibrary's
    composed stage. The library's Materials Path Prefix parm can be anything
    (/materials/, /ASSET/mtl/, ...), so we never assume '/materials/'. We find
    each UsdShade Material prim and map it back to a built material name.
    Falls back to '<prefix><name>' from the parm if a prim can't be found."""
    resolved = {}

    # 1. read the actual prefix off the node (best-effort; parm name varies)
    prefix = "/materials/"
    for pn in ("matpathprefix", "materials_path_prefix", "matlibprefix"):
        p = matlib.parm(pn)
        if p is not None:
            try:
                val = p.evalAsString()
                if val:
                    prefix = val if val.endswith("/") else val + "/"
                break
            except Exception:
                pass

    # 2. walk the library's stage for real Material prims
    name_set = set(material_names)
    try:
        stage = matlib.stage()
        for prim in stage.Traverse():
            tname = prim.GetTypeName()
            if tname not in ("Material", "Shader"):
                continue
            leaf = prim.GetName()
            if leaf in name_set and tname == "Material":
                resolved[leaf] = str(prim.GetPath())
    except Exception:
        pass

    # 3. fill any gaps from the prefix + name
    for m in material_names:
        resolved.setdefault(m, prefix + m)
    return resolved


def _assign_materials(stage_node, matlib, pairs, material_paths, name_hint=""):
    if not pairs:
        return None
    assign = stage_node.createNode("assignmaterial")
    if name_hint:
        assign.setName(name_hint + "_assignmaterial", unique_name=True)
    assign.setInput(0, matlib)
    _set_parm(assign, ["nummaterials"], len(pairs))
    for i, (geo_path, mat_name) in enumerate(pairs, 1):
        mat_path = material_paths.get(mat_name, MATERIALS_PREFIX + mat_name)
        _set_parm(assign, ["primpattern%d" % i, "geopath%d" % i], geo_path)
        _set_parm(assign, ["matspecpath%d" % i, "materialpath%d" % i,
                           "matpath%d" % i], mat_path)
    try:
        mp = matlib.position()
        assign.setPosition(hou.Vector2(mp.x(), mp.y() - 1.0))
    except Exception:
        pass
    assign.setDisplayFlag(True)
    assign.setSelected(True, clear_all_selected=True)
    return assign


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def _sanitize_node_name(name):
    """Make a string safe for a Houdini node name: keep alnum and underscore,
    collapse the rest to underscore, trim, ensure it doesn't start with a
    digit."""
    import re as _re
    safe = _re.sub(r"[^0-9A-Za-z_]", "_", name).strip("_")
    safe = _re.sub(r"_+", "_", safe)
    if not safe:
        return "prop"
    if safe[0].isdigit():
        safe = "prop_" + safe
    return safe


def _prop_name_from_stage(anchor):
    """Derive a prop name from the anchor's composed stage: the first
    meaningful Mesh/Xform prim, preferring a named asset root over a bare
    top-level group. Returns None if nothing suitable is found."""
    try:
        stage = anchor.stage()
    except Exception:
        return None
    if stage is None:
        return None

    # collect candidate prims: Xform/Mesh, skip /materials, /lights, /Render...
    skip_roots = ("materials", "lights", "Render", "cameras")
    best = None
    try:
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            parts = [p for p in path.split("/") if p]
            if not parts or parts[0] in skip_roots:
                continue
            tname = prim.GetTypeName()
            if tname not in ("Mesh", "Xform"):
                continue
            # prefer the deepest-but-still-asset-level name: index 1 if present
            # (/top/asset/...), else the top prim.
            cand = parts[1] if len(parts) >= 2 else parts[0]
            if cand and not _is_garbage_name(cand):
                best = cand
                break
    except Exception:
        return None
    return best


def build(anchor_path, textures_folder, scope_path="", assign=True,
          config_path=None, prop_name=None, add_controls=False):
    """Build materials for one prop.

    anchor_path     : LOP node in /stage to chain matlib/assign below
                      (typically the SOP Import feeding the prop).
    textures_folder : flat folder holding this prop's textures.
    scope_path      : optional prim path to restrict geometry matching to a
                      single prop when several live under one node ('' = all).
    prop_name       : optional name for the created nodes (e.g. the prop's
                      mesh name). Falls back to the textures folder name.
    Returns a stats dict for the UI.
    """
    cfg, cfg_warn = _config.load_config(config_path)
    if cfg is None:
        return {"error": cfg_warn or "Could not load channel map."}

    folder = hou.text.expandString(textures_folder).rstrip("/\\")
    if not os.path.isdir(folder):
        return {"error": "Not a folder: %s" % folder}

    anchor = hou.node(anchor_path) if anchor_path else None
    if anchor is None or anchor.parent() is None or \
            anchor.parent().path() != "/stage":
        return {"error": "Anchor must be a node in /stage "
                         "(select the prop's SOP Import / Reference node)."}

    materials, unrecognised = scan_textures(folder, cfg)
    if not materials:
        return {"error": "No recognisable textures in folder.",
                "unrecognised": unrecognised}

    stage = hou.node("/stage")

    # If no prop name was supplied, derive one from the anchor's stage: the
    # first meaningful top-level prim (the asset root), not '/materials' etc.
    if not prop_name:
        prop_name = _prop_name_from_stage(anchor)

    matlib = stage.createNode("materiallibrary")
    # Name nodes after the prop when given, else the textures folder.
    raw_hint = prop_name or os.path.basename(folder.rstrip("/\\")) or "prop"
    prop_hint = _sanitize_node_name(raw_hint)
    matlib.setName(prop_hint + "_materials", unique_name=True)

    # Splice matlib into the stream directly below the anchor: capture the
    # anchor's existing consumers first so we can reconnect them below assign.
    anchor_outputs = []
    try:
        for conn in anchor.outputConnections():
            anchor_outputs.append((conn.outputNode(), conn.inputIndex()))
    except Exception:
        pass

    try:
        matlib.setInput(0, anchor)
        ap = anchor.position()
        matlib.setPosition(hou.Vector2(ap.x(), ap.y() - 1.0))
    except Exception:
        pass

    created = []
    for mat_name in sorted(materials.keys()):
        _build_material(matlib, mat_name, materials[mat_name], cfg,
                        add_controls=add_controls)
        created.append(mat_name)

    matlib.layoutChildren()
    matlib.setDisplayFlag(True)

    assigned = 0
    unmatched, unused = [], []
    material_paths = {}
    assign_node = None
    preset_created = []
    if assign and created:
        # Force the materiallibrary to cook so its Material prims exist on the
        # stage before we read their real paths and match geometry.
        try:
            matlib.cook(force=True)
        except Exception:
            pass

        lib_stage = matlib.stage()
        geo_items = collect_geo(lib_stage, scope_path)
        pairs, unmatched, unused = match_pairs(geo_items, created, cfg)

        # --- presets: for geometry that got no textured material but whose
        #     slot name matches a preset (glass, metall, ...), build a default
        #     material and bind it. Textures always win (these are only the
        #     UNMATCHED slots).
        preset_pairs = []
        preset_mat_for = {}   # preset_name -> created material node name
        matched_paths = {p for p, _ in pairs}
        for path, gtype, name in geo_items:
            if path in matched_paths:
                continue
            slot = _material_name_from_subset(name)
            pname, params = cfg.match_preset(slot)
            if not pname:
                continue
            # build the preset material once, reuse for all matching slots
            if pname not in preset_mat_for:
                _build_preset_material(matlib, pname, params)
                preset_mat_for[pname] = pname
                preset_created.append(pname)
            preset_pairs.append((path, pname))

        if preset_created:
            matlib.layoutChildren()
            try:
                matlib.cook(force=True)
            except Exception:
                pass

        all_created = created + preset_created
        all_pairs = pairs + preset_pairs
        material_paths = _resolve_material_paths(matlib, all_created)
        assign_node = _assign_materials(stage, matlib, all_pairs,
                                        material_paths, prop_hint)
        assigned = len(all_pairs)

        # recompute unmatched after presets
        bound = {p for p, _ in all_pairs}
        unmatched = [n for (p, g, n) in geo_items if p not in bound]

    # Splice into the stream: whatever used to read from the anchor now reads
    # from the tail of our new chain (assign if present, else matlib). This
    # keeps the graph a single line instead of a dangling side branch.
    tail = assign_node or matlib
    if tail is not None and anchor_outputs:
        for out_node, in_idx in anchor_outputs:
            try:
                out_node.setInput(in_idx, tail)
            except Exception:
                pass

    return {
        "created": created,
        "preset_created": preset_created,
        "assigned": assigned,
        "unmatched": sorted(set(unmatched)),
        "unused_materials": unused,
        "unrecognised": unrecognised,
        "matlib": matlib.path(),
        "material_paths": material_paths,
        "config_warning": cfg_warn,
    }
