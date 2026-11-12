# The dev dependency group from uv.lock as a Nix-built virtualenv, for the
# NixOS VM tests, which have no network and so cannot run `uv sync`.
{
  pkgs,
  lib,
  pyproject-nix,
  uv2nix,
  pyproject-build-systems,
}:
let
  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ../.; };
  overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };
  python = pkgs.python314;

  # These ship only as source distributions whose build requirements
  # pyproject-nix cannot read, so name them here.
  buildRequires = {
    mock-open.setuptools = [ ];
    pyric.setuptools = [ ];
    pyturbojpeg.setuptools = [ ];
    pymicro-vad = {
      setuptools = [ ];
      pybind11 = [ ];
    };
    pyspeex-noise = {
      setuptools = [ ];
      pybind11 = [ ];
    };
  };
  buildSystems =
    final: prev:
    lib.mapAttrs (
      name: requires:
      prev.${name}.overrideAttrs (old: {
        nativeBuildInputs = old.nativeBuildInputs ++ final.resolveBuildSystem requires;
      })
    ) buildRequires;

  pythonSet = (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope (
    lib.composeManyExtensions [
      pyproject-build-systems.overlays.wheel
      overlay
      buildSystems
    ]
  );
in
pythonSet.mkVirtualEnv "metron-env" workspace.deps.all
