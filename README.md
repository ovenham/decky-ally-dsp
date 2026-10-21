# Ally DSP

Decky Loader plugin that brings the Dolby speaker tuning of the ASUS ROG Ally
handhelds (ROG Xbox Ally X, ROG Xbox Ally, ROG Ally X) to SteamOS. On Windows the
built-in speakers are shaped by Dolby Atmos; on SteamOS they play untreated.
Ally DSP downloads the public ASUS Dolby driver package for the detected device,
extracts the tuning for the installed codec, converts it with
[speaker-tuning-to-easyeffects](https://github.com/antoinecellerier/speaker-tuning-to-easyeffects)
into a PipeWire filter chain and runs the chain as a WirePlumber smart filter in
front of the speaker sink. Steam keeps seeing the real speakers, the volume keys
keep working, headphones pause the chain.

## Features

- Setup wizard: hardware check, ASUS package download with SHA-256 verification,
  tuning extraction, converter venv, conversion of all profiles, activation.
- Presets Game, Dynamic, Movie, Music and Voice, each with the Dolby voicings
  Balanced, Detailed and Warm.
- Global preset or per-game preset, switched with the running app.
- Extras: Dolby volume leveler (on by default), dialog enhancer, regulator, pre-gain.
- Headphone detection on the shared 3.5 mm jack pauses the chain.
- Diagnostics page and text report.
- Signed updates from GitHub Releases, installed through Decky Loader.
- No root; nothing is written outside the home directory.

## Supported hardware

| Device | Codec subsystem | Status |
|---|---|---|
| ROG Xbox Ally X (RC73XA) | 1043:1384 | developed and tested on SteamOS 3.8.16 |
| ROG Xbox Ally (RC73YA) | 1043:1394 | tuning is in the same ASUS package, untested |
| ROG Ally X (2024, RC72LA) | 1043:1EB3 | tested on SteamOS 3.8.28 by a contributor |
| ROG Xbox Ally X20 (RC74XA) | 1043:1954 (SoundWire) | extraction and conversion checked off-device; needs working speakers first ([X20 speaker fix](https://github.com/ovenham/rog-ally-x20-steamos-speaker-qam-fix)) |

Each device has its own entry in `defaults/fallback-sources.json`: the ASUS
support API query and a pinned package (URL, SHA-256, size). The RC72LA uses an
older ASUS package (V9.816.706.24) because the Xbox Ally package has no tuning
for its codec. To add a device, add its lowercase codec subsystem id to that file.

SoundWire devices such as the X20 have no HDA codec. The plugin reads the
SoundWire peripherals from `/sys/bus/soundwire/devices` and the audio device's
PCI subsystem, and keys the device by the `SUBSYS_` token of Dolby's
`SOUNDWIRE_..._MAN_<man>_FUNC_<nnnn>_SUBSYS_<device><vendor>.xml` tuning name
(`19541043` for the X20). It targets the UCM speaker sink (`...HiFi__Speaker__sink`);
headphones have their own sink there, so the chain never sits in front of them.

Requirements: SteamOS 3.8 or newer, Decky Loader, internet access during setup
(10 MB ASUS package plus about 220 MB numpy/scipy for the converter).

## Install

With Decky Loader installed, open Konsole in Desktop Mode:

```bash
curl -sL https://github.com/bassobr/decky-ally-dsp/raw/main/install.sh -o /tmp/ally-dsp-install.sh && sudo bash /tmp/ally-dsp-install.sh
```

Then open the Quick Access menu → Decky → Ally DSP → Setup. Updates are offered
in the plugin; `install.sh` can be re-run at any time.

## How it works

```
game → PipeWire → [Ally DSP: convolver → LSP PEQ → LSP multiband compressor → LSP autogain → LSP limiter] → speaker sink → ALC294 → 2× TAS2781 → speakers
```

The chain runs in its own `pipewire -c` process (`~/.config/systemd/user/ally-dsp.service`),
the pattern Valve uses for the Steam Deck microphone filter. The LSP LV2 plugins
are bundled in `bin/lv2` (LGPL-3, see `THIRD_PARTY_LICENSES.md`). A preset
switch restarts that process with another configuration. Details:
[docs/architecture.md](docs/architecture.md), background: [docs/research.md](docs/research.md).

## Command line

The backend doubles as a CLI for support (run as `deck`):

```bash
cd ~/homebrew/plugins/"Ally DSP"
PYTHONPATH=py_modules python3 -m allydsp.cli doctor
PYTHONPATH=py_modules python3 -m allydsp.cli setup
PYTHONPATH=py_modules python3 -m allydsp.cli apply movie warm --save
PYTHONPATH=py_modules python3 -m allydsp.cli status
```

## Development

```bash
pnpm install && pnpm build          # frontend
python3 -m pytest tests -q          # backend (Python 3.9+)
scripts/assemble-converter.sh       # copy converter from the submodule
scripts/fetch-lsp.sh                # bundle the LV2 plugins
scripts/dev-deploy.sh deck@<ip>     # copy to the handheld and restart Decky
```

Releases: tag `vX.Y.Z` matching `package.json`. GitHub Actions builds, tests,
packages `ally-dsp-X.Y.Z.zip`, signs `SHA256SUMS` with the `MINISIGN_SEED`
secret and publishes the release.

## License

MIT. Third-party components and why the Dolby tuning is never redistributed:
`THIRD_PARTY_LICENSES.md`.
