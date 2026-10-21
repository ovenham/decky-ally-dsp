"""Read-only probes: codec, DMI, PipeWire graph, TAS2781 controls, LV2 plugins."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from . import devices, paths
from .constants import CALF_SATURATOR_URI, INPUT_NODE, LSP_URIS
from .util import run, which

REALTEK = "10ec"


def parse_codec_header(head: str) -> Optional[Dict[str, str]]:
    codec = re.search(r"^Codec:\s*(.+)$", head, re.M)
    vendor = re.search(r"^Vendor Id:\s*0x([0-9a-fA-F]{8})", head, re.M)
    subsys = re.search(r"^Subsystem Id:\s*0x([0-9a-fA-F]{8})", head, re.M)
    if not (codec and vendor and subsys):
        return None
    return {"codec": codec.group(1).strip(), "vendor_id": vendor.group(1).lower(), "ssid": subsys.group(1).lower()}


def _codec_files() -> List[str]:
    out: List[str] = []
    base = "/proc/asound"
    try:
        cards = [c for c in os.listdir(base) if re.fullmatch(r"card\d+", c)]
    except OSError:
        return out
    for c in sorted(cards, key=lambda x: int(x[4:])):
        d = os.path.join(base, c)
        try:
            out += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.startswith("codec#")]
        except OSError:
            continue
    return out


def codec_info() -> Optional[Dict[str, Any]]:
    """Return the speaker codec: the Realtek HDA codec, else the SoundWire devices (ROG Xbox Ally X20)."""
    return hda_codec_info() or soundwire_codec_info()


def hda_codec_info() -> Optional[Dict[str, Any]]:
    """Return the Realtek HDA codec (vendor 0x10ec) with its subsystem id."""
    for path in _codec_files():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(4096)
        except OSError:
            continue
        parsed = parse_codec_header(head)
        if not parsed or not parsed["vendor_id"].startswith(REALTEK):
            continue
        vid = parsed["vendor_id"]
        codec_name = parsed["codec"]
        card_dir = os.path.dirname(path)
        card = int(re.search(r"card(\d+)", card_dir).group(1))
        try:
            with open(os.path.join(card_dir, "id"), "r", encoding="utf-8") as f:
                card_id = f.read().strip()
        except OSError:
            card_id = str(card)
        ssid = devices.normalize_ssid(parsed["ssid"])
        dev = devices.lookup(ssid)
        return {
            "bus": "hda",
            "card": card,
            "card_id": card_id,
            "codec": codec_name,
            "vendor_id": vid,
            "dev": vid[4:],
            "ssid": ssid,
            "supported": dev is not None,
            "model": dev.get("name") if dev else None,
        }
    return None


SDW_BUS = "/sys/bus/soundwire/devices"
PCI_BUS = "/sys/bus/pci/devices"
SDW_DEVICE_RE = re.compile(r"sdw:\d+:\d+:([0-9a-fA-F]{4}):([0-9a-fA-F]{4}):\d+")
# Multimedia audio (0x0401), HD audio (0x0403) and other multimedia (0x0480, the AMD ACP).
AUDIO_PCI_CLASSES = ("0x0401", "0x0403", "0x0480")
SDW_PART_NAMES = {("0102", "2783"): "TI TAS2783", ("025d", "0721"): "Realtek RT721"}


def soundwire_ids(bus: str = SDW_BUS) -> List[Dict[str, str]]:
    """SoundWire peripherals as {"man", "part"} lowercase hex, deduplicated, in bus order."""
    out: List[Dict[str, str]] = []
    try:
        names = sorted(os.listdir(bus))
    except OSError:
        return out
    for name in names:
        m = SDW_DEVICE_RE.fullmatch(name)
        if not m:
            continue
        ids = {"man": m.group(1).lower(), "part": m.group(2).lower()}
        if ids not in out:
            out.append(ids)
    return out


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def sdw_subsys_token(subsystem_vendor: str, subsystem_device: str) -> str:
    """The SUBSYS token in Dolby's SoundWire tuning names: device then vendor (0x1043, 0x1f2c -> 1f2c1043)."""
    vendor = subsystem_vendor.lower().removeprefix("0x").zfill(4)
    device = subsystem_device.lower().removeprefix("0x").zfill(4)
    return device + vendor


def pci_audio_subsystem(base: str = PCI_BUS) -> Optional[Dict[str, str]]:
    """PCI subsystem ids of the AMD audio device that owns the SoundWire bus (bound to an snd_ driver)."""
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None
    for name in names:
        d = os.path.join(base, name)
        if not _read(os.path.join(d, "class")).startswith(AUDIO_PCI_CLASSES):
            continue
        if _read(os.path.join(d, "vendor")).lower() != "0x1022":
            continue
        driver = os.path.basename(os.path.realpath(os.path.join(d, "driver")))
        vendor, device = _read(os.path.join(d, "subsystem_vendor")), _read(os.path.join(d, "subsystem_device"))
        if vendor and device and driver.startswith("snd_"):
            return {"pci": name, "subsystem_vendor": vendor.lower(), "subsystem_device": device.lower()}
    return None


def _soundwire_card(cards_path: str = "/proc/asound/cards") -> Dict[str, Any]:
    """The ALSA card the SoundWire machine driver registers (an id like amdsoundwire)."""
    for line in _read(cards_path).splitlines():
        m = re.match(r"\s*(\d+)\s+\[(\S+)\s*\]", line)
        if m and ("sdw" in m.group(2).lower() or "soundwire" in m.group(2).lower()):
            return {"card": int(m.group(1)), "card_id": m.group(2)}
    return {"card": None, "card_id": None}


def soundwire_codec_info(bus: str = SDW_BUS, pci_base: str = PCI_BUS,
                         cards_path: str = "/proc/asound/cards") -> Optional[Dict[str, Any]]:
    """SoundWire audio (ROG Xbox Ally X20): the peripherals plus the audio device's PCI subsystem.

    Dolby names these tunings SOUNDWIRE_[SDCAFUNCTION_NN_]MAN_<man>_FUNC_<part>_SUBSYS_<device><vendor>.xml,
    so a SoundWire device's registry key is that SUBSYS token."""
    ids = soundwire_ids(bus)
    pci = pci_audio_subsystem(pci_base)
    if not ids or not pci:
        return None
    ssid = sdw_subsys_token(pci["subsystem_vendor"], pci["subsystem_device"])
    dev = devices.lookup(ssid)
    names = [SDW_PART_NAMES.get((i["man"], i["part"]), f"{i['man']}:{i['part']}") for i in ids]
    return {
        "bus": "soundwire",
        **_soundwire_card(cards_path),
        "codec": "SoundWire " + ", ".join(names),
        "vendor_id": None,
        "dev": None,
        "sdw": ids,
        "pci": pci["pci"],
        "ssid": ssid,
        "supported": dev is not None,
        "model": dev.get("name") if dev else None,
    }


def dmi() -> Dict[str, str]:
    out = {}
    for key in ("sys_vendor", "product_name", "board_name", "bios_version"):
        try:
            with open(f"/sys/devices/virtual/dmi/id/{key}", "r", encoding="utf-8") as f:
                out[key] = f.read().strip()
        except OSError:
            out[key] = ""
    return out


def kernel() -> str:
    try:
        return os.uname().release
    except Exception:
        return ""


def pw_dump() -> List[Dict[str, Any]]:
    r = run(["pw-dump"], timeout=15)
    if not r.ok:
        return []
    try:
        data = json.loads(r.out)
        return data if isinstance(data, list) else []
    except ValueError:
        return []


def _props(obj: Dict[str, Any]) -> Dict[str, Any]:
    return obj.get("info", {}).get("props", {}) or {}


def _sink(obj: Dict[str, Any]) -> Dict[str, Any]:
    p = _props(obj)
    return {"id": obj.get("id"), "name": str(p.get("node.name", "")), "description": p.get("node.description", ""),
            "card_name": p.get("alsa.card_name", "")}


def find_speaker_sink(dump: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Internal speaker sink: the HDA analog sink shared with the 3.5 mm jack, else a UCM speaker sink.
    SoundWire devices give speakers and headphones separate sinks, e.g. ...HiFi__Speaker__sink."""
    sinks = [o for o in dump if _props(o).get("media.class") == "Audio/Sink"]
    for obj in sinks:
        name = str(_props(obj).get("node.name", ""))
        if name.startswith("alsa_output.pci-") and name.endswith("analog-stereo"):
            return _sink(obj)
    for obj in sinks:
        name = str(_props(obj).get("node.name", ""))
        if name.startswith("alsa_output.") and "__speaker__" in name.lower():
            return _sink(obj)
    return None


def output_route(dump: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Active output route of the internal analog card: speaker or headphones."""
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Device":
            continue
        p = _props(obj)
        if p.get("device.api") != "alsa" or not str(p.get("device.name", "")).startswith("alsa_card.pci-"):
            continue
        params = obj.get("info", {}).get("params", {}) or {}
        enum_names = [r.get("name", "") for r in params.get("EnumRoute", []) or []]
        if not any("analog-output" in n for n in enum_names):
            continue
        for r in params.get("Route", []) or []:
            if r.get("direction") == "Output":
                return {"name": r.get("name", ""), "description": r.get("description", ""),
                        "available": r.get("available", "unknown"), "device": p.get("device.name", "")}
    return None


def headphones_active(route: Optional[Dict[str, Any]]) -> bool:
    return bool(route) and "headphone" in str(route.get("name", "")).lower()


def filter_node_present(dump: List[Dict[str, Any]], node_name: str = INPUT_NODE) -> bool:
    return any(_props(o).get("node.name") == node_name for o in dump)


def filter_links(dump: List[Dict[str, Any]]) -> Dict[str, int]:
    """Link counts on the chain's input and output nodes."""
    ids = {o.get("id"): _props(o).get("node.name") for o in dump if _props(o).get("node.name", "").startswith("effect_")}
    counts = {"input": 0, "output": 0}
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Link":
            continue
        info = obj.get("info", {})
        if ids.get(info.get("input-node-id")) == INPUT_NODE:
            counts["input"] += 1
        if ids.get(info.get("output-node-id")) == INPUT_NODE.replace("effect_input", "effect_output"):
            counts["output"] += 1
    return counts


def tas_controls(card: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"bound": False, "controls": {}}
    r = run(["amixer", "-c", str(card), "controls"], timeout=10)
    if not r.ok:
        return out
    names = re.findall(r"name='(Speaker [^']+)'", r.out)
    out["bound"] = any(n in ("Speaker Program Id", "Speaker Config Id") for n in names)
    for n in ("Speaker Program Id", "Speaker Config Id", "Speaker Profile Id", "Speaker Analog Gain",
              "Speaker Force Firmware Load"):
        if n in names:
            c = run(["amixer", "-c", str(card), "cget", f"iface=CARD,name={n}"], timeout=10)
            m = re.search(r": values=([^\n]+)", c.out)
            out["controls"][n] = m.group(1).strip() if m else "?"
    return out


def lv2_check(lv2_dir: str = paths.LV2_DIR) -> Dict[str, Any]:
    env_extra = {"LV2_PATH": f"{lv2_dir}:/usr/lib/lv2"}
    r = run(["lv2ls"], timeout=30, env=_with(env_extra))
    present = set(r.out.split()) if r.ok else set()
    missing = [u for u in LSP_URIS if u not in present]
    return {"ok": not missing and r.ok, "missing": missing, "lv2ls_rc": r.rc, "lv2_dir": lv2_dir,
            "bundle_present": os.path.isdir(os.path.join(lv2_dir, "lsp-plugins.lv2")),
            "calf": CALF_SATURATOR_URI in present}


def _with(extra: Dict[str, str]) -> Dict[str, str]:
    from .util import user_env
    return user_env(extra)


def tools() -> Dict[str, Optional[str]]:
    return {t: which(t) for t in ("pw-dump", "pw-cli", "wpctl", "systemctl", "journalctl", "7z", "curl",
                                  "lv2ls", "lv2info", "amixer", "pipewire")}


def summary() -> Dict[str, Any]:
    dump = pw_dump()
    codec = codec_info()
    sink = find_speaker_sink(dump)
    route = output_route(dump)
    return {
        "codec": codec,
        "dmi": dmi(),
        "kernel": kernel(),
        "sink": sink,
        "route": route,
        "headphones": headphones_active(route),
        "filter_present": filter_node_present(dump),
        "tools": tools(),
        "system_python": paths.SYSTEM_PYTHON if os.path.exists(paths.SYSTEM_PYTHON) else None,
    }
