# WazeIOS6Fix — lab only (not Relight)

**Relight** (Cydia public) is `com.wazeios6.server` — see `tweak/layout/` and
`tweak/build-deb.sh`. Do not ship this package to end users.

This Substrate tweak is for a **local mitmweb** lab:

1. Force an HTTP proxy for the Waze process (Waze ignores Wi‑Fi proxy)
2. Disable SSL trust (`SecTrustEvaluate`) for Waze

## Build (Theos, Mac or Linux with iOS toolchain)

```bash
export THEOS=~/theos
cd tweak/WazeIOS6Fix
make package
```

The `.deb` lands in `packages/`.

## Install on the iPhone

1. mitmweb on the PC (`192.168.1.191:8080`)
2. Install the `.deb` (Filza / `dpkg -i`)
3. Settings → **WazeIOS6Fix** → PC IP + port 8080 + Enable
4. Respring, open Waze

## Bundle IDs

`com.waze.iphone`, `com.waze.app`, `com.waze`, `com.google.waze`
