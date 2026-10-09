"""Parsing regressions for the collectors.

No phone required: each case feeds a collector the raw text a real device
produces and checks what comes out. Every case here is a past misreading --
a value lost, or worse, a value invented -- that must not come back.
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phonevitals.collectors.hardware import CpuCollector, StorageCollector   # noqa: E402
from phonevitals.collectors.identity import IdentityProbe                    # noqa: E402
from phonevitals.collectors.peripherals import (                             # noqa: E402
    BiometricCollector, CameraCollector, InputCollector,
)
from phonevitals.collectors.history import HistoryCollector                  # noqa: E402
from phonevitals.collectors.power import BatteryCollector, merge_agent_facts  # noqa: E402
from phonevitals.collectors.radio import TelephonyCollector, WifiCollector   # noqa: E402
from phonevitals.collectors.security import SecurityCollector                # noqa: E402
from phonevitals.collectors.system import SystemCollector                    # noqa: E402


def check(condition: bool, message: str) -> bool:
    print(("  ok   " if condition else "  FAILED ") + message)
    return condition


def battery() -> bool:
    print("battery")
    ok = True
    # BatteryService prints one "<source> powered" line per source and no
    # `plugged` line at all.
    dumpsys = (
        "Current Battery Service state:\n"
        "  AC powered: false\n  USB powered: true\n"
        "  Wireless powered: false\n  Dock powered: false\n"
        "  status: 2\n  health: 2\n  present: true\n  level: 59\n"
        "  scale: 100\n  voltage: 3955\n  temperature: 280\n"
        "  technology: Li-ion\n"
    )
    out = BatteryCollector().parse({"bat.dumpsys": dumpsys})
    ok &= check(out["plugged"] == "USB", "USB power source read without a plugged line")

    unknown = BatteryCollector().parse({"bat.dumpsys": "  level: 50\n"})
    ok &= check(unknown["plugged"] == "n/a", "missing power source is n/a, not none")

    new_cell = BatteryCollector().parse({"bat.sysfs": "cycle_count=0\n"})
    ok &= check(new_cell["cycle_count"] == 0, "zero cycles kept as 0, not lost")

    samsung = BatteryCollector().parse(
        {"bat.sysfs": "cycle_count=0\nbattery_cycle=212\n"})
    ok &= check(samsung["cycle_count"] == 212, "positive battery_cycle wins over a 0")

    # A Galaxy A52s with a reset gauge: full capacity echoes the design value,
    # no cycle count, and the ASOC is the gauge's default. Reporting 100%
    # health here would vouch for a cell nobody measured.
    reset = BatteryCollector().parse({"bat.sysfs": (
        "charge_full=4500000\ncharge_full_design=4500000\nbattery_cycle=-1\n"
        "fg_cycle=0\nfg_asoc=99\nbatt_capacity_max=990\n")})
    ok &= check(reset["health_percent"] is None, "nominal capacity is not a 100% health reading")
    ok &= check(bool(reset["health_note"]), "the reason health is unknown is stated")

    learned = BatteryCollector().parse({"bat.sysfs": (
        "charge_full=4120000\ncharge_full_design=4500000\n")})
    ok &= check(learned["health_percent"] == 91.6, "a learned capacity gives the health ratio")

    gauge = BatteryCollector().parse({"bat.sysfs": (
        "charge_full=4500000\ncharge_full_design=4500000\nbattery_cycle=430\nfg_asoc=86\n")})
    ok &= check(gauge["health_percent"] == 86 and "ASOC" in gauge["health_source"],
                "Samsung ASOC used when the gauge has a history")
    return ok


def battery_sources() -> bool:
    print("battery health sources")
    ok = True
    stats = ("  Estimated battery capacity: 4500 mAh\n"
             "  Last learned battery capacity: 3870 mAh\n"
             "  Min learned battery capacity: 3810 mAh\n"
             "  Max learned battery capacity: 3990 mAh\n")
    learned = BatteryCollector().parse({
        "bat.sysfs": "charge_full=4500000\ncharge_full_design=4500000\n",
        "bat.stats": stats})
    ok &= check(learned["health_percent"] == 86.0
                and learned["health_source"].startswith("learned"),
                "batterystats learned capacity fills in when the gauge echoes design")
    echo = BatteryCollector().parse({
        "bat.sysfs": "charge_full=4500000\ncharge_full_design=4500000\n",
        "bat.stats": "  Last learned battery capacity: 4500 mAh\n"})
    ok &= check(echo["health_percent"] is None, "a learned value equal to design is not a reading")

    bat = {"health_percent": None, "cycle_count": None}
    merge_agent_facts(bat, {"state_of_health_percent": 100})
    ok &= check(bat["health_percent"] is None and bool(bat["health_note"]),
                "100% state of health without cycles is not trusted")
    bat = {"health_percent": None, "cycle_count": None}
    merge_agent_facts(bat, {"state_of_health_percent": 91, "cycle_count": 312,
                            "manufacturing_date": "2023-04-02"})
    ok &= check(bat["health_percent"] == 91 and bat["cycle_count"] == 312
                and bat["manufacturing_date"]["iso"] == "2023-04-02",
                "Android 14 battery facts fill the gaps")
    return ok


def charging_units() -> bool:
    print("charging test helpers")
    from phonevitals.testsuite import TestSuite
    ok = check(TestSuite._to_ma(340) == 340 and TestSuite._to_ma(-412000) == -412,
               "BatteryManager current in mA (Samsung) and in uA (the API) both read right")
    state = TestSuite._battery_state("  AC powered: false\n  USB powered: true\n"
                                     "  status: 2\n  level: 61\n  voltage: 3998\n")
    ok &= check(state == {"plugged": 2, "status": 2, "level": 61, "voltage_v": 3.998},
                "dumpsys battery state parsed")
    return ok


def history() -> bool:
    print("history")
    ok = True
    raw = {
        "sys.props": "[ro.product.brand]: [samsung]\n[ro.serialno]: [R5CR8TEST01]\n"
                     "[sys.boot.reason]: [reboot,userrequested]\n",
        "hist.boot_count": "57\n",
        "hist.boot_history": "reboot,userrequested,1760000000\nkernel_panic,1759000000\n"
                             "reboot,ota,1758000000",
        "hist.install_days": "3 1 2009-01-01\n200 1 2021-01-01\n187 61 2023-05-12\n"
                             "2 2 2023-06-01\n1 1 2026-10-01\n",
        "hist.dropbox": "      2 2026-10-07 SYSTEM_TOMBSTONE\n      1 2026-10-08 SYSTEM_LAST_KMSG\n"
                        "      4 2026-10-08 data_app_crash\n",
        "hist.accounts": "      1 com.google\n      2 com.whatsapp\naccounts-read\n",
    }
    h = HistoryCollector().parse(raw)
    ok &= check(bool(h["manufactured"]) and h["manufactured"]["iso"] == "2021-08",
                "Samsung serial decoded to August 2021")
    ok &= check(h["setup_date"]["iso"] == "2023-05-12" and h["setup_date"]["confident"],
                "setup date skips clock defaults and same-second build placeholders")
    reflashed = HistoryCollector().parse({"hist.install_days": "200 1 2021-01-01\n9 9 2026-08-08\n"})
    ok &= check(reflashed["setup_date"]["iso"] == "2026-08-08"
                and not reflashed["setup_date"]["confident"],
                "a ROM's placeholder date is not taken for the setup date")
    ok &= check(h["boot_count"] == 57, "boot count read")
    ok &= check([b["abnormal"] for b in h["boot_history"]] == [False, True, False],
                "kernel panic flagged as an abnormal restart")
    ok &= check(h["crashes"]["counts"] == {"SYSTEM_TOMBSTONE": 2},
                "only crash tags of note are counted, not the kernel log of an update")
    ok &= check(h["accounts"]["google"] == 1 and h["accounts"]["read"],
                "Google account counted without its name")
    pixel = HistoryCollector().parse({"sys.props": "[ro.product.brand]: [google]\n"
                                                   "[ro.serialno]: [0A1B2C3D4E5F6G]\n"})
    ok &= check(pixel["manufactured"] is None, "no date invented for serials without one")
    command = HistoryCollector().commands()["hist.log_errors"]
    ok &= check("' adbd '" in command and "__PV_" in command,
                "the log scan skips adbd's record of our own commands")
    none = HistoryCollector().parse({"hist.accounts": "accounts-read\n"})
    ok &= check(none["accounts"]["read"] and none["accounts"]["google"] == 0,
                "no accounts is a reading, not a failure")
    return ok


def wifi() -> bool:
    print("wifi")
    ok = True
    # Pixel prints this second line when Wi-Fi is *off*.
    off = WifiCollector().parse({"wifi.status": (
        "Wifi is disabled\n"
        "Wifi scanning is only available when wifi is enabled\n")})
    ok &= check(off["enabled"] is False, "disabled Wi-Fi not read as enabled")
    ok &= check(off["connected"] is False, "disabled Wi-Fi not connected")

    on = WifiCollector().parse({"wifi.status": (
        "Wifi is enabled\n==== Primary ClientModeManager instance ====\n"
        'Wifi is connected to "net"\n')})
    ok &= check(on["enabled"] and on["connected"], "enabled and connected Wi-Fi")
    return ok


def telephony() -> bool:
    print("telephony")
    reg = (
        "  mSignalStrength=SignalStrength:{"
        "mCdma=CellSignalStrengthCdma: cdmaDbm=2147483647 level=0, "
        "mGsm=CellSignalStrengthGsm: rssi=2147483647 ber=2147483647 "
        "mTa=2147483647 mLevel=0, "
        "mLte=CellSignalStrengthLte: rssi=-75 rsrp=-105 rsrq=-10 rssnr=10 "
        "level=3 parametersUseForLevel=1, "
        "mNr=CellSignalStrengthNr:{ csiRsrp = 2147483647 ssRsrp = -98 "
        "ssRsrq = -11 level = 2 }, primary=CellSignalStrengthLte}\n"
        "  mBatteryLevel=4\n"
    )
    sig = TelephonyCollector()._signal(reg)
    ok = check(sig.get("level") == 3, "level taken from the best technology, "
               "not the first (GSM, 0)")
    ok &= check(sig.get("rssi_dbm") == -75, "first valid rssi, not the GSM placeholder")
    ok &= check(sig.get("nr_rsrp_dbm") == -98, "NR values with spaces around '='")
    ok &= check(sig.get("lte_rsrp_dbm") == -105, "LTE rsrp")
    return ok


def cpu() -> bool:
    print("cpu")
    # Two big cores offline: their cpufreq nodes are gone, the present mask
    # still lists them.
    freqs = "".join(f"cpu{i}.cpuinfo_max_freq=2000000\n" for i in range(6))
    out = CpuCollector().parse({"cpu.freqs": freqs, "cpu.present": "0-7"})
    ok = check(out["core_count"] == 8, "offline cores counted from the present mask")

    cpuinfo = (
        "processor\t: 0\nCPU implementer\t: 0x41\nCPU part\t: 0xd03\n\n"
        "processor\t: 1\nCPU implementer\t: 0x41\nCPU part\t: 0xd03\n\n"
        "Hardware\t: MT6765\nSerial\t: 0000\n"
    )
    soc = SystemCollector()._soc({}, cpuinfo)
    ok &= check(soc["core_count_cpuinfo"] == 2,
                "trailing Hardware block not counted as a core")
    ok &= check(soc["hardware_line"] == "MT6765", "Hardware line read")
    return ok


def storage() -> bool:
    print("storage")
    # A 256 GB microSD card in a 64 GB UFS phone: only the UFS LUNs count.
    proc = (
        " 8        0   62464000 sda\n"
        " 8       16       4096 sdb\n"
        "179        0  250000000 mmcblk0\n"
    )
    out = StorageCollector().parse({"stor.proc_disks": proc})
    ok = check(out["nominal_gb"] == 64, "microSD card not taken for internal storage")
    ok &= check(out["type"] == "UFS", "storage type UFS")

    sd_on_mmc0 = StorageCollector().parse(
        {"stor.mmc": "type=SD\nname=SD64G\n", "stor.proc_disks": proc})
    ok &= check(sd_on_mmc0["emmc"] is None, "SD card on mmc0 not reported as eMMC")

    emmc = StorageCollector().parse({
        "stor.mmc": "type=MMC\nname=HAG4a2\nmanfid=0x000015\n",
        "stor.proc_disks": "179        0   30535680 mmcblk0\n"
                           "179       32  125000000 mmcblk1\n",
    })
    ok &= check(emmc["emmc"] is not None and emmc["type"] == "eMMC",
                "internal eMMC read")
    ok &= check(emmc["nominal_gb"] == 32, "eMMC size from mmcblk0, not the SD card")
    return ok


def camera() -> bool:
    print("camera")
    # camera_metadata dump format: hexadecimal tag id, type, values in
    # brackets on the next line.
    dump = (
        "== Camera 0 information: ==\n"
        "  android.lens.facing (80005): byte[1]\n        [BACK ]\n"
        "  android.lens.info.availableApertures (90000): float[1]\n"
        "        [1.6800 ]\n"
        "  android.lens.info.availableFocalLengths (90002): float[1]\n"
        "        [6.8100 ]\n"
        "  android.sensor.info.activeArraySize (f0000): int32[4]\n"
        "        [8 8 4080 3064 ]\n"
        "  android.sensor.info.physicalSize (f0005): float[2]\n"
        "        [9.7920 7.3440 ]\n"
        "  android.sensor.info.pixelArraySize (f0006): int32[2]\n"
        "        [4096 3072 ]\n"
        "  android.sensor.info.pixelArraySizeMaximumResolution (f0013): int32[2]\n"
        "        [8192 6144 ]\n"
        "  android.flash.info.available (50000): byte[1]\n        [TRUE ]\n"
        "  android.info.supportedHardwareLevel (150000): byte[1]\n"
        "        [FULL ]\n"
    )
    cams = CameraCollector().parse({"cam.dumpsys": dump})["cameras"]
    ok = check(len(cams) == 1, "one camera block")
    if not cams:
        return False
    cam = cams[0]
    ok &= check(cam["pixel_array"] == {"width": 4096, "height": 3072},
                "pixel array read from the values, not the tag id")
    ok &= check(cam["megapixels"] == 12.6, "megapixels")
    ok &= check(cam["focal_lengths_mm"] == [6.81], "focal length")
    ok &= check(cam["apertures"] == [1.68], "aperture")
    ok &= check((cam["active_array"] or {}).get("width") == 4080, "active array")
    ok &= check(cam["facing"] == "rear", "facing from android.lens.facing")
    ok &= check(cam["has_flash"] is True, "flash")
    ok &= check(cam["hardware_level"] == "FULL", "hardware level")
    return ok


def input_devices() -> bool:
    print("input")
    getevent = (
        "add device 1: /dev/input/event2\n"
        '  name:     "touch_ts"\n'
        "  events:\n"
        "    KEY (0001): KEY_WAKEUP\n"
        "    ABS (0003): ABS_MT_SLOT           : value 0, min 0, max 9, fuzz 0, flat 0, resolution 0\n"
        "                ABS_MT_POSITION_X     : value 0, min 0, max 1079, fuzz 0, flat 0, resolution 0\n"
        "                ABS_MT_POSITION_Y     : value 0, min 0, max 2399, fuzz 0, flat 0, resolution 0\n"
        "  input props:\n"
        "    INPUT_PROP_DIRECT\n"
    )
    devices = InputCollector().parse({"in.getevent": getevent})["devices"]
    ok = check(len(devices) == 1 and devices[0]["is_touchscreen"], "touchscreen found")
    if devices:
        ok &= check(devices[0]["max_slots"] == 10,
                    "axis on the section header line not dropped")
        ok &= check("KEY_WAKEUP" in devices[0]["keys"],
                    "key on the section header line not dropped")
    return ok


def biometrics() -> bool:
    print("biometrics")
    dump = "sensorId: 0\n  user 0: sensorId=0\n  user 10: sensorId=0\n"
    out = BiometricCollector().parse({"bio.fingerprint": dump})
    return check(out["fingerprint"]["sensors"] == ["0"], "sensor ids listed once")


def security() -> bool:
    print("security")
    detector = SecurityCollector().parse({
        "sec.packages_root": "package:io.github.vvb2060.magiskdetector\n"})
    ok = check(detector["root"]["detected"] is False,
               "a root detector app is not evidence of root")
    magisk = SecurityCollector().parse({
        "sec.packages_root": "package:com.topjohnwu.magisk\n"})
    ok &= check(magisk["root"]["detected"] is True, "Magisk still detected")
    root_shell = SecurityCollector().parse({"sec.id": "uid=0(root) gid=0(root) groups=0(root)"})
    ok &= check(root_shell["root"]["detected"] is True, "adb running as root is root access")
    shell = SecurityCollector().parse({"sec.id": "uid=2000(shell) gid=2000(shell)"})
    ok &= check(shell["root"]["detected"] is False, "the normal shell user is not root")
    return ok


def identity() -> bool:
    print("identity")
    imeisv = ET.fromstring(
        '<hierarchy><node text="IMEI SV 4901542017674001" /></hierarchy>')
    imeis, _ = IdentityProbe._extract_from_tree(imeisv)
    return check(imeis == ["490154201767409"],
                 "IMEISV converted to the IMEI with its check digit")


def main() -> int:
    ok = True
    for case in (battery, battery_sources, charging_units, history, wifi, telephony, cpu, storage, camera,
                 input_devices, biometrics, security, identity):
        ok &= case()
    print()
    print("RESULT: " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
