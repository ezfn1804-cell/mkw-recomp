"""Custom release selection, checksum-verified staging and preserved user data, using synthetic GitHub responses.

No real release or game is needed. Usage: uv run pytest tests/test_update.py
"""

import hashlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/prepare"))
import update  # noqa: E402


def package(extra=None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mkw-recomp/mkw.exe", b"synthetic new runtime")
        z.writestr("mkw-recomp/setup/src/prepare.py", b"synthetic setup")
        if extra:
            name, content = extra
            z.writestr(name, content)
    return out.getvalue()


def release(tag, *, draft=False, prerelease=False, body=b"", os_name="windows"):
    asset = {"name": f"mkw-recomp-{tag}{update.ASSET_SUFFIX[os_name]}", "size": len(body),
             "digest": "sha256:" + hashlib.sha256(body).hexdigest(), "browser_download_url": "https://example.test/package"}
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease, "assets": [asset]}


@pytest.mark.parametrize(("old", "new"), [
    ("v0.1.8-custom.1", "v0.1.8-custom.2"), ("0.1.8-custom.2", "0.1.8-custom.10"),
    ("0.1.8-custom.99", "0.1.8"), ("0.1.8", "0.1.9-custom.1"),
])
def test_versions_advance_numerically(old, new):
    assert update.version_key(new) > update.version_key(old)


def test_describe_suffix_and_invalid_versions():
    assert update.version_key("v0.1.8-custom.2-3-gabc123-dirty") == update.version_key("0.1.8-custom.2")
    for version in ("dev", "0.1.8-garbage", "0.1.8-custom.01", "0.1.8-custom.0", "0.1.8-rc.1"):
        assert update.version_key(version) is None


def mock_feed(monkeypatch, releases):
    calls = []

    def get(url, timeout):
        calls.append(url)
        assert url == f"https://api.github.com/repos/{update.REPO}/releases?per_page=100"
        return io.BytesIO(json.dumps(releases).encode())

    monkeypatch.setattr(update, "get", get)
    return calls


def test_custom_channel_selects_published_custom_release_not_draft(monkeypatch, capsys):
    monkeypatch.delenv("MKW_UPDATE_AS", raising=False)
    feed = [release("v0.1.8-custom.999", draft=True), release("v0.1.8-custom.2", prerelease=True),
            release("v0.1.8-custom.10", prerelease=True), release("v0.1.7")]
    mock_feed(monkeypatch, feed)
    update.check(SimpleNamespace(version="0.1.8-custom.1", os="windows"))
    assert capsys.readouterr().out.startswith("update v0.1.8-custom.10 ")


def test_stable_channel_does_not_offer_custom_or_other_prereleases(monkeypatch, capsys):
    monkeypatch.delenv("MKW_UPDATE_AS", raising=False)
    mock_feed(monkeypatch, [release("v0.1.9-custom.1"), release("v0.1.9", prerelease=True), release("v0.1.8")])
    update.check(SimpleNamespace(version="0.1.8", os="windows"))
    assert capsys.readouterr().out == "latest\n"


@pytest.mark.parametrize("feed", [[], [release("v0.1.8-custom.2", draft=True)],
                                [release("v0.1.8-custom.1", prerelease=True)]])
def test_no_update_does_not_reinstall_same_version(monkeypatch, capsys, feed):
    monkeypatch.delenv("MKW_UPDATE_AS", raising=False)
    mock_feed(monkeypatch, feed)
    update.check(SimpleNamespace(version="0.1.8-custom.1", os="windows"))
    assert capsys.readouterr().out == "latest\n"


def mock_download(monkeypatch, body, *, digest=None, draft=False):
    rel = release("v0.1.8-custom.2", body=body, prerelease=True, draft=draft)
    if digest is not None:
        rel["assets"][0]["digest"] = digest
    calls = []

    def get(url, timeout):
        calls.append(url)
        if url.endswith("/releases/tags/v0.1.8-custom.2"):
            return io.BytesIO(json.dumps(rel).encode())
        assert url == "https://example.test/package"
        return io.BytesIO(body)

    monkeypatch.setattr(update, "get", get)
    return calls


def test_fetch_stages_only_offered_release_and_preserves_installed_data(tmp_path, monkeypatch, capsys):
    game = tmp_path / "Port C ñ"
    game.mkdir()
    keep = ("mkw.exe", "mkwgame.dll", "mkw.ini", "setup-state.json", "romfs/resource", "profile/save", "spirv/cache.spv")
    for name in keep:
        p = game / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"original " + name.encode())
    before = {name: (game / name).read_bytes() for name in keep}
    calls = mock_download(monkeypatch, package())
    update.fetch(SimpleNamespace(tag="v0.1.8-custom.2", dest=game / "update", os="windows"))
    assert "ready " in capsys.readouterr().out
    assert (game / "update/new/mkw-recomp/mkw.exe").read_bytes() == b"synthetic new runtime"
    assert {name: (game / name).read_bytes() for name in keep} == before
    assert len(calls) == 2 and "/releases/tags/" in calls[0]  # another latest release cannot change the chosen tag


@pytest.mark.parametrize("digest", ["", "sha256:bad", "sha256:" + "0" * 64])
def test_bad_or_missing_digest_never_yields_installable_files(tmp_path, monkeypatch, digest):
    mock_download(monkeypatch, package(), digest=digest)
    with pytest.raises(ValueError):
        update.fetch(SimpleNamespace(tag="v0.1.8-custom.2", dest=tmp_path / "update", os="windows"))
    assert not (tmp_path / "update/new").exists()


def test_draft_is_not_downloaded(tmp_path, monkeypatch):
    calls = mock_download(monkeypatch, package(), draft=True)
    with pytest.raises(ValueError, match="not published"):
        update.fetch(SimpleNamespace(tag="v0.1.8-custom.2", dest=tmp_path, os="windows"))
    assert len(calls) == 1


@pytest.mark.parametrize("name", ["../outside", "mkw-recomp/../outside", "C:/outside", "mkw-recomp\\setup\\file",
                                "mkw-recomp/mkw.ini", "mkw-recomp/setup-state.json", "mkw-recomp/mkwgame.dll",
                                "mkw-recomp/romfs/resource", "mkw-recomp/profile/save", "mkw-recomp/spirv/cache.spv"])
def test_package_rejects_paths_that_could_overwrite_user_data(name):
    with zipfile.ZipFile(io.BytesIO(package((name, b"synthetic")))) as z:
        with pytest.raises(ValueError):
            update.validate_windows_package(z)


def test_package_rejects_links_and_case_collisions():
    for extra in ("link", "duplicate"):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("mkw-recomp/mkw.exe", b"synthetic")
            if extra == "link":
                info = zipfile.ZipInfo("mkw-recomp/setup/link")
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, "../../romfs")
            else:
                z.writestr("mkw-recomp/MKW.EXE", b"duplicate")
        with zipfile.ZipFile(out) as z, pytest.raises(ValueError):
            update.validate_windows_package(z)


def test_cleanup_keeps_user_backups(tmp_path, capsys):
    for name in ("mkwgame.dll.old", "save.old", "exefs.old"):
        (tmp_path / name).write_text("player backup")
    (tmp_path / "mkw.exe.old").write_text("old runtime")
    update.clean(SimpleNamespace(game=tmp_path))
    assert not (tmp_path / "mkw.exe.old").exists()
    assert all((tmp_path / n).read_text() == "player backup" for n in ("mkwgame.dll.old", "save.old", "exefs.old"))
