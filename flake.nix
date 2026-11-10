{
  description = "ZPMyFitnessCards development shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    # nixpkgs-unstable dropped x86_64-darwin in 26.11; 26.05 keeps it until
    # the end of 2026.
    nixpkgs-x86_64-darwin.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
    android-nixpkgs = {
      url = "github:tadfisher/android-nixpkgs";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-x86_64-darwin,
      android-nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems =
        f:
        nixpkgs.lib.genAttrs systems (
          system:
          f (if system == "x86_64-darwin" then nixpkgs-x86_64-darwin else nixpkgs).legacyPackages.${system}
        );
    in
    {
      devShells = forAllSystems (
        pkgs:
        let
          inherit (pkgs.stdenv.hostPlatform) system;

          default = pkgs.mkShell {
            packages = [
              pkgs.python314
              pkgs.uv
              pkgs.nodejs_24
              pkgs.ruff
              # A throwaway server for the tests that run against Postgres.
              (pkgs.lib.getBin pkgs.postgresql)
            ];

            env = {
              # uv builds .venv from this interpreter and never downloads its own.
              UV_PYTHON = "${pkgs.python314}/bin/python3";
              UV_PYTHON_DOWNLOADS = "never";
            }
            // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
              # Wheels with compiled code (greenlet, numpy, ...) link against
              # these, which NixOS keeps out of the default library path.
              LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
                pkgs.stdenv.cc.cc.lib
                pkgs.zlib
                pkgs.libjpeg_turbo
              ];
              # The end-to-end tests drive this Chromium. Playwright for Python in
              # .venv must be the same version as this driver; tests/e2e checks it.
              PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
              PLAYWRIGHT_DRIVER_VERSION = pkgs.playwright-driver.version;
              PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "true";
              # The driver bundled in the Python wheel runs its own Node, a
              # generic Linux binary that NixOS cannot start.
              PLAYWRIGHT_NODEJS_PATH = "${pkgs.nodejs_24}/bin/node";
            };

            shellHook = ''
              "${pkgs.uv}/bin/uv" sync --locked --quiet
              source .venv/bin/activate
              # Home Assistant depends on the uv wheel, whose generic Linux
              # binary NixOS cannot start, so keep this shell's uv first.
              export PATH="${pkgs.uv}/bin:$PATH"
            '';
          };

          android = import ./nix/android.nix { inherit pkgs android-nixpkgs; };
        in
        {
          inherit default;
        }
        // pkgs.lib.optionalAttrs (system == "x86_64-linux") {
          # The default shell plus an Android emulator, kept apart so CI does
          # not download the SDK.
          android = default.overrideAttrs (old: {
            nativeBuildInputs = old.nativeBuildInputs ++ [
              # These wrappers sit ahead of the SDK on PATH. Both write to $HOME whatever
              # ANDROID_USER_HOME says (adb its server state, the emulator its
              # console token, which adb emu then reads back), so both run
              # with the HOME the shell hook sets aside.
              # steam-run gives the emulator an FHS environment where the host
              # GPU drivers load.
              (pkgs.writeShellScriptBin "emulator" ''
                HOME="$ANDROID_SANDBOX_HOME" exec ${pkgs.steam-run-free}/bin/steam-run ${android.sdkRoot}/emulator/emulator "$@"
              '')
              (pkgs.writeShellScriptBin "adb" ''
                HOME="$ANDROID_SANDBOX_HOME" exec ${android.sdkRoot}/platform-tools/adb "$@"
              '')
              android.sdk
              android.create-avd
            ];
            ANDROID_HOME = android.sdkRoot;
            ANDROID_SDK_ROOT = android.sdkRoot;
            # The Companion app, for adb install.
            COMPANION_APK = android.companion;
            shellHook = old.shellHook + ''
              # AVDs, adb keys and emulator settings live in .android here
              # (ignored by git), not in ~/.android.
              export ANDROID_SANDBOX_HOME="$PWD/.android"
              export ANDROID_USER_HOME="$ANDROID_SANDBOX_HOME/.android"
              export ANDROID_AVD_HOME="$ANDROID_USER_HOME/avd"
              export ANDROID_EMULATOR_HOME="$ANDROID_USER_HOME"
              [ -e "$ANDROID_AVD_HOME/pixel_8.ini" ] || create-avd
            '';
          });
        }
      );

      packages.x86_64-linux.python-env = import ./nix/python.nix {
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
        inherit (nixpkgs) lib;
        inherit pyproject-nix uv2nix pyproject-build-systems;
      };

      # nix build .#checks.x86_64-linux.e2e-vm-sqlite (or e2e-vm-postgresql, android-vm)
      checks.x86_64-linux =
        let
          pkgs = nixpkgs.legacyPackages.x86_64-linux;
          vms = import ./nix/e2e-vm.nix {
            inherit pkgs;
            inherit (nixpkgs) lib;
            pythonEnv = self.packages.x86_64-linux.python-env;
            android = import ./nix/android.nix { inherit pkgs android-nixpkgs; };
          };
        in
        {
          e2e-vm-sqlite = vms.web-sqlite;
          e2e-vm-postgresql = vms.web-postgresql;
          android-vm = vms.android;
        };
    };
}
