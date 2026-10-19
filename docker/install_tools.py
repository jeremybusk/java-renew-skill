"""Install checksum-verified build tools; invoked only while building the image."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile


def install(name, entry, destination):
    algorithm = "sha512" if "sha512" in entry else "sha256"
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "download"
        with urllib.request.urlopen(entry["url"], timeout=120) as source, archive.open("wb") as target:
            shutil.copyfileobj(source, target)
        with archive.open("rb") as stream:
            checksum = hashlib.new(algorithm)
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(block)
        if checksum.hexdigest() != entry[algorithm]:
            raise ValueError(f"{name}: checksum mismatch")
        extracted = Path(directory) / "extracted"
        extracted.mkdir()
        if name == "maven":
            with tarfile.open(archive) as source:
                source.extractall(extracted, filter="data")
        else:
            with zipfile.ZipFile(archive) as source:
                for member in source.infolist():
                    path = Path(member.filename)
                    if path.is_absolute() or ".." in path.parts:
                        raise ValueError(f"{name}: unsafe archive path")
                source.extractall(extracted)
        roots = list(extracted.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError(f"{name}: unexpected archive layout")
        shutil.move(str(roots[0]), destination)
        (destination / "bin" / ("mvn" if name == "maven" else "gradle")).chmod(0o755)


def main():
    lock = json.loads(Path(__file__).with_name("toolchains.lock.json").read_text())
    Path("/opt/tools").mkdir(parents=True, exist_ok=True)
    for name in ("maven", "gradle8", "gradle9"):
        install(name, lock[name], Path("/opt/tools") / name)
    for name in ("gradle8", "gradle9"):
        (Path("/usr/local/bin") / name).symlink_to(Path("/opt/tools") / name / "bin/gradle")


if __name__ == "__main__":
    main()
