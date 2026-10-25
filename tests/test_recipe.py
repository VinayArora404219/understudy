"""The recipe is everything between the inputs and the delivered file."""
import json

from recast import recipe, scail


def test_the_recipe_carries_the_graph_that_ran_and_what_came_after(tmp_path):
    files = {}
    for name in ("r.png", "d.mp4", "out.mp4"):
        files[name] = tmp_path / name
        files[name].write_bytes(name.encode())
    rp = scail.ScailParams(drive="d.mp4", reference="r.png", prompt="In the frame, a man.", track="person",
                           people=1, replace=True, layout="portrait")
    g = scail.build(rp)
    r = recipe.write(tmp_path / "recipe.json", params=rp, g=g,
                     inputs={"reference": files["r.png"], "drive": files["d.mp4"]},
                     outputs={"recast": files["out.mp4"]}, job_id="j1", seconds=1.0,
                     finishing={"audio": "the clip's own"})
    saved = json.loads((tmp_path / "recipe.json").read_text())
    assert saved["graph"] == g and saved["graph_sha256"] == recipe.graph_sha(g)  # opens in ComfyUI as is
    assert saved["finishing"] == {"audio": "the clip's own"} and r["recipe_version"] == 2
    assert saved["inputs"]["drive"]["sha256"] == recipe.sha256(files["d.mp4"])


def test_the_exported_workflows_match_the_code():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "tools/export_workflows.py", "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + " (run tools/export_workflows.py)"
