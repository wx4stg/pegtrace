"""Write the synthetic sample photo and its ground truth.

    python scripts/make_sample.py [outdir]

Writes ``<outdir>/sample_photo.jpg`` and ``<outdir>/sample_truth.json``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pegtrace.sample import make_photo  # noqa: E402


def main(outdir: str = "examples") -> None:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    photo, truth = make_photo()
    photo.save(out / "sample_photo.jpg", quality=92)
    (out / "sample_truth.json").write_text(json.dumps(truth, indent=1))
    print(f"wrote {out / 'sample_photo.jpg'} and {out / 'sample_truth.json'}")


if __name__ == "__main__":
    main(*sys.argv[1:])
