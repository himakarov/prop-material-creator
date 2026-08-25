"""
config.py - loads and validates channel_map.json for Prop Material Creator.

The channel map is the single place project-specific naming lives. Editing it
(adding a suffix alias, changing a colorspace) never requires touching code.

Public surface:
    load_config(path=None) -> Config
    Config.match_suffix(token) -> channel_name | None
    Config.channel(name)       -> dict (aliases, colorspace, mtlx_input, ...)
    Config.texture_exts        -> tuple of lowercase extensions
"""

import os
import json

# channel_map.json lives in the package's config/ folder, a sibling of
# python/. From this file (…/python/prop_material_creator/config.py) that is
# three levels up, then into config/.
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_JSON = os.path.join(_PKG_ROOT, "config", "channel_map.json")

# Fallback to a copy next to this module, if one exists (keeps the tool working
# even if the config folder is moved).
if not os.path.isfile(_DEFAULT_JSON):
    _local = os.path.join(os.path.dirname(__file__), "channel_map.json")
    if os.path.isfile(_local):
        _DEFAULT_JSON = _local


class Config(object):
    def __init__(self, data):
        self._data = data
        self.channels = data.get("channels", {})
        self.texture_exts = tuple(
            e.lower() for e in data.get(
                "texture_exts",
                [".png", ".tif", ".tiff", ".exr", ".jpg", ".jpeg", ".tga"],
            )
        )
        parsing = data.get("parsing", {})
        self.separators = parsing.get("separators", ["_", "."])
        self.case_sensitive = bool(parsing.get("case_sensitive", False))

        # alias -> priority for resolving two maps that feed the same channel
        # (basecolor beats diffuse). Unlisted aliases default to 0.
        self._alias_priority = {}
        for k, v in data.get("alias_priority", {}).items():
            if k.startswith("_"):
                continue
            key = k if self.case_sensitive else k.lower()
            try:
                self._alias_priority[key] = int(v)
            except (TypeError, ValueError):
                pass

        # Build a flat alias -> channel_name lookup once, longest-alias-first so
        # 'basecolor' wins over 'bc' when both could match a token tail.
        self._alias_lookup = {}
        for ch_name, ch in self.channels.items():
            for alias in ch.get("aliases", []):
                key = alias if self.case_sensitive else alias.lower()
                # keep the longer alias if two channels ever collide on a key
                prev = self._alias_lookup.get(key)
                if prev is None:
                    self._alias_lookup[key] = ch_name
        self._aliases_sorted = sorted(self._alias_lookup.keys(),
                                      key=len, reverse=True)
        # material presets for untextured slots (glass, metal, ...)
        self.material_presets = {}
        for name, spec in data.get("material_presets", {}).items():
            if name.startswith("_"):
                continue
            self.material_presets[name] = spec
        # flat alias -> preset_name lookup, longest-first
        self._preset_lookup = {}
        for pname, spec in self.material_presets.items():
            for alias in spec.get("match", []):
                key = alias if self.case_sensitive else alias.lower()
                self._preset_lookup.setdefault(key, pname)
        self._preset_aliases_sorted = sorted(self._preset_lookup.keys(),
                                             key=len, reverse=True)

    def match_preset(self, slot_name):
        """Return (preset_name, params) for a slot name that matches a preset,
        or (None, None). Matches the whole slot name or the tail token after a
        separator: 'glass' or 'lens_glass' -> glass preset."""
        if not slot_name:
            return None, None
        low = slot_name if self.case_sensitive else slot_name.lower()
        # exact whole-name match first
        pname = self._preset_lookup.get(low)
        if pname:
            return pname, self.material_presets[pname].get("params", {})
        # tail-token match (longest alias first)
        for alias in self._preset_aliases_sorted:
            for sep in self.separators:
                if low.endswith(sep + alias) or low == alias:
                    pname = self._preset_lookup[alias]
                    return pname, self.material_presets[pname].get("params", {})
        return None, None

    def alias_priority(self, alias):
        """Priority of a matched alias (higher wins on same-channel conflict)."""
        if alias is None:
            return 0
        key = alias if self.case_sensitive else alias.lower()
        return self._alias_priority.get(key, 0)

    def match_suffix(self, token):
        """Return the channel name for a bare suffix token, or None.
        'dif' -> 'base_color', 'bump' -> 'bump'."""
        if token is None:
            return None
        key = token if self.case_sensitive else token.lower()
        return self._alias_lookup.get(key)

    def channel(self, name):
        return self.channels.get(name, {})

    def all_alias_keys(self):
        """All alias keys, longest first. Used to peel a channel suffix off a
        filename stem when the separator split is ambiguous."""
        return list(self._aliases_sorted)


def load_config(path=None):
    """Load channel_map.json. Falls back to the bundled default on any error,
    so the tool never hard-crashes on a malformed user edit; the caller can
    surface a warning if desired."""
    target = path or _DEFAULT_JSON
    try:
        with open(target, "r") as f:
            data = json.load(f)
        return Config(data), None
    except Exception as exc:
        # fall back to bundled default if the user file is broken
        if target != _DEFAULT_JSON:
            try:
                with open(_DEFAULT_JSON, "r") as f:
                    data = json.load(f)
                return Config(data), "Using bundled default (%s failed: %s)" % (
                    os.path.basename(target), exc)
            except Exception:
                pass
        return None, "Failed to load channel map: %s" % exc
