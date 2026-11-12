# The only fonts the end-to-end tests' Chromium sees: DejaVu, under
# fontconfig's own default rules, with none of the host's, so pages render
# alike in the dev shell, on CI runners (which may have no fonts at all) and
# in the VMs. tests/e2e/conftest.py gives this file to the browser as
# FONTCONFIG_FILE.
{ pkgs }:
pkgs.writeText "metron-fonts.conf" ''
  <?xml version="1.0"?>
  <!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
  <fontconfig>
    <include>${pkgs.fontconfig.out}/etc/fonts/conf.d</include>
    <dir>${pkgs.dejavu_fonts}/share/fonts</dir>
  </fontconfig>
''
