"""SoundWire speaker audio (ROG Xbox Ally X20): detection, tuning file lookup, speaker sink."""
import os

from allydsp import asus_fetch, hardware


def _sysfs(tmp_path, ids=(("0102", "2783"), ("0102", "2783"), ("025d", "0721")), subsys=("0x1043", "0x1954")):
    bus = tmp_path / "sdw"
    bus.mkdir()
    for n, (man, part) in enumerate(ids):
        (bus / f"sdw:0:{n}:{man}:{part}:0{n}").mkdir()
    (bus / "sdw-master-0-0").mkdir()
    pci = tmp_path / "pci"
    acp = pci / "0000:c4:00.5"
    acp.mkdir(parents=True)
    for k, v in {"class": "0x048000", "vendor": "0x1022", "subsystem_vendor": subsys[0],
                 "subsystem_device": subsys[1]}.items():
        (acp / k).write_text(v + "\n")
    drv = tmp_path / "drivers" / "snd_acp_pci"
    drv.mkdir(parents=True)
    os.symlink(drv, acp / "driver")
    gpu = pci / "0000:c4:00.0"
    gpu.mkdir()
    for k, v in {"class": "0x030000", "vendor": "0x1002", "subsystem_vendor": "0x1043", "subsystem_device": "0x0000"}.items():
        (gpu / k).write_text(v + "\n")
    cards = tmp_path / "cards"
    cards.write_text(" 0 [Generic        ]: HDA-Intel - HD-Audio Generic\n"
                     " 1 [amdsoundwire   ]: amd-soundwire - amd-soundwire\n")
    return str(bus), str(pci), str(cards)


def test_soundwire_ids_dedupes_and_skips_masters(tmp_path):
    bus, _, _ = _sysfs(tmp_path)
    assert hardware.soundwire_ids(bus) == [{"man": "0102", "part": "2783"}, {"man": "025d", "part": "0721"}]
    assert hardware.soundwire_ids(str(tmp_path / "missing")) == []


def test_subsys_token_is_device_then_vendor():
    assert hardware.sdw_subsys_token("0x1043", "0x1F2C") == "1f2c1043"
    assert hardware.sdw_subsys_token("0x10ec", "0x3072") == "307210ec"


def test_soundwire_codec_info(tmp_path):
    bus, pci, cards = _sysfs(tmp_path)
    c = hardware.soundwire_codec_info(bus, pci, cards)
    assert c["bus"] == "soundwire" and c["ssid"] == "19541043" and c["pci"] == "0000:c4:00.5"
    assert c["card"] == 1 and c["card_id"] == "amdsoundwire"
    assert c["codec"] == "SoundWire TI TAS2783, Realtek RT721"
    assert c["supported"] is True and c["model"] == "ROG Xbox Ally X20 (RC74XA)"


def test_soundwire_codec_info_needs_bus_and_pci(tmp_path):
    bus, pci, cards = _sysfs(tmp_path)
    assert hardware.soundwire_codec_info(str(tmp_path / "none"), pci, cards) is None
    assert hardware.soundwire_codec_info(bus, str(tmp_path / "none"), cards) is None


SDW = [{"man": "0102", "part": "2783"}, {"man": "025D", "part": "0721"}]
# Names as they appear in the ASUS Dolby Atmos driver V11.605.945.20 (the X20 is SUBSYS_19541043).
ENTRIES = [
    "x/dax3_ext_rtk.inf",
    "x/SOUNDWIRE_SDCAFUNCTION_10_MAN_0102_FUNC_0000_SUBSYS_19641043.xml",
    "x/SOUNDWIRE_SDCAFUNCTION_10_MAN_0102_FUNC_0000_SUBSYS_19541043_settings.xml",
    "x/SOUNDWIRE_SDCAFUNCTION_10_MAN_0102_FUNC_0000_SUBSYS_19541043.xml",
    "x/SOUNDWIRE_MAN_025D_FUNC_0721_SUBSYS_19541043_dmic.xml",
    "x/DEV_0294_SUBSYS_10431384_PCI_SUBSYS_13841043.xml",
]


def test_select_paths_soundwire():
    sel = asus_fetch.select_paths(ENTRIES, None, "19541043", SDW)
    assert sel["xml"].endswith("MAN_0102_FUNC_0000_SUBSYS_19541043.xml")
    assert sel["inf"].endswith("dax3_ext_rtk.inf")
    assert asus_fetch.select_paths(ENTRIES, None, "19551043", SDW)["xml"] is None
    assert asus_fetch.select_paths(ENTRIES, None, "19541043", [{"man": "01FA", "part": "3556"}])["xml"] is None
    sdw_short = ["y/SDW_MAN_0102_FUNC_0001_SUBSYS_19541043.xml"]
    assert asus_fetch.select_paths(sdw_short, None, "19541043", SDW)["xml"] == sdw_short[0]


def test_select_paths_hda_unchanged():
    sel = asus_fetch.select_paths(ENTRIES + ["x/dax3_ext_rtk.inf"], "0294", "10431384")
    assert sel["xml"].endswith("13841043.xml") and sel["inf"].endswith("dax3_ext_rtk.inf")


def test_find_speaker_sink_ucm():
    dump = [
        {"id": 50, "info": {"props": {"media.class": "Audio/Sink",
            "node.name": "alsa_output.pci-0000_c4_00.5-platform-amd_sdw.HiFi__Headphones__sink"}}},
        {"id": 51, "info": {"props": {"media.class": "Audio/Sink", "node.description": "Speaker",
            "node.name": "alsa_output.pci-0000_c4_00.5-platform-amd_sdw.HiFi__Speaker__sink"}}},
    ]
    sink = hardware.find_speaker_sink(dump)
    assert sink["id"] == 51 and sink["name"].endswith("HiFi__Speaker__sink")
    assert hardware.output_route(dump) is None and not hardware.headphones_active(None)
