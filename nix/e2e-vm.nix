# The end-to-end tests inside NixOS VMs, built from this flake, with no
# network. `web-sqlite` and `web-postgresql` run tests/e2e in Chromium, each
# against one database. `android` runs the cards inside
# the Companion app on an Android emulator, which needs nested KVM on the
# host, and copies its screenshots to $out/screenshots.
{
  pkgs,
  lib,
  pythonEnv,
  android,
}:
let
  # Only what the tests read; edits elsewhere do not rebuild the VM tests.
  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../custom_components
      ../tests
      ../pyproject.toml
      ../README.md
    ];
  };

  common = {
    users.users.tester.isNormalUser = true;
    environment.systemPackages = [ pythonEnv ];
    # Straight from the store, not the system profile: initdb finds its data
    # files relative to itself, and the profile leaves share/postgresql out.
    environment.extraInit = ''
      export PATH="${lib.getBin pkgs.postgresql}/bin:$PATH"
    '';
    environment.variables = {
      PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
      PLAYWRIGHT_DRIVER_VERSION = pkgs.playwright-driver.version;
      PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "true";
      # The Playwright wheel's bundled Node is a generic Linux binary.
      PLAYWRIGHT_NODEJS_PATH = "${pkgs.nodejs_24}/bin/node";
      ZPMF_FONTCONFIG_FILE = import ./fonts.nix { inherit pkgs; };
    };
  };

  # pytest and Home Assistant need a writable copy of the repository.
  copySource = ''
    machine.wait_for_unit("multi-user.target")
    machine.succeed("cp -r ${src} /home/tester/repo && chown -R tester /home/tester/repo && chmod -R u+w /home/tester/repo")
  '';
  pytest = args: ''
    machine.succeed("su - tester -c 'cd repo && pytest -p no:homeassistant -p no:cacheprovider -q ${args}' >&2")
  '';

  # tests/e2e on one database. Deselecting the other database's tests, rather
  # than selecting this one's, keeps a test that uses no database in both.
  web =
    database: other:
    pkgs.testers.runNixOSTest {
      name = "zp-my-fitness-e2e-${database}";
      nodes.machine = {
        imports = [ common ];
        virtualisation = {
          cores = 4;
          memorySize = 6144;
          diskSize = 8192;
        };
      };
      testScript = copySource + pytest ''tests/e2e --ignore=tests/e2e/test_android.py -k \"not ${other}\"'';
    };
in
{
  web-sqlite = web "sqlite" "postgresql";
  web-postgresql = web "postgresql" "sqlite";

  android = pkgs.testers.runNixOSTest {
    name = "zp-my-fitness-android";
    nodes.machine = {
      imports = [ common ];
      virtualisation = {
        cores = 6;
        memorySize = 10240;
        diskSize = 20480;
        # The emulator needs KVM inside this VM.
        qemu.options = [ "-cpu host" ];
      };
      boot.kernelModules = [
        "kvm-amd"
        "kvm-intel"
      ];
      users.users.tester.extraGroups = [ "kvm" ];
      environment.systemPackages = [
        android.sdk
        android.create-avd
      ];
      environment.variables = {
        ANDROID_HOME = android.sdkRoot;
        ANDROID_SDK_ROOT = android.sdkRoot;
        COMPANION_APK = "${android.companion}";
        ZPMF_SCREENSHOTS = "/home/tester/screenshots";
      };
    };
    testScript = copySource + ''
      status, _ = machine.execute("su - tester -c 'cd repo && pytest -p no:homeassistant -p no:cacheprovider -q tests/e2e/test_android.py' >&2", timeout=None)
      # Copied before failing, so a failed run still shows its screens.
      machine.copy_from_machine("/home/tester/screenshots", "")
      assert status == 0, "tests/e2e/test_android.py failed"
    '';
  };
}
