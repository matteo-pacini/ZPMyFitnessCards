# The Android pieces the dev shell and the VM tests share: an SDK with one
# system image, a script that makes the Pixel 8 AVD, and the Companion app.
{ pkgs, android-nixpkgs }:
rec {
  # A Pixel 8 on the newest stable Play Store image with 16 KB pages.
  image = "system-images;android-37.2;google_apis_playstore_ps16k;x86_64";

  sdk = android-nixpkgs.sdk.x86_64-linux (
    s: with s; [
      cmdline-tools-latest
      emulator
      # The 37.0.2 zip android-nixpkgs pins is gone from Google's mirror.
      # Drop this override once android-nixpkgs moves on.
      (platform-tools.overrideAttrs {
        src = pkgs.fetchurl {
          url = "https://dl.google.com/android/repository/platform-tools_r37.0.1-linux.zip";
          sha1 = "477254aa5f903c15cf51001717bdf347fb6b53e0";
        };
      })
      system-images-android-37-2-google-apis-playstore-ps16k-x86-64
    ]
  );

  sdkRoot = "${sdk}/share/android-sdk";

  # Writes the AVD into $ANDROID_AVD_HOME. The emulator fills in every
  # setting left out with the device's defaults. Written by hand, not with
  # avdmanager, which needs Java and turns the Play Store and keyboard off.
  create-avd = pkgs.writeShellScriptBin "create-avd" ''
    set -eu
    avd="$ANDROID_AVD_HOME/pixel_8.avd"
    mkdir -p "$avd"
    cat > "$ANDROID_AVD_HOME/pixel_8.ini" <<EOF
    avd.ini.encoding=UTF-8
    path=$avd
    path.rel=avd/pixel_8.avd
    target=android-37.2
    EOF
    cat > "$avd/config.ini" <<EOF
    avd.ini.encoding=UTF-8
    PlayStore.enabled=yes
    abi.type=x86_64
    hw.cpu.arch=x86_64
    hw.device.manufacturer=Google
    hw.device.name=pixel_8
    hw.lcd.width=1080
    hw.lcd.height=2400
    hw.lcd.density=420
    hw.ramSize=2G
    hw.keyboard=yes
    hw.camera.back=emulated
    hw.camera.front=none
    disk.dataPartition.size=6G
    image.sysdir.1=system-images/android-37.2/google_apis_playstore_ps16k/x86_64/
    tag.id=google_apis_playstore
    tag.ids=google_apis_playstore,page_size_16kb
    target=android-37.2
    EOF
  '';

  # The Home Assistant Companion app, release build.
  companion = pkgs.fetchurl {
    url = "https://github.com/home-assistant/android/releases/download/2026.11.1/app-full-release.apk";
    sha256 = "07z44zr9saly0bdd2v62pacnzmwyfrk6z04xqja2i0qvkspsn4cw";
  };
}
