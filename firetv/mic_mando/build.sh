#!/usr/bin/env bash
# Compila e instala la app del experimento en el Fire TV (sin Gradle: aapt2 + javac + d8 + apksigner).
set -euo pipefail
cd "$(dirname "$0")"
SDK=${ANDROID_HOME:-$HOME/android-sdk}
BT=$SDK/build-tools/34.0.0
JAR=$SDK/platforms/android-28/android.jar
KS=$HOME/.android/debug.keystore
rm -rf build && mkdir -p build/classes build/dex
"$BT/aapt2" link --manifest AndroidManifest.xml -I "$JAR" --min-sdk-version 28 --target-sdk-version 28 \
    --debug-mode -o build/base.apk
javac --release 11 -classpath "$JAR" -d build/classes $(find src -name '*.java')
"$BT/d8" --min-api 28 --lib "$JAR" --output build/dex $(find build/classes -name '*.class')
cp build/base.apk build/sin_firmar.apk
(cd build/dex && zip -q ../sin_firmar.apk classes.dex)
"$BT/zipalign" -f 4 build/sin_firmar.apk build/alineado.apk
if [ ! -f "$KS" ]; then  # clave de depuración estándar de Android (no es un secreto)
    mkdir -p "$(dirname "$KS")"
    keytool -genkeypair -keystore "$KS" -storepass android -keypass android -alias androiddebugkey \
        -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --out build/micmando.apk build/alineado.apk
echo "APK: $(pwd)/build/micmando.apk"
