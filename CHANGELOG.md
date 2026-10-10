# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/): until 1.0.0 the interface and the
report format may still change between minor versions.

## [Unreleased]

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
