"""CLI for testing and support; shares its on-disk state with the Decky plugin.
    python3 -m allydsp.cli doctor|setup|convert|apply|enable|disable|status|presets|update-check|update-verify|import-xml|unit-remove"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import asus_fetch, convert, diagnostics, dsp_runtime, hardware, paths, settings, setup_flow, updater
from .constants import PROFILE_IDS, VOICINGS


def _p(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _progress(ev: dict) -> None:
    print(f"[{ev['percent']:5.1f}%] {ev['step']:<9} {ev['status']:<8} {ev['message']}", flush=True)


def cmd_doctor(a):
    d = diagnostics.collect()
    print(json.dumps(d, indent=2, default=str) if a.json else diagnostics.render_text(d))


def cmd_setup(a):
    paths.ensure_dirs()
    res = setup_flow.run_setup(_progress, force=a.force, use_network=not a.offline,
                               allow_unsupported=a.allow_unsupported, activate=not a.no_activate)
    _p({k: res.get(k) for k in ("codec", "sink", "package", "results")})


def cmd_convert(a):
    paths.ensure_dirs()
    xml = asus_fetch.current_xml()
    if not xml:
        sys.exit("no tuning XML present, run setup first")
    sink = hardware.find_speaker_sink(hardware.pw_dump())
    if not sink:
        sys.exit("no speaker sink found")
    st = settings.load()
    profiles = a.profiles.split(",") if a.profiles else None
    res = convert.convert_all(xml, sink["name"], st["extras"], progress=lambda pct, msg: print(f"[{pct:5.1f}%] {msg}"),
                              profiles=profiles)
    _p(res)


def cmd_apply(a):
    if a.profile not in PROFILE_IDS or a.voicing not in VOICINGS:
        sys.exit(f"profile must be one of {PROFILE_IDS}, voicing one of {VOICINGS}")
    res = dsp_runtime.apply_preset(a.profile, a.voicing, a.pregain, restart_unit=not a.no_restart)
    if a.save:
        st = settings.load()
        st["global"] = {"profile": a.profile, "voicing": a.voicing}
        settings.save(st)
    _p(res)


def cmd_enable(a):
    dsp_runtime.ensure_unit()
    dsp_runtime.enable(True)
    ok = dsp_runtime.start()
    st = settings.load()
    st["enabled"] = True
    settings.save(st)
    _p({"started": ok, "verified": dsp_runtime.verify()})


def cmd_disable(a):
    ok = dsp_runtime.stop()
    dsp_runtime.enable(False)
    st = settings.load()
    st["enabled"] = False
    settings.save(st)
    _p({"stopped": ok})


def cmd_status(a):
    _p(dsp_runtime.status())


def cmd_presets(a):
    _p(convert.list_presets())


def cmd_update_check(a):
    st = settings.load()
    res = updater.check(st["update"], diagnostics.plugin_version(), force=True)
    settings.save(st)
    _p(res)


def cmd_update_verify(a):
    st = settings.load()
    latest = st["update"].get("latest") or updater.fetch_latest()
    _p(updater.verify_release(latest))


def cmd_import_xml(a):
    codec = hardware.codec_info()
    if not codec:
        sys.exit("no supported speaker codec found")
    _p(asus_fetch.import_xml(a.path, codec))


def cmd_unit_remove(a):
    dsp_runtime.remove_unit()
    _p({"removed": True})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="allydsp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("doctor"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("setup"); s.add_argument("--force", action="store_true"); s.add_argument("--offline", action="store_true")
    s.add_argument("--allow-unsupported", action="store_true"); s.add_argument("--no-activate", action="store_true"); s.set_defaults(fn=cmd_setup)
    s = sub.add_parser("convert"); s.add_argument("--profiles"); s.set_defaults(fn=cmd_convert)
    s = sub.add_parser("apply"); s.add_argument("profile"); s.add_argument("voicing"); s.add_argument("--pregain", type=float, default=0.0)
    s.add_argument("--no-restart", action="store_true"); s.add_argument("--save", action="store_true"); s.set_defaults(fn=cmd_apply)
    sub.add_parser("enable").set_defaults(fn=cmd_enable)
    sub.add_parser("disable").set_defaults(fn=cmd_disable)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("presets").set_defaults(fn=cmd_presets)
    sub.add_parser("update-check").set_defaults(fn=cmd_update_check)
    sub.add_parser("update-verify").set_defaults(fn=cmd_update_verify)
    s = sub.add_parser("import-xml"); s.add_argument("path"); s.set_defaults(fn=cmd_import_xml)
    sub.add_parser("unit-remove").set_defaults(fn=cmd_unit_remove)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except setup_flow.Cancelled:
        print("cancelled")
        return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
