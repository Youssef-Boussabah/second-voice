"""Score held-out consented clips; print real scores without changing settings.

Use clips NOT used for enrollment, in ROOT/per_id/*.wav.
python backend/scripts/voice_calibrate.py --root seed/voices-held-out
"""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from app import db
from app.config import settings
from app.contracts import Person
from app.voice.speaker import embed_voice


async def main(root: Path) -> None:
    genuine: list[float] = []
    impostor: list[float] = []
    try:
        people = [Person.model_validate(doc) async for doc in db.db()[db.PEOPLE].find(
            {"user_id": settings.demo_user_id, "consent.voice": True,
             "voice_centroid": {"$ne": None}})]
        if not people:
            raise SystemExit("No consented enrolled people; calibrate after enrollment")
        print("clip\t" + "\t".join(person.id for person in people))
        for person in people:
            for clip in sorted((root / person.id).glob("*.wav")):
                vector = await embed_voice(clip.read_bytes())
                scores = [float((1 + np.dot(vector, p.voice_centroid)) / 2) for p in people]
                print(f"{person.id}/{clip.name}\t" + "\t".join(f"{s:.4f}" for s in scores))
                for candidate, score in zip(people, scores):
                    (genuine if candidate.id == person.id else impostor).append(score)
        if genuine and impostor:
            low, high = min(genuine), max(impostor)
            if low > high:
                print(f"Suggested SPEAKER_THRESHOLD={(low + high) / 2:.4f} (held-out midpoint)")
            else:
                print("Scores overlap: use manual identity; collect cleaner clips before tuning")
            print("Production also requires a 0.03 top-two margin; verify unknown speakers separately")
        else:
            print("Need held-out clips from at least two enrolled people to suggest a threshold")
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.root))
