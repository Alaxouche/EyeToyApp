"""Driver helpers: argument passing and the scripts handed to PowerShell.

Nothing here installs, removes or elevates anything. The installer is only run
in extract mode (-x), which writes the driver files and touches no system
state, and the removal script only in its dry-run form.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from eyetoy import setup_driver

WINDOWS = sys.platform == "win32"

# Characters that broke the previous, shell-based launcher: a space splits an
# unquoted argument, an apostrophe ends a PowerShell literal.
AWKWARD = "Jean O'Neil ’ test"


@unittest.skipUnless(WINDOWS, "Windows only")
class ArgumentPassingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / AWKWARD

    def tearDown(self):
        self.tmp.cleanup()

    def test_arguments_reach_the_program_intact(self):
        self.root.mkdir()
        out = self.root / "argv.txt"
        args = [str(out), "-n", setup_driver.DEVICE_NAME, "-d", str(self.root),
                'a "quoted" arg', "trailing\\"]
        script = ("import sys, pathlib; "
                  "pathlib.Path(sys.argv[1]).write_text("
                  "'\\n'.join(sys.argv[2:]), encoding='utf-8')")
        code = setup_driver.shell_execute(sys.executable, ["-c", script, *args],
                                          directory=self.root)
        self.assertEqual(code, 0)
        self.assertEqual(out.read_text(encoding="utf-8").split("\n"), args[1:])

    def test_negative_exit_code_comes_back_signed(self):
        code = setup_driver.shell_execute(
            sys.executable, ["-c", "import sys; sys.exit(-3)"])
        self.assertEqual(code, -3)
        self.assertEqual(setup_driver.describe_wdi_error(code), "access denied")
        self.assertEqual(setup_driver.describe_wdi_error(-1234), "code -1234")

    @unittest.skipIf(setup_driver.wdi_simple_path() is None,
                     "wdi-simple.exe absent")
    def test_installer_extracts_into_awkward_path(self):
        # ASCII only: wdi-simple cannot take anything else (see
        # extraction_dir), but spaces and apostrophes must get through.
        target = Path(self.tmp.name) / "Jean O'Neil" / "dossier pilote"
        target.mkdir(parents=True)
        code = setup_driver.shell_execute(
            setup_driver.wdi_simple_path(),
            setup_driver.wdi_arguments(target, extract_only=True),
            directory=target)
        self.assertEqual(code, 0)
        inf = target / setup_driver.INF_NAME
        self.assertTrue(inf.is_file())
        raw = inf.read_bytes()
        text = (raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff")
                else raw.decode("latin-1"))
        self.assertIn(f'DeviceName = "{setup_driver.DEVICE_NAME}"', text)


class ExtractionDirTest(unittest.TestCase):
    def setUp(self):
        self.saved = setup_driver.CACHE_DIR

    def tearDown(self):
        setup_driver.CACHE_DIR = self.saved

    def test_ascii_cache_is_used(self):
        setup_driver.CACHE_DIR = Path(r"C:\Users\jean\AppData\Local\EyeToyStudio")
        self.assertEqual(setup_driver.extraction_dir(),
                         setup_driver.CACHE_DIR / "driver")

    def test_accented_profile_falls_back_to_ascii(self):
        setup_driver.CACHE_DIR = Path(
            "C:\\Users\\J\u00e9r\u00f4me\\AppData\\Local\\EyeToyStudio")
        chosen = setup_driver.extraction_dir()
        self.assertTrue(str(chosen).isascii(), chosen)
        self.assertNotEqual(chosen, setup_driver.CACHE_DIR / "driver")


@unittest.skipUnless(WINDOWS, "Windows only")
class PowerShellTest(unittest.TestCase):
    def run_ps(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [setup_driver.powershell_exe(), *setup_driver._encoded(script)],
            capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_ps_quote_round_trips(self):
        for text in (AWKWARD, "''", "a‘b‚c‛d", "$env:PATH"):
            with self.subTest(text=text):
                result = self.run_ps(
                    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                    f"Write-Output {setup_driver.ps_quote(text)}")
                self.assertEqual(result.stdout.rstrip("\r\n"), text)

    def test_uninstall_dry_run_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / AWKWARD / "rapport.txt"
            report.parent.mkdir()
            result = self.run_ps(
                setup_driver.uninstall_script(report, dry_run=True))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(report.is_file())
            for line in report.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    self.assertRegex(line,
                                     r"^(driver oem\d+\.inf|certificate \w+ )")


if __name__ == "__main__":
    unittest.main()
