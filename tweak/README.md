# WazeIOS6Fix — force proxy + SSL trust pour Waze (iOS 6)

Waze ignore le proxy Wi‑Fi. Ce tweak Substrate :
1. Force un proxy HTTP (mitmweb) pour le process Waze
2. Désactive la vérif SSL (SecTrustEvaluate) pour Waze

## Build (Theos, Mac ou Linux avec toolchain iOS)

```bash
export THEOS=~/theos
cd tweak/WazeIOS6Fix
make package
```

Le `.deb` sort dans `packages/`.

## Install sur l’iPhone

1. mitmweb tourne sur le PC (`192.168.1.191:8080`)
2. Installe le `.deb` (Filza / `dpkg -i` / SCP + Cydia)
3. Réglages → **WazeIOS6Fix** → IP du PC + port 8080 + Enable
4. Respring, ouvre Waze

## Bundle IDs ciblés

`com.waze.iphone`, `com.waze.app`, `com.waze`, `com.google.waze`
