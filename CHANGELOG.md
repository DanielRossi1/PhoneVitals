# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/): until 1.0.0 the interface and the
report format may still change between minor versions.

## [Unreleased]

### Added
- Tablets are recognised as such: sensors expected of a tablet, wording in
  findings and test instructions, device type in the overview and the PDF.
- Custom ROMs named in the report (LineageOS, crDroid, CalyxOS and others),
  with the Android version the device launched with.
- Warning when the vendor layer (drivers, modem and secure-environment
  firmware) is more than a year behind the Android security patch.
- Galaxy Tab S5e in the catalogue of expected specifications.
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

### Fixed
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
