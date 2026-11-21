#!/usr/bin/env python3
"""Download and safely flatten a one-time organization certificate bundle."""

from __future__ import annotations

import io
import re
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

BUNDLE_PATH = re.compile(r"/api/bundle/[A-Za-z0-9-]+/[A-Za-z0-9-]+\.tar\.gz\Z")
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 128


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep the one-time bearer URL from being forwarded to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fail(message: str) -> int:
    print(f"Credential bundle: {message}", file=sys.stderr)
    return 2


def is_bundle_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and not parsed.query
        and not parsed.fragment
        and BUNDLE_PATH.fullmatch(parsed.path) is not None
    )


def main() -> int:
    if len(sys.argv) != 2:
        return fail("internal usage error")

    destination = Path(sys.argv[1]).resolve()
    # The URL arrives on stdin so it does not appear in process listings/arguments.
    url = sys.stdin.read()
    if not is_bundle_url(url):
        return fail("URL does not match the one-time HTTPS organization-bundle URL format")

    request = urllib.request.Request(
        url, headers={"Accept": "application/gzip, application/octet-stream"}
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )
    try:
        with opener.open(request, timeout=30) as response:
            if response.geturl() != url or response.status != 200:
                return fail("unexpected response or redirect")
            archive_bytes = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return fail(
            f"download failed ({type(exc).__name__}); reissue a consumed one-time URL"
        )

    if len(archive_bytes) > MAX_DOWNLOAD_BYTES:
        return fail("download exceeds the 32 MiB limit")

    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            members = archive.getmembers()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS:
                return fail("archive is empty or has too many entries")

            expanded_bytes = 0
            seen_names: set[str] = set()
            for member in members:
                member_path = PurePosixPath(member.name)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or "\\" in member.name
                ):
                    return fail("archive contains an unsafe path")
                if member.isdir():
                    continue
                if not member.isfile() or member.name in seen_names:
                    return fail("archive contains links, special files, or duplicate paths")

                seen_names.add(member.name)
                expanded_bytes += member.size
                if expanded_bytes > MAX_EXPANDED_BYTES:
                    return fail("expanded archive exceeds the 64 MiB limit")

                # The wizard expects a flat credential directory. Reject basename
                # collisions rather than silently overwriting a bundle member.
                filename = member_path.name
                target = destination / filename
                if filename in {"", ".", ".."} or target.exists():
                    return fail("archive contains colliding file names")

                source = archive.extractfile(member)
                if source is None:
                    return fail("archive member could not be read")
                with target.open("xb") as output:
                    output.write(source.read(MAX_EXPANDED_BYTES + 1))
                target.chmod(0o600)
    except (tarfile.TarError, OSError, EOFError) as exc:
        return fail(f"invalid archive ({type(exc).__name__})")

    print("One-time bundle downloaded and archive structure validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
