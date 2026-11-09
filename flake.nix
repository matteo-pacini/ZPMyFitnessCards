{
  description = "ZPMyFitnessCards development shell";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.python314
            pkgs.uv
            pkgs.nodejs_24
            pkgs.ruff
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
      });
    };
}
