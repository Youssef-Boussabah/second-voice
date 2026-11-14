"""Enroll consented people from ignored local WAVs via the voice REST API.

python backend/scripts/voice_enroll_seed.py --root seed/voices --url http://localhost:8000
Never writes or uploads clips for a person without server-side consent.
"""
import argparse
import asyncio
from pathlib import Path

import httpx


async def main(root: Path, url: str) -> None:
    async with httpx.AsyncClient(base_url=url, timeout=120) as client:
        for directory in sorted(root.glob("per_*")):
            clips = sorted(directory.glob("*.wav"))
            if len(clips) < 3:
                print(f"{directory.name}: skipped (need at least three clips)")
                continue
            files = [("clips[]", (clip.name, clip.read_bytes(), "audio/wav")) for clip in clips[:10]]
            response = await client.post(f"/api/people/{directory.name}/enroll", files=files)
            # Print only result status, never provider errors or audio bytes.
            print(f"{directory.name}: HTTP {response.status_code}")
            response.raise_for_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("seed/voices"))
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    asyncio.run(main(args.root, args.url))
