"""Diagnostics report for the UI and bug reports."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from . import asus_fetch, convert, dsp_runtime, hardware, paths, settings
from .util import read_json, run


def plugin_version() -> str:
    v = os.environ.get("DECKY_PLUGIN_VERSION")
    if v:
        return v
    pkg = read_json(os.path.join(paths.PLUGIN_DIR, "package.json"), {}) or {}
    return str(pkg.get("version", "dev"))


def os_release() -> Dict[str, str]:
    out = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r'^(NAME|VERSION_ID|BUILD_ID|VARIANT_ID)=(.*)$', line.strip())
                if m:
                    out[m.group(1)] = m.group(2).strip('"')
    except OSError:
        pass
    return out


def tool_version(cmd, timeout=10) -> str:
    r = run(cmd, timeout=timeout)
    text = (r.out or r.err).strip().splitlines()
    return text[-1][:80] if text else f"rc={r.rc}"


def collect() -> Dict[str, Any]:
    hw = hardware.summary()
    codec = hw.get("codec") or {}
    st = settings.load()
    st_public = dict(st)
    st_public["perApp"] = {k: v for k, v in (st.get("perApp") or {}).items()}
    return {
        "plugin_version": plugin_version(),
        "os": os_release(),
        "kernel": hw.get("kernel"),
        "dmi": hw.get("dmi"),
        "codec": codec,
        "tas": hardware.tas_controls(codec["card"]) if codec and codec.get("card") is not None else {},
        "sink": hw.get("sink"),
        "route": hw.get("route"),
        "pipewire": tool_version(["pipewire", "--version"]),
        "wireplumber": tool_version(["wireplumber", "--version"]),
        "lv2": hardware.lv2_check(),
        "tools": hw.get("tools"),
        "dsp": dsp_runtime.status(with_journal=True),
        "venv": convert.venv_meta(),
        "converter_present": convert.converter_ok(),
        "presets": convert.list_presets(),
        "provenance": asus_fetch.provenance(),
        "settings": st_public,
        "paths": {"plugin": paths.PLUGIN_DIR, "runtime": paths.RUNTIME_DIR, "settings": paths.SETTINGS_DIR,
                  "unit": paths.UNIT_PATH},
    }


def render_text(d: Dict[str, Any]) -> str:
    lines = [f"Ally DSP {d.get('plugin_version')} diagnostics", ""]
    osr = d.get("os") or {}
    lines.append(f"OS: {osr.get('NAME', '?')} {osr.get('VERSION_ID', '?')} (build {osr.get('BUILD_ID', '?')}), kernel {d.get('kernel')}")
    dmi = d.get("dmi") or {}
    lines.append(f"Device: {dmi.get('sys_vendor')} {dmi.get('product_name')} (BIOS {dmi.get('bios_version')})")
    c = d.get("codec") or {}
    lines.append(f"Codec: {c.get('codec')} vendor={c.get('vendor_id')} ssid={c.get('ssid')} supported={c.get('supported')} ({c.get('model')})")
    tas = d.get("tas") or {}
    lines.append(f"TAS2781 driver bound: {tas.get('bound')} controls={json.dumps(tas.get('controls'))}")
    lines.append(f"Sink: {(d.get('sink') or {}).get('name')}  route: {json.dumps(d.get('route'))}")
    lines.append(f"PipeWire: {d.get('pipewire')}  WirePlumber: {d.get('wireplumber')}")
    lv2 = d.get("lv2") or {}
    lines.append(f"LV2 bundle present: {lv2.get('bundle_present')} ok={lv2.get('ok')} missing={lv2.get('missing')}")
    dsp = d.get("dsp") or {}
    lines.append(f"DSP unit: installed={dsp.get('unit_installed')} enabled={dsp.get('enabled')} active={dsp.get('active')} "
                 f"node_visible={dsp.get('verified')} links={json.dumps(dsp.get('links'))}")
    ap = (dsp.get("active_preset") or {})
    lines.append(f"Active preset: {ap.get('profile')}/{ap.get('voicing')} preGainDb={ap.get('preGainDb')} applied={ap.get('applied_at')}")
    lines.append(f"venv: {json.dumps(d.get('venv'))}")
    lines.append(f"converter present: {d.get('converter_present')}")
    pres = d.get("presets") or {}
    ok = sum(1 for p in pres.values() for v in p.values() if v)
    lines.append(f"presets available: {ok}")
    prov = d.get("provenance") or {}
    lines.append(f"DAX3: {prov.get('xml_name')} sha256={str(prov.get('xml_sha256'))[:16]}… package={json.dumps((prov.get('package') or {}).get('version'))} method={prov.get('method')}")
    lines.append(f"settings: enabled={d['settings'].get('enabled')} global={json.dumps(d['settings'].get('global'))} "
                 f"extras={json.dumps(d['settings'].get('extras'))} perApp={len(d['settings'].get('perApp') or {})}")
    lines.append("")
    lines.append("journal (ally-dsp.service):")
    lines.append(dsp.get("journal") or "(empty)")
    return "\n".join(lines)
