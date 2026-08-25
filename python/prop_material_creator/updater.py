"""
updater.py - self-update for Prop Material Creator.

Contract (same as the other CGA tools):
  * The local version is the plain text in the package's VERSION file.
  * The remote version is the tag of the latest GitHub *release*.
  * "Check for updates" compares the two; if the remote is newer it downloads
    the release's source zip and overwrites the local package files in place.
  * After an update the user restarts Houdini.

Everything is stdlib only (urllib) so there are no extra deps to install into
Houdini's Python. Network and parse failures degrade to a message, never an
exception that reaches the shelf.
"""

import os
import io
import re
import json
import shutil
import zipfile
import tempfile
import urllib.request
import urllib.error

# --- repo identity -----------------------------------------------------------
GITHUB_OWNER = "himakarov"
GITHUB_REPO = "prop-material-creator"
_API_LATEST = "https://api.github.com/repos/%s/%s/releases/latest" % (
    GITHUB_OWNER, GITHUB_REPO)
_RELEASES_PAGE = "https://github.com/%s/%s/releases/latest" % (
    GITHUB_OWNER, GITHUB_REPO)

# package root = .../PropMaterialCreator (two levels up from this file's dir:
# .../python/prop_material_creator/updater.py -> up to python -> up to root)
_PKG_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSION_FILE = os.path.join(_PKG_ROOT, "VERSION")

_TIMEOUT = 20  # seconds


# --- version helpers ---------------------------------------------------------
def local_version():
    """Read the local VERSION file. Returns a string like '1.2.2' or '0.0.0'."""
    try:
        with open(_VERSION_FILE, "r") as f:
            return f.read().strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def _parse(v):
    """'v1.2.10' -> (1, 2, 10). Non-numeric parts become 0. Extra parts kept."""
    v = (v or "").strip().lstrip("vV")
    parts = re.split(r"[.\-_]", v)
    out = []
    for p in parts:
        m = re.match(r"^(\d+)", p)
        out.append(int(m.group(1)) if m else 0)
    return tuple(out) or (0,)


def is_newer(remote, local):
    """True if remote version string is strictly newer than local."""
    return _parse(remote) > _parse(local)


# --- remote query ------------------------------------------------------------
def _http_json(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "PropMaterialCreator-updater",
    })
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def latest_release():
    """Return dict(tag, zip_url, notes) for the latest release, or raises."""
    data = _http_json(_API_LATEST)
    tag = data.get("tag_name") or data.get("name") or ""
    # Prefer an attached .zip asset; fall back to the auto source zipball.
    zip_url = None
    for asset in data.get("assets", []):
        name = (asset.get("name") or "").lower()
        if name.endswith(".zip"):
            zip_url = asset.get("browser_download_url")
            break
    if not zip_url:
        zip_url = data.get("zipball_url")
    return {
        "tag": tag,
        "zip_url": zip_url,
        "notes": data.get("body") or "",
    }


# --- download + apply --------------------------------------------------------
def _download(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "PropMaterialCreator-updater",
        "Accept": "application/octet-stream",
    })
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.read()


def _find_package_dir(root):
    """Inside the extracted zip, locate the folder that IS the package (the one
    containing a VERSION file and a python/ dir). Release zips are laid out
    flat (VERSION at top) OR nested one level (source zipballs), so search."""
    for dirpath, dirnames, filenames in os.walk(root):
        if "VERSION" in filenames and "python" in dirnames:
            return dirpath
    return None


# files/dirs at the package root we overwrite on update. Config is intentionally
# NOT wiped wholesale - user edits to channel_map.json are preserved (see below).
_MANAGED = ("python", "scripts", "VERSION", "CHANGELOG.md",
            "README.md", "README.en.md")


def apply_update(zip_bytes):
    """Extract the release zip and copy managed files over the live package.
    channel_map.json is only written if it does not already exist, so hand
    edits survive. Returns a short status string."""
    tmp = tempfile.mkdtemp(prefix="pmc_update_")
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmp)

        src = _find_package_dir(tmp)
        if src is None:
            return "Update failed: package layout not found in the release zip."

        # managed code/docs: overwrite
        for name in _MANAGED:
            s = os.path.join(src, name)
            d = os.path.join(_PKG_ROOT, name)
            if not os.path.exists(s):
                continue
            if os.path.isdir(s):
                if os.path.isdir(d):
                    shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)

        # config: add new files, but never clobber an existing channel_map.json
        src_cfg = os.path.join(src, "config")
        dst_cfg = os.path.join(_PKG_ROOT, "config")
        if os.path.isdir(src_cfg):
            if not os.path.isdir(dst_cfg):
                os.makedirs(dst_cfg)
            for fn in os.listdir(src_cfg):
                s = os.path.join(src_cfg, fn)
                d = os.path.join(dst_cfg, fn)
                if os.path.isdir(s):
                    if not os.path.isdir(d):
                        shutil.copytree(s, d)
                elif not os.path.exists(d):
                    shutil.copy2(s, d)

        return "ok"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- public surface ----------------------------------------------------------
def check(download_if_newer=True):
    """One-shot check used by the UI.

    Returns a dict:
      {"status": "up_to_date"|"updated"|"available"|"error",
       "local": "1.2.2", "remote": "1.3.0", "message": "..."}
    """
    loc = local_version()
    try:
        rel = latest_release()
    except urllib.error.URLError as e:
        return {"status": "error", "local": loc, "remote": None,
                "message": "Network error: %s" % e}
    except Exception as e:
        return {"status": "error", "local": loc, "remote": None,
                "message": "Could not read latest release: %s" % e}

    remote = rel.get("tag") or ""
    if not is_newer(remote, loc):
        return {"status": "up_to_date", "local": loc, "remote": remote,
                "message": "You're on the latest version (%s)." % loc}

    if not download_if_newer:
        return {"status": "available", "local": loc, "remote": remote,
                "message": "Version %s is available (you have %s)." % (
                    remote, loc)}

    if not rel.get("zip_url"):
        return {"status": "error", "local": loc, "remote": remote,
                "message": "Release %s has no downloadable zip." % remote}

    try:
        blob = _download(rel["zip_url"])
    except Exception as e:
        return {"status": "error", "local": loc, "remote": remote,
                "message": "Download failed: %s" % e}

    res = apply_update(blob)
    if res != "ok":
        return {"status": "error", "local": loc, "remote": remote,
                "message": res}

    return {"status": "updated", "local": loc, "remote": remote,
            "message": "Updated %s -> %s. Restart Houdini to load it." % (
                loc, remote)}


def changelog_text():
    """Return the local CHANGELOG.md contents for the 'Changelog' button."""
    path = os.path.join(_PKG_ROOT, "CHANGELOG.md")
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception as e:
        return "Could not read CHANGELOG.md: %s" % e


def releases_url():
    return _RELEASES_PAGE
