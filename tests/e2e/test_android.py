"""The cards inside the Home Assistant Companion app, on an Android emulator.

Skipped unless COMPANION_APK names the app's APK, which the `android` dev shell
and the NixOS VM test (nix/e2e-vm.nix) both set. Screenshots go to
ZPMF_SCREENSHOTS when it is set.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Locator, Page, expect
from playwright.sync_api import Error as PlaywrightError

from . import screenshots as shots
from .conftest import CONFIGURATION, Home, _free_port, _home
from .screenshots import add_sample_data

APK = os.environ.get("COMPANION_APK")
APP = "io.homeassistant.companion.android"
PHOTOS = "com.google.android.apps.photos"

BARCODE = "5201054017111"

pytestmark = pytest.mark.skipif(not APK, reason="COMPANION_APK is not set")

# The app logs in with no password from 127.0.0.1, which is where the
# emulator's traffic to 10.0.2.2 arrives. mobile_app registers the device.
APP_CONFIGURATION = (
    CONFIGURATION.replace(
        "homeassistant:\n",
        "homeassistant:\n"
        "  auth_providers:\n"
        "    - type: trusted_networks\n"
        "      trusted_networks: [127.0.0.1/32]\n"
        "      allow_bypass_login: true\n"
        "    - type: homeassistant\n",
    )
    + "mobile_app:\n"
)

# An emulator console port of its own, so a developer's emulator is untouched.
PORT = 5580
SERIAL = f"emulator-{PORT}"


class AdbError(subprocess.CalledProcessError):
    """A failed adb command, with what adb said about it."""

    def __str__(self) -> str:
        return f"{super().__str__()}\n{self.stderr or self.output}"


@dataclass
class Device:
    """The emulator, driven through adb and uiautomator."""

    env: dict[str, str]
    shots: Path

    def adb(self, *args: str, timeout: float = 120) -> str:
        command = ["adb", "-s", SERIAL, *args]
        done = subprocess.run(
            command, env=self.env, capture_output=True, text=True, timeout=timeout
        )
        if done.returncode:
            raise AdbError(done.returncode, command, done.stdout, done.stderr)
        return done.stdout

    def nodes(self) -> list[tuple[str, tuple[int, int]]]:
        """Each node's text (or description) and centre on screen."""
        for _ in range(5):
            # uiautomator fails now and then while the screen animates.
            try:
                self.adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
                root = ET.fromstring(self.adb("exec-out", "cat", "/sdcard/ui.xml"))
                break
            except subprocess.CalledProcessError, ET.ParseError:
                time.sleep(1)
        else:
            raise RuntimeError("uiautomator could not read the screen")
        found = []
        for node in root.iter("node"):
            # Collapsed: the app's labels mix in non-breaking spaces.
            label = " ".join((node.get("text") or node.get("content-desc") or "").split())
            left, top, right, bottom = map(
                int, node.get("bounds", "[0,0][0,0]").replace("][", ",").strip("[]").split(",")
            )
            if label and right > left and bottom > top:
                found.append((label, ((left + right) // 2, (top + bottom) // 2)))
        return found

    def find(self, text: str, timeout: float = 30) -> tuple[int, int]:
        """The centre of the first node whose label contains `text`.

        Brings the Companion app back to the front if something else took
        over the screen meanwhile.
        """
        deadline = time.monotonic() + timeout
        while True:
            nodes = self.nodes()
            for label, centre in nodes:
                if text in label:
                    return centre
            # On a new image, system apps' first-run screens and a launcher
            # restart can push the app aside; monkey resumes it as it was.
            if APP not in self.foreground():
                self.adb("shell", "monkey", "-p", APP, "1")
            if time.monotonic() > deadline:
                self.screenshot("failed-" + "".join(c if c.isalnum() else "-" for c in text))
                labels = "\n".join(label for label, _ in nodes)
                raise TimeoutError(f"{text!r} is not on screen. On screen:\n{labels}")
            time.sleep(1)

    def foreground(self) -> str:
        """The resumed activity, as dumpsys names it."""
        activities = self.adb("shell", "dumpsys", "activity", "activities")
        return next((line for line in activities.splitlines() if "ResumedActivity" in line), "")

    def tap(self, text: str, timeout: float = 30) -> None:
        x, y = self.find(text, timeout)
        self.adb("shell", "input", "tap", str(x), str(y))

    def scroll_to(self, text: str) -> None:
        for _ in range(15):
            if any(text in label for label, _ in self.nodes()):
                return
            self.adb("shell", "input", "swipe", "540", "1900", "540", "700", "300")
        raise TimeoutError(f"{text!r} is not on the page")

    def screenshot(self, name: str) -> None:
        with open(self.shots / f"{name}.png", "wb") as f:
            subprocess.run(
                ["adb", "-s", SERIAL, "exec-out", "screencap", "-p"],
                env=self.env,
                check=True,
                stdout=f,
            )


@pytest.fixture(scope="module")
def device(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Device]:
    """A brand-new Pixel 8 AVD, booted, with the Companion app installed."""
    root = Path(tempfile.mkdtemp(prefix="zpmf-android-"))
    env = {
        **os.environ,
        # The dev shell's adb and emulator wrappers use this as $HOME.
        "ANDROID_SANDBOX_HOME": str(root),
        "ANDROID_USER_HOME": str(root / ".android"),
        "ANDROID_AVD_HOME": str(root / ".android" / "avd"),
        "ANDROID_EMULATOR_HOME": str(root / ".android"),
    }
    shots = Path(os.environ.get("ZPMF_SCREENSHOTS") or tmp_path_factory.mktemp("android-shots"))
    shots.mkdir(parents=True, exist_ok=True)
    subprocess.run(["create-avd"], env=env, check=True)
    log_path = root / "emulator.log"
    command = ["emulator", "-avd", "pixel_8", "-port", str(PORT)]
    command += ["-no-window", "-no-audio", "-no-boot-anim", "-no-snapshot"]
    # The emulator's own test pattern: a camera that opens, for the scanner.
    command += ["-gpu", "swiftshader_indirect", "-camera-back", "emulated"]
    phone = Device(env=env, shots=shots)
    with open(log_path, "w") as log:
        emulator = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 600
            while True:
                if emulator.poll() is not None:
                    raise RuntimeError(f"The emulator exited:\n{log_path.read_text()[-4000:]}")
                if time.monotonic() > deadline:
                    raise TimeoutError("The emulator did not boot in 600 s")
                try:
                    booted = phone.adb("shell", "getprop", "sys.boot_completed", timeout=10)
                    # The package manager can still be starting after boot.
                    if booted.strip() == "1":
                        phone.adb("shell", "pm", "path", "android", timeout=10)
                        break
                except subprocess.CalledProcessError, subprocess.TimeoutExpired:
                    pass
                time.sleep(3)
            for attempt in range(3):
                try:
                    phone.adb("install", APK, timeout=300)
                    break
                except AdbError:
                    if attempt == 2:
                        raise
                    time.sleep(10)
            for permission in ("ACCESS_LOCAL_NETWORK", "CAMERA"):
                phone.adb("shell", "pm", "grant", APP, f"android.permission.{permission}")
            # On a new image, Photos opens its sign-in screen over other apps.
            phone.adb("shell", "pm", "disable-user", "--user", "0", PHOTOS)
            yield phone
        finally:
            # Kept beside the screenshots: they say why the app or a boot failed.
            # No logcat when the emulator never came up.
            with contextlib.suppress(Exception):
                (shots / "logcat.txt").write_text(phone.adb("logcat", "-d", timeout=60))
            try:
                phone.adb("emu", "kill", timeout=30)
                emulator.wait(timeout=60)
            except Exception:
                emulator.kill()
            shutil.copy(log_path, shots / "emulator.log")
            shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def app_home() -> Iterator[Home]:
    """A brand-new Home Assistant the app logs in to without a password."""
    yield from _home(None, APP_CONFIGURATION)


def _connect_app(phone: Device, home: Home) -> None:
    """Take the app through its first run, as someone would on a new phone."""
    phone.adb("shell", "monkey", "-p", APP, "1")
    phone.tap("Connect to my Home Assistant server", timeout=120)
    phone.tap("Enter address manually", timeout=60)
    phone.tap("http://homeassistant.local")
    phone.adb("shell", "input", "keyevent", "KEYCODE_MOVE_END", *["KEYCODE_DEL"] * 30)
    port = home.url.rsplit(":", 1)[1]
    phone.adb("shell", "input", "text", f"http://10.0.2.2:{port}")
    phone.tap("Connect")
    phone.find("How would you like to name this device?", timeout=120)
    phone.tap("Save")
    phone.tap("Got it", timeout=60)
    phone.tap("Do not share my location")
    phone.tap("Less secure")
    phone.tap("Next")
    phone.tap("Do not allow")
    phone.find("Overview", timeout=120)


def _set_up_app(phone: Device) -> None:
    """Allow DevTools on the app's WebView; turn crash reports off."""
    phone.tap("Sidebar toggle")
    phone.tap("Settings")
    phone.tap("Companion app", timeout=60)
    phone.scroll_to("Crash reporting")
    phone.tap("Crash reporting")
    phone.tap("Troubleshooting")
    phone.tap("WebView remote debugging")
    phone.screenshot("settings-troubleshooting")
    phone.adb("shell", "am", "force-stop", APP)
    phone.adb("shell", "monkey", "-p", APP, "1")


@pytest.fixture(scope="module")
def app(device: Device, app_home: Home, browser: Browser) -> Iterator[Page]:
    """The app's WebView, under Playwright's control."""
    _connect_app(device, app_home)
    _set_up_app(device)
    port = _free_port()
    try:
        # The app's DevTools socket is named after its process and opens
        # before the WebView loads Home Assistant; the app can also restart,
        # or replace its first page, while it starts. A connection lists only
        # the pages there were when it was made. So until a page has Home
        # Assistant connected and stays open: find the socket, forward to
        # it, and connect again.
        deadline = time.monotonic() + 240
        while True:
            cdp = None
            try:
                pid = device.adb("shell", "pidof", APP).strip()
                socket = f"webview_devtools_remote_{pid}"
                if device.adb("shell", "cat", "/proc/net/unix").count(socket):
                    device.adb("forward", f"tcp:{port}", f"localabstract:{socket}")
                    # The session's Playwright: a second sync instance cannot
                    # run beside it.
                    cdp = browser.browser_type.connect_over_cdp(f"http://127.0.0.1:{port}")
                    pages = [p for c in cdp.contexts for p in c.pages if p.url.startswith("http")]
                    if pages:
                        page = pages[0]
                        page.wait_for_function(
                            "document.querySelector('home-assistant')?.hass?.connected",
                            timeout=30_000,
                        )
                        page.wait_for_timeout(3000)
                        if not page.is_closed():
                            break
            except AdbError, PlaywrightError:
                pass  # pidof fails while the app is not running
            if cdp:
                cdp.close()
            # The emulator's WebView sometimes crashes the app as it starts.
            if APP not in device.foreground():
                close_dialogs = [
                    "am",
                    "broadcast",
                    "-a",
                    "android.intent.action.CLOSE_SYSTEM_DIALOGS",
                ]
                device.adb("shell", *close_dialogs)
                device.adb("shell", "monkey", "-p", APP, "1")
            if time.monotonic() > deadline:
                device.screenshot("failed-webview")
                raise TimeoutError("The app's WebView did not load Home Assistant")
            time.sleep(2)
        try:
            yield page
        finally:
            cdp.close()
    finally:
        with contextlib.suppress(AdbError):  # never forwarded if it timed out
            device.adb("forward", "--remove", f"tcp:{port}")


def _open(home: Home, page: Page, card: dict) -> Locator:
    home.dashboard([card])
    port = home.url.rsplit(":", 1)[1]
    page.goto(f"http://10.0.2.2:{port}/{home.DASHBOARD}/0")
    element = page.locator(card["type"].removeprefix("custom:"))
    expect(element.locator(".title").first).to_be_visible(timeout=60_000)
    return element


# The README's phone screenshots, which scripts/phone-screenshots copies to
# images/: name, card, dark, and the range to pick first.
PHONE_SHOTS = [
    ("phone-food-diary", shots.DIARY, False, None),
    ("phone-summary", shots.SUMMARY, False, None),
    ("phone-summary-dark", shots.SUMMARY, True, None),
    ("phone-weight", shots.WEIGHT, False, "365"),
    ("phone-trends", shots.TRENDS, False, "30"),
]


def test_the_cards_show_in_the_app(app_home: Home, app: Page, device: Device) -> None:
    add_sample_data(app_home)
    try:
        for name, card, dark, range_ in PHONE_SHOTS:
            app.emulate_media(color_scheme="dark" if dark else "light")
            element = _open(app_home, app, card)
            if range_:
                pick = element.locator(f'[data-action="range"][data-range="{range_}"]')
                pick.dispatch_event("click")
                expect(pick).to_have_attribute("aria-pressed", "true")
            app.wait_for_timeout(1000)  # charts and rings animate in
            device.screenshot(name)
    finally:
        app.emulate_media(color_scheme="light")


def test_scans_a_barcode_with_the_app(app_home: Home, app: Page, device: Device) -> None:
    app_home.ws(
        {
            "type": "zp_my_fitness/food/add",
            "name": "Greek yogurt 2%",
            "kcal": 73,
            "protein": 10,
            "carbs": 3.6,
            "fat": 2,
            "barcode": BARCODE,
            "portions": [{"name": "Pot", "grams": 170}],
        }
    )
    card = _open(app_home, app, {"type": "custom:zp-food-diary-card", "person": "Debora"})
    # Clicks go through the DOM: the soft keyboard can resize the WebView
    # while Playwright aims a real click.
    card.locator('.meal[data-meal="breakfast"] [data-action="add"]').dispatch_event("click")
    card.locator('.panel [data-action="scan"]').dispatch_event("click")

    # The app's own scanner opens over the WebView, titled by the card.
    device.find("Scan a barcode", timeout=60)
    device.screenshot("app-scanner")

    # The emulator's camera cannot show a barcode, so send what the app sends
    # when it reads one. The card asks the app to close the scanner.
    app.evaluate(
        """code => document.querySelector("home-assistant").hass.auth.external.receiveMessage({
          id: 1, type: "command", command: "bar_code/scan_result",
          payload: { rawValue: code, format: "ean_13" },
        })""",
        BARCODE,
    )

    # The scan finds the saved food and picks it, with its first portion.
    expect(card.locator('.panel [data-field="grams"]')).to_have_value("170", timeout=60_000)
    expect(card.locator(".panel")).to_contain_text("Greek yogurt 2%")
    deadline = time.monotonic() + 30
    while any("Scan a barcode" in label for label, _ in device.nodes()):
        assert time.monotonic() < deadline, "The app's scanner did not close"
        time.sleep(1)
    card.locator('.panel [data-field="grams"]').scroll_into_view_if_needed()
    device.screenshot("app-scanned")
