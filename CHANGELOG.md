# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/): until 1.0.0 the interface and the
report format may still change between minor versions.

## [Unreleased]

## [0.2.0] - 2026-10-11

Hardware check, origin and event history; tablets, custom OSes and Android 7
supported; terms of use.

### Added
- Tablets are recognised as such: sensors expected of a tablet, wording in
  findings and test instructions, device type in the overview and the PDF.
- Custom ROMs named in the report (LineageOS, crDroid, CalyxOS and others),
  with the Android version the device launched with.
- Warning when the vendor layer (drivers, modem and secure-environment
  firmware) is more than a year behind the Android security patch.
- Galaxy Tab S5e, Galaxy A52s 5G and ASUS ZenFone AR in the catalogue of
  expected specifications.
- "Modified" verdict: when the secure environment, verified up to Google's
  roots, vouches for the hardware and the only serious findings follow from
  an unlocked bootloader, custom ROM or root, the device is reported as an
  original running modified software rather than as compromised.
- Other users, guest, work profile and private space left on the device.
- Wi-Fi-only and cellular versions told apart: a mobile radio inside a
  Wi-Fi-only model, or none inside a cellular one, is reported.
- Mid-grey screen pattern for OLED burn-in and LCD mura.
- Stylus test for pen digitizers (S Pen and similar): strokes with pressure,
  hover and side button.
- Battery capacity estimated from the current integrated over whole
  percents, for devices that do not report battery health (on request: it
  takes 10 to 30 minutes).
- run.sh accepts a toolchain kept outside the checkout (PHONEVITALS_TOOLCHAIN).
- Hardware check page: every component, sensors and actuators included, with
  what it reports about itself, whether the phone calls it original or
  replaced, the clues found and the tests that exercise it; component codes
  to match against spare parts; origin; a physical inspection checklist saved
  into the report.
- Screen and battery replacement as the phone itself reports it (Android 15
  and later), and the fingerprint reader's rejection rate, a sign of an
  uncalibrated under-display reader after a screen replacement.
- Components the firmware declares but the hardware does not report:
  missing, disconnected or dead parts.
- Market the phone was built for, from its hardware model number or
  Samsung sales code, compared with the country of its SIM.
- Event history: restarts classified (updates, flat battery, overheating,
  kernel panics, recovery and bootloader modes), recovery and file system
  repair records, and the traces of earlier use (SIMs, eSIMs, saved Wi-Fi
  networks, paired devices, account changes), counted on the phone.
- Liquid or debris in the USB-C port, where the port controller detects it;
  GPU model, board panel driver and the chip drivers loaded among the
  component codes.
- Terms of use (TERMS.md, also shown in the application from the sidebar and
  the start screen); using the software means accepting them. Reports and
  the store description refer to them.
- Battery gauge cross-checked with the capacity Android learns while
  charging: a large gap is a sign of an aftermarket battery or a reset gauge.
- Touch controller hardware IDs from the input service, among the component
  codes and compared with the reference unit.
- Camera and microphone privacy switches: tests report them instead of a
  failing camera or microphone.
- Pixel battery pairing: a battery taken from another phone is reported.
- Device age from the mainboard (Samsung serial, factory radio calibration,
  storage chip production date), never from the battery, which may have been
  replaced; without one, the time since the last reset is shown as such.
- GrapheneOS, CalyxOS, /e/OS and iodéOS recognised; a custom OS with the
  bootloader locked again is reported as modified, not compromised.

### Fixed
- Android 7 support: the agent is built for API 24 (the dex built for 26
  made app_process abort), the device commands no longer need awk, and the
  tests fall back where the shell lacks a command: vibration through the
  agent, Wi-Fi from the service's last scan, storage writes followed by
  sync, Bluetooth through the vendor's svc command; the cameras, which the
  debugging shell may not use there, are reported as such.
- Software-only attestation is a note on phones launched before Android 8,
  when hardware attestation was not yet required.
- A gauge above the design capacity after a handful of cycles is reported as
  not yet learned, not as 104% health; a cycle counter near zero on an
  old phone is noted (battery replaced or gauge reset).
- Processor cores capped by a firmware policy are judged against the cap.
- The fingerprint check no longer reports a missing reader on releases whose
  service lists no sensors.
- Asus market SKUs (WW, CN, JP, TW) and customer ID among the origin codes.
- Cameras refused on Android 16 builds (LineageOS 23), which ask the activity
  manager for the caller's tasks: the agent's activity manager now carries the
  shell identity too.
- On custom ROMs: missing Google services, a boot image one security bulletin
  behind the system, and recovery visits on update days are notes, not
  warnings.
- Camera and microphone access refused on stricter Android 15 builds
  (LineageOS 22): the agent now identifies itself as the shell package, so
  the camera test no longer reports working cameras as dead and the
  microphone test no longer records silence.
- Cameras read from the per-HAL-device sections newer camera services print:
  facing, resolution and flash were missing.
- Loudspeaker, earpiece and microphones read from the audio policy; on
  Android 15 the old source returned nothing.
- Storage type and commercial size where sysfs is closed to the shell: from
  the boot device and from Android's storage service instead of an estimate.
- First start after a reset no longer taken from a clock reset to New Year.
- Thermal zones that report a fixed limit instead of a temperature are
  ignored, which made the processor test show a constant 75 °C.
- Flash, mobile network and satellite tests offered only when the device
  declares the hardware.
- Live temperatures from the thermal HAL's current readings: the cached
  ones only change when a threshold is crossed and showed stale values.
- Screen patterns open in the gallery from shared storage, in the screen's
  current orientation: galleries cannot read the old location and closed at
  once. A missing viewer is inconclusive, not a screen failure.

## [0.1.0] - 2026-10-10

First version prepared for public release.

### Added
- Desktop interface: overview with verdict and points needing attention,
  authenticity, health, functional tests, live sensors, specifications and
  raw data; light and dark themes following the system.
- Hardware attestation chain verified offline up to Google's roots, with
  Google's revocation list.
- History: production month (Samsung), first start after the last reset,
  boots, abnormal restarts, crashes and hardware errors in the system log.
- Locks and leftovers: Google account (Factory Reset Protection), financing
  lock, device owner, personal files counted.
- Automatic tests: storage write speed, charging, processor under load,
  loudspeaker and microphone through the computer, Bluetooth, mobile network,
  GNSS; camera stills in a guided test.
- Local memory of analysed phones with salted hashes, reference units per
  model, PDF report with fingerprint, bench mode.
- Snap packaging and GitHub workflows for CI and releases.

### Changed
- Battery health is reported only when the device really measures it.

### Security
- The local server requires a per-launch session token and checks the Host
  header, so web pages cannot drive a connected phone.
