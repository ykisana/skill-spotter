"""Export the background-tier model chosen in config/method.extras.json.

Refits the extras fusion (gradient-boosted trees) on dev pairs, using the cached pair
scores of the chosen text and action representations, and writes it next to the config
as config/model.extras.pkl. The plugin's extras installer pins the same scikit-learn
version, so the pickle loads there.

    .venv/bin/python -m bench.export_extras
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import sklearn

from . import data as D
from .methods import fusion as F
from .run import Lab

ROOT = Path(__file__).resolve().parent.parent


def main():
    config = json.loads((ROOT / "config" / "method.extras.json").read_text())
    out = ROOT / "config" / "model.extras.pkl"
    if config["fusion"] != "gbt":
        # Linear fusers ship as coefficients inside the config; no pickle needed.
        out.unlink(missing_ok=True)
        print(f"{config['fusion']}: coefficients are in config/method.extras.json; no model file")
        return
    lab = Lab(reuse=True)
    cols = lab.pair_columns("dev", config["text"], config["actions"])
    y = np.array([p[2] for p in lab.pairs["dev"]])
    fuser = F.GradientBoosted()
    fuser.fit(cols, y)
    with out.open("wb") as f:
        pickle.dump(
            {
                "model": fuser.model,
                "features": F.FEATURES,
                "sklearn": sklearn.__version__,
                "text": config["text"],
                "actions": config["actions"],
            },
            f,
        )
    print(
        f"wrote {out} ({out.stat().st_size // 1024} KB), sklearn {sklearn.__version__}, "
        f"trained on {len(y)} dev pairs from {len(D.load('dev'))} turns"
    )


if __name__ == "__main__":
    main()
